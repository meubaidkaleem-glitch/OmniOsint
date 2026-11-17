"""Helpers shared by the test suites."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import socket
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from omniosint.core.config import Settings, deep_merge, load_settings
from omniosint.core.paths import AppPaths

TEST_DB_ENV = "OMNIOSINT_TEST_DATABASE_URL"
TEST_REDIS_ENV = "OMNIOSINT_TEST_REDIS_URL"

# Low Argon2 cost keeps the suite fast; production defaults are tested separately.
FAST_ARGON2 = {"argon2_time_cost": 1, "argon2_memory_kib": 8192, "argon2_parallelism": 1}

ADMIN_PASSWORD = "correct horse battery staple"
USER_PASSWORD = "another long passphrase"


def run_sync[T](factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run a coroutine to completion on a separate thread with its own loop.

    Used from synchronous fixtures and tests so that the event loop pytest-asyncio
    manages on the main thread is never disturbed.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()


def make_settings(
    paths: AppPaths, database_url: str | None = None, **sections: dict[str, Any]
) -> Settings:
    """Hermetic settings: no YAML or .env files, fast hashing, quiet logging."""
    overrides: dict[str, Any] = {
        "environment": "test",
        "auth": dict(FAST_ARGON2),
        "logging": {"file_enabled": False, "access_log": False, "level": "WARNING"},
        "server": {"serve_frontend": False},
    }
    if database_url is not None:
        overrides["database"] = {"url": database_url, "pool_size": 2, "max_overflow": 2}
    overrides = deep_merge(overrides, sections)
    return load_settings(paths, overrides=overrides, use_files=False)


def async_url(database_url: str) -> URL:
    return make_url(database_url).set(drivername="postgresql+asyncpg")


async def execute_sql(database_url: str, *statements: str) -> None:
    engine = create_async_engine(async_url(database_url), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def fetch_all(database_url: str, statement: str, **params: Any) -> list[Any]:
    engine = create_async_engine(async_url(database_url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(text(statement), params)).all())
    finally:
        await engine.dispose()


CLEAN_STATEMENTS = (
    "SET LOCAL omniosint.audit_purge = 'on'",
    "TRUNCATE users, user_roles, user_sessions, audit_events, service_instances CASCADE",
    "DELETE FROM system_settings WHERE key <> 'instance'",
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def unique_name(prefix: str = "user") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


@dataclass
class ApiUser:
    """A signed-in API caller using a bearer session."""

    username: str
    token: str
    permissions: list[str] = field(default_factory=list)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


async def complete_setup(
    client: httpx.AsyncClient,
    paths: AppPaths,
    *,
    username: str = "admin",
    password: str = ADMIN_PASSWORD,
) -> dict[str, Any]:
    status = (await client.get("/api/v1/auth/setup-status")).json()
    assert status["setup_required"] is True
    token = Path(status["token_file"]).read_text(encoding="utf-8").strip()
    response = await client.post(
        "/api/v1/auth/setup",
        json={"setup_token": token, "username": username, "password": password},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def login_cookie(
    client: httpx.AsyncClient, username: str = "admin", password: str = ADMIN_PASSWORD
) -> str:
    """Sign in with a browser-style cookie session. Returns the CSRF token."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


async def login_bearer(
    client: httpx.AsyncClient, username: str, password: str, *, client_type: str = "api"
) -> ApiUser:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
            "session_type": "bearer",
            "client": client_type,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return ApiUser(username=username, token=body["access_token"], permissions=body["permissions"])


async def create_user(
    client: httpx.AsyncClient,
    admin: ApiUser,
    *,
    username: str | None = None,
    roles: list[str] | None = None,
    password: str = USER_PASSWORD,
    must_change_password: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/admin/users",
        headers=admin.headers,
        json={
            "username": username or unique_name(),
            "password": password,
            "roles": roles or ["analyst"],
            "must_change_password": must_change_password,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def clean_environment() -> dict[str, str]:
    """A copy of the environment without OmniOSINT settings from the developer's shell."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("OMNIOSINT_") or key.startswith("OMNIOSINT_TEST_")
    }
