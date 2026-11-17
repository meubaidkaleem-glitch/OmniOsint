"""Fixtures shared by every test suite.

Integration, security and end-to-end tests need a PostgreSQL database named in
the environment variable ``OMNIOSINT_TEST_DATABASE_URL``, for example::

    postgresql://omniosint:secret@127.0.0.1:5432/omniosint_test

The schema in that database is dropped and recreated at the start of every
run, so the database name must contain "test". When the variable is not set,
those tests are skipped and only the unit tests run.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import make_url

from omniosint.api.app import create_app
from omniosint.core.config import Settings
from omniosint.core.paths import AppPaths
from omniosint.database import migrate
from omniosint.database.engine import Database
from omniosint.database.seeds import seed_builtin
from tests.helpers import (
    CLEAN_STATEMENTS,
    TEST_DB_ENV,
    ApiUser,
    async_url,
    complete_setup,
    execute_sql,
    login_bearer,
    make_settings,
    run_sync,
)


@pytest.fixture(scope="session", autouse=True)
def isolated_environment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Keep the developer's OmniOSINT environment variables and data out of tests."""
    with pytest.MonkeyPatch.context() as patch:
        for key in list(os.environ):
            if key.startswith("OMNIOSINT_") and not key.startswith("OMNIOSINT_TEST_"):
                patch.delenv(key)
        patch.setenv("OMNIOSINT_HOME", str(tmp_path_factory.mktemp("default-home")))
        yield


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.resolve(tmp_path / "home")
    paths.ensure()
    return paths


@pytest.fixture
def settings(app_paths: AppPaths) -> Settings:
    """Settings without a database (for unit tests)."""
    return make_settings(app_paths)


# --------------------------------------------------------------------------- database
@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get(TEST_DB_ENV)
    if not url:
        pytest.skip(f"{TEST_DB_ENV} is not set: PostgreSQL tests are skipped")
    name = make_url(url).database or ""
    if "test" not in name:
        pytest.exit(
            f"Refusing to use database {name!r}: the test database name must contain "
            "'test' because its schema is dropped at the start of the run.",
            returncode=2,
        )
    return url


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    """Drop the schema, migrate to head and seed built-in data, once per run."""
    run_sync(
        lambda: execute_sql(
            database_url,
            "DROP SCHEMA public CASCADE",
            "CREATE SCHEMA public",
        )
    )
    migrate.upgrade(async_url(database_url))
    seed_database(database_url)
    return database_url


def seed_database(database_url: str) -> None:
    async def seed() -> None:
        settings = make_settings(AppPaths.resolve(Path.cwd()), database_url)
        database = Database.from_settings(settings)
        try:
            async with database.session() as session:
                await seed_builtin(session)
                await session.commit()
        finally:
            await database.dispose()

    run_sync(seed)


@pytest.fixture
def clean_database(migrated_database: str) -> str:
    """Remove users, sessions, audit events and process records before a test."""
    run_sync(lambda: execute_sql(migrated_database, *CLEAN_STATEMENTS))
    return migrated_database


@pytest.fixture
def db_settings(app_paths: AppPaths, clean_database: str) -> Settings:
    return make_settings(app_paths, clean_database)


# --------------------------------------------------------------------------- API
@pytest.fixture
async def app(db_settings: Settings, app_paths: AppPaths) -> AsyncIterator[FastAPI]:
    application = create_app(db_settings, paths=app_paths)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as http:
        yield http


@pytest.fixture
async def admin(client: httpx.AsyncClient, app_paths: AppPaths) -> ApiUser:
    """The first administrator, created through first-run setup, signed in with a bearer token."""
    from tests.helpers import ADMIN_PASSWORD

    await complete_setup(client, app_paths)
    return await login_bearer(client, "admin", ADMIN_PASSWORD)
