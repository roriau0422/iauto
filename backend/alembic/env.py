"""Alembic environment, wired to the app's Settings and Base metadata.

- Reads the database URL from `app.platform.config.Settings`, not from
  alembic.ini, so there is a single source of truth for connection strings.
- Imports `app.platform.models_registry` which re-exports every context's
  model module, ensuring `Base.metadata` sees every table before autogenerate
  computes a diff.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Pull the app Settings + declarative base. Importing models_registry has the
# side effect of registering every model with Base.metadata.
from app.platform import models_registry  # noqa: F401
from app.platform.base import Base
from app.platform.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Choose database URL from Settings. `alembic -x db=test ...` targets the
# test database (used in CI and by the integration test fixture).
settings = get_settings()
_x_args = context.get_x_argument(as_dictionary=True)
_target_db = _x_args.get("db", "main")
if _target_db == "test":
    if settings.database_test_url_str is None:
        raise RuntimeError("DATABASE_TEST_URL not configured but -x db=test was passed")
    _chosen_url = settings.database_test_url_str
else:
    _chosen_url = settings.database_url_str
config.set_main_option("sqlalchemy.url", _chosen_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without actually connecting.

    Useful for reviewing a migration in CI. Not part of the normal dev loop.
    """
    context.configure(
        url=settings.database_url_str,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
