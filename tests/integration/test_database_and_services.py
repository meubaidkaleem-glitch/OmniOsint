from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import asyncpg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

import omniosint.database.models  # noqa: F401
from omniosint.audit.service import SYSTEM_ACTOR, record
from omniosint.auth.permissions import BUILTIN_ROLES, Permission
from omniosint.core.config import Settings
from omniosint.core.paths import AppPaths
from omniosint.core.timeutil import utcnow
from omniosint.database import migrate
from omniosint.database.base import Base
from omniosint.database.engine import Database
from omniosint.database.models import User, UserSession
from omniosint.database.seeds import seed_builtin
from omniosint.system import health, registry
from omniosint.workers import housekeeping
from omniosint.workers.worker import Worker
from tests.conftest import seed_database
from tests.helpers import TEST_REDIS_ENV, async_url, fetch_all, make_settings, run_sync

pytestmark = pytest.mark.integration


@pytest.fixture
async def database(db_settings: Settings, app_paths: AppPaths):  # type: ignore[no-untyped-def]
    db = Database.from_settings(db_settings, app_paths)
    yield db
    await db.dispose()


# --------------------------------------------------------------------------- schema
async def test_models_match_the_migrations(database: Database):
    def diff(connection: Connection) -> list[object]:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        return list(compare_metadata(context, Base.metadata))

    async with database.engine.connect() as connection:
        differences = await connection.run_sync(diff)
    assert differences == [], f"models and migrations disagree: {differences}"


def test_downgrade_then_upgrade_round_trip(clean_database: str):
    url = async_url(clean_database)
    migrate.downgrade(url, "base")
    tables = run_sync(
        lambda: fetch_all(
            clean_database,
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename <> 'alembic_version'",
        )
    )
    assert tables == []
    migrate.upgrade(url)
    seed_database(clean_database)
    revision = run_sync(
        lambda: fetch_all(clean_database, "SELECT version_num FROM alembic_version")
    )
    assert revision == [(migrate.head_revision(),)]


async def test_audit_trail_is_append_only(database: Database):
    async with database.session() as session:
        event = record(session, action="system.test", actor=SYSTEM_ACTOR)
        await session.commit()
        event_id = event.id

    for statement in (
        "UPDATE audit_events SET action = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ):
        async with database.engine.begin() as connection:
            with pytest.raises(DBAPIError, match="append-only"):
                await connection.execute(text(statement))

    async with database.engine.begin() as connection:
        await connection.execute(text("SET LOCAL omniosint.audit_purge = 'on'"))
        deleted = await connection.execute(
            text("DELETE FROM audit_events WHERE id = :id"), {"id": event_id}
        )
        assert deleted.rowcount == 1


async def test_seeding_is_idempotent_and_matches_the_code(database: Database):
    async with database.session() as session:
        await seed_builtin(session)
        await seed_builtin(session)
        await session.commit()
    async with database.engine.connect() as connection:
        permissions = (await connection.execute(text("SELECT code FROM permissions"))).scalars()
        assert set(permissions) == {permission.value for permission in Permission}
        rows = await connection.execute(
            text(
                "SELECT r.name, count(rp.permission_id) FROM roles r "
                "LEFT JOIN role_permissions rp ON rp.role_id = r.id GROUP BY r.name"
            )
        )
        counts = dict(rows.all())
    assert counts == {role.name: len(role.permissions) for role in BUILTIN_ROLES}


async def test_seeding_removes_permissions_no_longer_in_the_code(database: Database):
    async with database.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO permissions (id, code) VALUES (:id, 'obsolete:thing')"),
            {"id": uuid.uuid4()},
        )
    async with database.session() as session:
        await seed_builtin(session)
        await session.commit()
    async with database.engine.connect() as connection:
        codes = set((await connection.execute(text("SELECT code FROM permissions"))).scalars())
    assert "obsolete:thing" not in codes


# --------------------------------------------------------------------------- health
async def test_database_check_reports_an_unreachable_server(app_paths: AppPaths):
    settings = make_settings(
        app_paths,
        "postgresql://nobody:nothing@127.0.0.1:1/omniosint_test",
        # Not shorter: Windows retries a refused connection for about two
        # seconds before reporting it, and would report a timeout instead.
        database={"connect_timeout_seconds": 5},
    )
    db = Database.from_settings(settings)
    try:
        result = await health.check_database(db)
    finally:
        await db.dispose()
    assert result.status is health.ComponentState.UNAVAILABLE
    assert "connection refused" in result.detail
    assert "nothing" not in result.detail, "credentials must not appear in messages"


async def test_database_check_reports_a_missing_schema(clean_database: str, app_paths: AppPaths):
    empty_name = f"omniosint_test_empty_{uuid.uuid4().hex[:6]}"
    admin_url = async_url(clean_database)
    connect_args = {
        "host": admin_url.host,
        "port": admin_url.port,
        "user": admin_url.username,
        "password": admin_url.password,
        "database": admin_url.database,
    }
    connection = await asyncpg.connect(**connect_args)
    try:
        await connection.execute(f'CREATE DATABASE "{empty_name}"')
    finally:
        await connection.close()
    try:
        settings = make_settings(
            app_paths, admin_url.set(database=empty_name).render_as_string(hide_password=False)
        )
        db = Database.from_settings(settings)
        try:
            result = await health.check_database(db)
        finally:
            await db.dispose()
        assert result.status is health.ComponentState.UNAVAILABLE
        assert "omniosint db upgrade" in result.detail
    finally:
        connection = await asyncpg.connect(**connect_args)
        try:
            await connection.execute(f'DROP DATABASE IF EXISTS "{empty_name}"')
        finally:
            await connection.close()


async def test_worker_health_follows_its_heartbeat(
    database: Database, db_settings: Settings, clean_database: str
):
    assert (await health.check_worker(database, db_settings)).status.value == "unavailable"
    async with database.session() as session:
        instance_id = await registry.register(session, "worker")
    assert (await health.check_worker(database, db_settings)).status.value == "ok"

    await asyncio.to_thread(
        run_sync,
        lambda: _age_heartbeat(clean_database, instance_id),
    )
    stale = await health.check_worker(database, db_settings)
    assert stale.status.value == "unavailable" and "No heartbeat" in stale.detail
    async with database.session() as session:
        assert await registry.reap_stale(session, timedelta(seconds=60)) == 1
    assert (await health.check_worker(database, db_settings)).detail == "No worker is running."


async def _age_heartbeat(database_url: str, instance_id: uuid.UUID) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(async_url(database_url), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE service_instances "
                    "SET last_heartbeat_at = now() - interval '10 minutes' WHERE id = :id"
                ),
                {"id": instance_id},
            )
    finally:
        await engine.dispose()


async def test_redis_check(app_paths: AppPaths):
    import os

    not_configured = await health.check_redis(make_settings(app_paths))
    assert not_configured.status is health.ComponentState.NOT_CONFIGURED
    unreachable = await health.check_redis(
        make_settings(
            app_paths, redis={"url": "redis://127.0.0.1:1/0", "socket_timeout_seconds": 0.5}
        )
    )
    assert unreachable.status is health.ComponentState.UNAVAILABLE
    url = os.environ.get(TEST_REDIS_ENV)
    if not url:
        pytest.skip(f"{TEST_REDIS_ENV} is not set")
    reachable = await health.check_redis(make_settings(app_paths, redis={"url": url}))
    assert reachable.status is health.ComponentState.OK


# --------------------------------------------------------------------------- worker
async def test_housekeeping_purges_old_sessions(database: Database, db_settings: Settings):
    now = utcnow()
    async with database.session() as session:
        user = User(username="hk", display_name="hk", password_hash="x")
        session.add(user)
        await session.flush()
        for days_ago, revoked in ((30, False), (30, True), (0, False)):
            session.add(
                UserSession(
                    user_id=user.id,
                    token_hash=uuid.uuid4().hex,
                    expires_at=now - timedelta(days=days_ago) + timedelta(hours=1),
                    revoked_at=now - timedelta(days=days_ago) if revoked else None,
                )
            )
        await session.commit()
    async with database.session() as session:
        purged = await housekeeping.purge_sessions(session, retention_days=7)
    assert purged == 2


async def test_worker_runs_and_stops_cleanly(
    db_settings: Settings, app_paths: AppPaths, database: Database
):
    worker = Worker(db_settings, app_paths)
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    for _ in range(100):
        if worker.heartbeat.instance_id is not None:
            break
        await asyncio.sleep(0.05)
    assert (await health.check_worker(database, db_settings)).status.value == "ok"
    stop.set()
    await asyncio.wait_for(task, timeout=10)
    assert (await health.check_worker(database, db_settings)).status.value == "unavailable"
