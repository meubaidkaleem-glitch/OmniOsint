"""Alembic environment.

Normally invoked through :mod:`omniosint.database.migrate`, which passes the
database URL in ``config.attributes``. When Alembic is run directly, the URL is
resolved from the OmniOSINT settings instead.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import URL, Connection, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

import omniosint.database.models  # noqa: F401  (registers every table)
from omniosint.database.base import Base

config = context.config
target_metadata = Base.metadata

# Serialises concurrent upgrades (for example two processes starting at once).
_MIGRATION_LOCK_ID = 7_304_815_001


def _resolve_url() -> URL:
    url = config.attributes.get("sqlalchemy_url")
    if url is not None:
        return url  # type: ignore[no-any-return]
    from omniosint.core.config import load_settings
    from omniosint.core.paths import AppPaths
    from omniosint.database.engine import build_database_url

    paths = AppPaths.resolve()
    return build_database_url(load_settings(paths), paths)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (``--sql`` mode)."""
    context.configure(
        url=_resolve_url().render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": _MIGRATION_LOCK_ID}
        )
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_resolve_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
    else:
        asyncio.run(_run_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
