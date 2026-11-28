"""FastAPI application entry point (`uvicorn app.main:app`).

`create_app()` builds the app; tests call it too and put their own engine and clock on
`app.state`, so they run the exact middleware, guards and routes that ship.
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.clock import clock_from_settings, parse_app_now
from app.clock_anchor import anchored_clock
from app.config import Settings, get_settings
from app.db import application_name, make_engine, make_sessionmaker, pool_status, wait_for_db
from app.errors import install_error_handlers
from app.logging import RequestLogMiddleware, setup_logging
from app.realtime import CLOSE, Hub, Listener, asyncpg_dsn, on_shutdown_signal
from app.routers import meetings as meeting_routes
from app.routers import session as session_routes
from app.routers import teams as team_routes
from app.security import API_PREFIX, ApiGuardMiddleware

log = logging.getLogger("eos.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings, settings.database_url, application_name("eos-api:pool"))
        await wait_for_db(engine)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        if settings.app_clock_mode == "ticking":
            # One business clock for every worker and across restarts (plan 3.2).
            app.state.clock = await anchored_clock(engine, parse_app_now(settings.app_now))
        # This worker's LISTEN connection feeds its SSE streams (plan 3.7, 3.12).
        listener = Listener(
            asyncpg_dsn(settings.database_url), app.state.hub, application_name("eos-api:listen")
        )
        await listener.start()
        app.state.listener = listener
        restore_signals = on_shutdown_signal(lambda: app.state.hub.broadcast(CLOSE))
        log.info("api started", extra={"env": settings.app_env, "version": settings.version})
        try:
            yield
        finally:
            restore_signals()
            app.state.hub.broadcast(CLOSE)  # open streams end; EventSource reconnects
            await listener.stop()
            await engine.dispose()
            log.info("api stopped")

    app = FastAPI(
        title="EOS Level 10 API",
        version=settings.version,
        description=(
            "Scorecard, Rocks, To-Dos, Issues and the live Level 10 Meeting. "
            "Contracts: docs/API_CONTRACTS.md."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        debug=False,
    )
    app.state.settings = settings
    # Frozen mode: exactly APP_NOW. Ticking mode: replaced in lifespan by the clock anchored
    # in the database (app/clock_anchor.py), so this process-local one is only a fallback
    # for code that builds the app without running lifespan (tests set their own).
    app.state.clock = clock_from_settings(settings)
    app.state.hub = Hub()

    install_error_handlers(app)
    # Added first = runs inside RequestLogMiddleware, so its refusals carry the request id.
    app.add_middleware(
        ApiGuardMiddleware,
        web_origins=settings.web_origin_list,
        max_body_bytes=settings.max_body_bytes,
    )
    app.add_middleware(
        RequestLogMiddleware,
        log_payloads=settings.log_payloads,
        body_limit=settings.log_body_limit,
        trusted_proxy_hosts=settings.trusted_proxy_host_list,
    )

    @app.get("/healthz", tags=["Health"], summary="Liveness, database and pool check")
    async def healthz(request: Request) -> JSONResponse:
        engine = request.app.state.engine
        listener = getattr(request.app.state, "listener", None)

        async def ping() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        try:
            # Plan 3.12: a connection and SELECT 1 within 1 s, or the database counts as down.
            await asyncio.wait_for(ping(), timeout=1.0)
            db_status = "ok"
        except Exception:  # noqa: BLE001 - report, don't crash the probe
            log.warning("healthz: database unreachable", exc_info=True)
            db_status = "error"
        status = "ok" if db_status == "ok" else "error"
        return JSONResponse(
            status_code=200 if status == "ok" else 503,
            content={
                "status": status,
                "db": db_status,
                "pool": pool_status(engine),
                # Degraded real-time doesn't fail the healthcheck (the app still works),
                # but it shows here: "reconnecting" means live updates are paused.
                "realtime": {
                    "listener": listener.status if listener else "off",
                    "streams": request.app.state.hub.stream_count(),
                },
                # Which Uvicorn worker answered (layer L1): pool and stream counts are per
                # worker, so repeated probes can show different numbers.
                "worker": os.getpid(),
                "version": settings.version,
            },
        )

    api = APIRouter(prefix=API_PREFIX)

    @api.get("/ping", tags=["Health"], summary="Round-trip check through the web proxy")
    async def ping() -> dict[str, str]:
        return {"pong": "ok"}

    api.include_router(session_routes.router)
    api.include_router(team_routes.router)
    api.include_router(meeting_routes.router)
    app.include_router(api)
    return app


setup_logging(get_settings().log_level)
app = create_app()
