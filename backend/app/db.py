"""Database engine lifecycle (plan 3.12).

One async engine per process, created in FastAPI's lifespan (never at import time,
because each Uvicorn worker is its own process and must own its own pool).
"""

import asyncio
import logging
import os
import socket
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

log = logging.getLogger("eos.db")


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Request-scoped session (plan 3.12 item 4): one transaction per request, committed
    when the handler succeeds, rolled back on any error, connection always returned.

    Use it through `DbSession`, never a bare `Depends(get_session)`: FastAPI's default
    dependency scope ("request") runs the code after `yield` only after the response has
    been sent, so the commit would happen after the client already saw a 2xx and a failed
    commit could never become a 500."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session, session.begin():
        yield session


# scope="function": commit (or roll back) before the response is sent.
DbSession = Annotated[AsyncSession, Depends(get_session, scope="function")]


def pool_status(engine: AsyncEngine) -> dict[str, int]:
    """Pool counters for /healthz (no hostnames or credentials). A NullPool (tests, CLIs)
    keeps no connections, so it reports zeros instead of failing the probe."""
    pool = engine.pool
    if not hasattr(pool, "checkedout"):
        return {"size": 0, "open": 0, "checked_out": 0, "overflow": 0}
    checked_out = pool.checkedout()  # type: ignore[attr-defined]
    return {
        "size": pool.size(),  # type: ignore[attr-defined]  configured steady size
        "open": pool.checkedin() + checked_out,  # type: ignore[attr-defined]
        "checked_out": checked_out,
        # SQLAlchemy's overflow() is negative until the pool has filled up; report only
        # connections actually opened beyond the steady size.
        "overflow": max(pool.overflow(), 0),  # type: ignore[attr-defined]
    }


def application_name(component: str) -> str:
    """Postgres application_name, max 63 chars: eos-api:pool:<hostname>:<pid>."""
    return f"{component}:{socket.gethostname()}:{os.getpid()}"[:63]


def make_engine(
    settings: Settings,
    url: str,
    app_name: str,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=settings.db_pool_size if pool_size is None else pool_size,
        max_overflow=settings.db_max_overflow if max_overflow is None else max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_recycle=settings.db_pool_recycle_s,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "application_name": app_name,
                "statement_timeout": str(settings.db_statement_timeout_ms),
                "idle_in_transaction_session_timeout": str(settings.db_idle_in_tx_timeout_ms),
            }
        },
    )


async def wait_for_db(engine: AsyncEngine, *, attempts: int = 30, delay_s: float = 1.0) -> None:
    """SELECT 1 with retry, so a slow first boot or a DB restart doesn't crash startup."""
    for attempt in range(1, attempts + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 - any connection error means "retry"
            if attempt == attempts:
                raise
            log.warning(
                "database not ready, retrying",
                extra={"attempt": attempt, "error": type(exc).__name__},
            )
            await asyncio.sleep(delay_s)


class LeakWatch:
    """Pool leak watch (plan 3.12 item 7, layer L5): a warning in the logs, with the
    request id that took it, when a connection stays checked out of this worker's pool
    longer than `threshold_s`.

    Two signals: `run()` checks every second and warns once about a connection that is
    still out (a real leak never comes back, so waiting for its return would never fire),
    and the return itself logs how long it was held. Transactions here are short (a 5 s
    statement timeout, 10 s idle-in-transaction timeout, SSE never holds a connection), so
    either line means a bug worth finding by its request id.
    """

    def __init__(self, engine: AsyncEngine, threshold_s: float = 5.0) -> None:
        # Deferred: app.logging imports nothing from here, but keep the module light.
        from app.logging import request_id_var

        self._request_id = request_id_var
        self.threshold_s = threshold_s
        self.out: dict[int, tuple[float, str | None]] = {}  # connection record -> taken
        self.warned: set[int] = set()
        self.pool = engine.sync_engine.pool
        event.listen(self.pool, "checkout", self._checkout)
        event.listen(self.pool, "checkin", self._checkin)

    def _checkout(self, _dbapi: object, record: object, _proxy: object) -> None:
        self.out[id(record)] = (time.monotonic(), self._request_id.get())

    def _checkin(self, _dbapi: object, record: object) -> None:
        taken = self.out.pop(id(record), None)
        self.warned.discard(id(record))
        if taken is None:
            return
        held_s = time.monotonic() - taken[0]
        if held_s > self.threshold_s:
            log.warning(
                "db connection returned after a long checkout",
                extra={"held_ms": round(held_s * 1000), "request_id": taken[1]},
            )

    def check(self) -> None:
        now = time.monotonic()
        for key, (since, request_id) in list(self.out.items()):
            if now - since > self.threshold_s and key not in self.warned:
                self.warned.add(key)
                log.warning(
                    f"db connection checked out for more than {self.threshold_s:g} s",
                    extra={"held_ms": round((now - since) * 1000), "request_id": request_id},
                )

    async def run(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            self.check()

    def stop(self) -> None:
        event.remove(self.pool, "checkout", self._checkout)
        event.remove(self.pool, "checkin", self._checkin)


async def connection_budget(engine: AsyncEngine, settings: Settings) -> dict[str, int]:
    """What this API can open at most, against the server's max_connections (plan 3.12):
    API_WORKERS x (pool + overflow + its LISTEN connection). Logged once at startup
    (app/preflight.py), as a warning above 80 %, so a scale-up that can't fit shows up
    at once instead of under load."""
    async with engine.connect() as conn:
        limit = int((await conn.execute(text("SHOW max_connections"))).scalar_one())
    per_worker = settings.db_pool_size + settings.db_max_overflow + 1
    budget = {
        "workers": settings.api_workers,
        "per_worker": per_worker,
        "total": settings.api_workers * per_worker,
        "max_connections": limit,
        "percent": round(100 * settings.api_workers * per_worker / limit),
    }
    if budget["percent"] > 80:
        log.warning("db connection budget above 80% of max_connections", extra=budget)
    else:
        log.info("db connection budget", extra=budget)
    return budget
