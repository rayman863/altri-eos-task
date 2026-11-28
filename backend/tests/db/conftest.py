"""Fixtures for tests against a real Postgres: the separate eos_test database (plan 6)."""

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app import seed
from app.cache import rotate_generation
from app.config import Settings, get_settings

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def settings() -> Settings:
    s = get_settings()
    for url in (s.database_url, s.owner_database_url, s.readonly_database_url):
        database = make_url(url).database or ""
        if not database.endswith("_test"):
            pytest.exit(f"refusing to run DB tests against {database!r}: not a *_test database")
    return s


@pytest.fixture(scope="session")
def migrated(settings: Settings) -> Settings:
    subprocess.run(["alembic", "upgrade", "head"], cwd=BACKEND, check=True)
    return settings


def reseed(settings: Settings, *, reset: bool, seed_path: Path | None = None) -> dict[str, int]:
    inserted = asyncio.run(
        seed.run(
            reset=reset,
            seed_path=seed_path or Path(settings.seed_path),
            database_url=settings.owner_database_url,
        )
    )
    if settings.cache_enabled:  # like `python -m app.seed`: nothing cached survives a seed
        asyncio.run(rotate_generation(settings))
    return inserted


def engine_for(url: str) -> AsyncEngine:
    """Short-lived test engine, named `eos-test` in pg_stat_activity (plan 3.12)."""
    return create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"application_name": "eos-test"}},
    )


@pytest.fixture
def seeded(migrated: Settings) -> Settings:
    reseed(migrated, reset=True)
    return migrated


async def _fetch(url: str, sql: str, params: dict[str, Any]) -> list[Any]:
    engine = engine_for(url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params)
            return result.all() if result.returns_rows else []
    finally:
        await engine.dispose()


def query(url: str, sql: str, **params: Any) -> list[Any]:
    """Run SQL and commit."""
    return asyncio.run(_fetch(url, sql, params))


async def _attempt(url: str, statements: list[str], params: dict[str, Any]) -> None:
    engine = engine_for(url)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                for statement in statements:
                    await conn.execute(text(statement), params)
            finally:
                await transaction.rollback()  # never leave anything behind
    finally:
        await engine.dispose()


def db_error(url: str, *statements: str, **params: Any) -> tuple[str | None, str]:
    """Run statements in a rolled-back transaction; return (SQLSTATE, message) of the
    error they raise, or (None, "") if they succeed."""
    try:
        asyncio.run(_attempt(url, list(statements), params))
    except DBAPIError as exc:
        cause = exc.orig.__cause__ if exc.orig is not None else None
        sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(cause, "sqlstate", None)
        return sqlstate, str(exc)
    return None, ""
