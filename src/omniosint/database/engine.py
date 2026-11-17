"""Database engine and session management."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import URL, make_url, text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from omniosint.core.config import DatabaseSettings, Settings
from omniosint.core.errors import ConfigurationError
from omniosint.core.paths import AppPaths
from omniosint.core.secrets import DATABASE_PASSWORD, SecretStore, SecretStoreError

ASYNC_DRIVER = "postgresql+asyncpg"

# Environments a test or a container may use to supply the password without
# touching the secret store.
_SSL_QUERY_KEYS = ("sslmode", "ssl")


def build_database_url(settings: Settings, paths: AppPaths | None = None) -> URL:
    """Return the effective database URL.

    Password resolution order: ``database.url`` or ``database.password`` from the
    environment, then the protected secret store.
    """
    db = settings.database
    if db.url is not None:
        try:
            url = make_url(db.url.get_secret_value())
        except ArgumentError as exc:
            raise ConfigurationError("database.url is not a valid database URL.") from exc
        if url.get_backend_name() not in ("postgresql", "postgres"):
            raise ConfigurationError(
                "OmniOSINT requires PostgreSQL; database.url points at "
                f"{url.get_backend_name()!r}."
            )
        query = {key: value for key, value in url.query.items() if key not in _SSL_QUERY_KEYS}
        url = url.set(drivername=ASYNC_DRIVER, query=query)
    else:
        url = URL.create(
            ASYNC_DRIVER,
            username=db.user,
            password=db.password.get_secret_value() if db.password else None,
            host=db.host,
            port=db.port,
            database=db.name,
        )

    if url.password is None and paths is not None:
        try:
            stored = SecretStore(paths).get(DATABASE_PASSWORD)
        except SecretStoreError as exc:
            raise ConfigurationError(str(exc)) from exc
        if stored:
            url = url.set(password=stored)
    return url


def ssl_mode_for(settings: DatabaseSettings) -> str:
    """SSL mode, honouring ``sslmode`` in ``database.url`` when present."""
    if settings.url is not None:
        try:
            query = make_url(settings.url.get_secret_value()).query
        except ArgumentError:
            query = {}
        value = query.get("sslmode") or query.get("ssl")
        if isinstance(value, str) and value:
            return value
    return settings.ssl_mode


class Database:
    """Owns the engine and hands out sessions."""

    def __init__(
        self,
        url: URL,
        settings: DatabaseSettings,
        *,
        application_name: str = "omniosint",
        statement_timeout_ms: int | None = None,
    ) -> None:
        timeout_ms = (
            settings.statement_timeout_ms if statement_timeout_ms is None else statement_timeout_ms
        )
        server_settings = {"application_name": application_name}
        if timeout_ms:
            server_settings["statement_timeout"] = str(timeout_ms)
        connect_args: dict[str, Any] = {
            "timeout": settings.connect_timeout_seconds,
            "server_settings": server_settings,
            "ssl": ssl_mode_for(settings),
        }
        self._url = url
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_timeout=settings.pool_timeout_seconds,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        paths: AppPaths | None = None,
        *,
        application_name: str = "omniosint",
        statement_timeout_ms: int | None = None,
    ) -> Database:
        return cls(
            build_database_url(settings, paths),
            settings.database,
            application_name=application_name,
            statement_timeout_ms=statement_timeout_ms,
        )

    @property
    def url(self) -> URL:
        return self._url

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    def session(self) -> AsyncSession:
        return self._sessions()

    async def ping(self) -> float:
        """Run a trivial query and return the round-trip time in milliseconds."""
        started = time.perf_counter()
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return (time.perf_counter() - started) * 1000.0

    async def server_version(self) -> tuple[int, str]:
        """Return ``(server_version_num, human readable version)``."""
        async with self._engine.connect() as connection:
            number = (await connection.execute(text("SHOW server_version_num"))).scalar_one()
            label = (await connection.execute(text("SHOW server_version"))).scalar_one()
        return int(number), str(label)

    async def dispose(self) -> None:
        await self._engine.dispose()


def describe_target(url: URL) -> str:
    """Human-readable connection target without credentials."""
    host = url.host or "localhost"
    port = url.port or 5432
    return f"{url.username or ''}@{host}:{port}/{url.database or ''}".lstrip("@")
