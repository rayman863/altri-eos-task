"""Alembic migration environment (async, runs as eos_owner)."""

import asyncio

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.config import get_settings

settings = get_settings()

# Phase 2 sets this to the models' MetaData so `alembic revision --autogenerate` works.
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=settings.owner_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(
        settings.owner_database_url,
        poolclass=pool.NullPool,
        connect_args={"server_settings": {"application_name": "eos-migrate"}},
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
