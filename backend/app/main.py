"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import application_name, make_engine, wait_for_db
from app.errors import install_error_handlers
from app.logging import RequestLogMiddleware, setup_logging

settings = get_settings()
setup_logging(settings.log_level)
log = logging.getLogger("eos.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = make_engine(settings, settings.database_url, application_name("eos-api:pool"))
    await wait_for_db(engine)
    app.state.engine = engine
    log.info("api started", extra={"env": settings.app_env, "version": settings.version})
    try:
        yield
    finally:
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
)
install_error_handlers(app)
app.add_middleware(
    RequestLogMiddleware,
    log_payloads=settings.log_payloads,
    body_limit=settings.log_body_limit,
    trusted_proxy_hosts=settings.trusted_proxy_host_list,
)


@app.get("/healthz", tags=["Health"], summary="Liveness and database check")
async def healthz() -> JSONResponse:
    try:
        async with app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:  # noqa: BLE001 - report, don't crash the probe
        log.warning("healthz: database unreachable", exc_info=True)
        db_status = "error"
    status = "ok" if db_status == "ok" else "error"
    return JSONResponse(
        status_code=200 if status == "ok" else 503,
        content={"status": status, "db": db_status, "version": settings.version},
    )


api = APIRouter(prefix="/api/v1")


@api.get("/ping", tags=["Health"], summary="Round-trip check through the web proxy")
async def ping() -> dict[str, str]:
    return {"pong": "ok"}


app.include_router(api)
