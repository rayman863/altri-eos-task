"""Alembic migration environment (async, runs as eos_owner)."""

import asyncio

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.config import get_settings
from app.models import Base

settings = get_settings()

# `alembic revision --autogenerate` and `alembic check` compare against these models;
# a test runs `alembic check` so models and migrations can't drift apart.
target_metadata = Base.metadata

# The rules report migrates its own scratch database through Alembic's command API and
# passes the URL in `config.attributes`; everything else uses OWNER_DATABASE_URL.
database_url: str = context.config.attributes.get("database_url") or settings.owner_database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# The default privileges from db/init give eos_app data access to every table eos_owner
# creates, which would include Alembic's own bookkeeping table. The API must never be
# able to change the recorded revision, so take that back after every upgrade.
_PROTECT_VERSION_TABLE = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eos_app')
     AND to_regclass('public.alembic_version') IS NOT NULL THEN
    REVOKE ALL ON TABLE public.alembic_version FROM eos_app;
  END IF;
END
$$;
"""


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
        connection.execute(text(_PROTECT_VERSION_TABLE))


async def run_async_migrations() -> None:
    engine = create_async_engine(
        database_url,
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
