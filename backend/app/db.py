"""Database engine lifecycle (plan 3.12).

One async engine per process, created in FastAPI's lifespan (never at import time,
because each Uvicorn worker is its own process and must own its own pool).
"""

import asyncio
import logging
import os
import socket
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import text
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
    """Pool counters for /healthz (no hostnames or credentials)."""
    pool = engine.pool
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
