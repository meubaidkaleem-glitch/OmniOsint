"""Database bootstrap (used by the installer) and the backup commands."""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import make_url

from omniosint.backup import pgtools
from omniosint.core.errors import ValidationFailed
from omniosint.database.bootstrap import bootstrap_database, scram_verifier, validate_identifier
from tests.integration.test_cli import cli_env, run_cli

pytestmark = pytest.mark.integration

ADMIN_URL_ENV = "OMNIOSINT_TEST_ADMIN_DATABASE_URL"


def test_scram_verifier_format() -> None:
    verifier = scram_verifier("correct horse battery", salt=b"0123456789abcdef")
    assert verifier is not None
    assert verifier.startswith("SCRAM-SHA-256$4096:")
    assert "correct horse battery" not in verifier
    assert scram_verifier("pässwörd") is None, "non-ASCII passwords are sent as-is"


@pytest.mark.parametrize("name", ["Upper", "1leading", "has-dash", "x;drop", "a" * 64, ""])
def test_identifiers_are_validated(name: str) -> None:
    with pytest.raises(ValidationFailed):
        validate_identifier(name, "role")


@pytest.fixture
def admin_url() -> str:
    url = os.environ.get(ADMIN_URL_ENV)
    if not url:
        pytest.skip(f"{ADMIN_URL_ENV} is not set (needs a role that may create roles)")
    return url


async def test_bootstrap_creates_a_working_role_and_database(admin_url: str) -> None:
    admin = make_url(admin_url)
    suffix = uuid.uuid4().hex[:8]
    role, database = f"omni_role_{suffix}", f"omni_db_{suffix}"
    password = f"pw-{uuid.uuid4().hex}"
    common = {
        "host": admin.host or "127.0.0.1",
        "port": admin.port or 5432,
        "admin_user": admin.username or "postgres",
        "admin_password": admin.password,
        "admin_database": admin.database or "postgres",
        "role": role,
        "database": database,
    }
    try:
        first = await bootstrap_database(role_password=password, **common)
        assert (first.role_created, first.database_created) == (True, True)

        # The verifier we sent must let the role sign in with the plain password.
        connection = await asyncpg.connect(
            host=common["host"],
            port=common["port"],
            user=role,
            password=password,
            database=database,
        )
        owner = await connection.fetchval(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = $1", database
        )
        await connection.close()
        assert owner == role

        again = await bootstrap_database(role_password="something-else-entirely", **common)
        assert (again.role_created, again.role_password_set, again.database_created) == (
            False,
            False,
            False,
        ), "an existing role is left untouched"
        reset = await bootstrap_database(
            role_password="a-new-password-value", reset_password=True, **common
        )
        assert reset.role_password_set is True
    finally:
        connection = await asyncpg.connect(
            host=common["host"],
            port=common["port"],
            user=common["admin_user"],
            password=admin.password,
            database=common["admin_database"],
        )
        try:
            # A non-superuser administrator must be able to switch to the owner
            # before it may drop the database, just as when creating it.
            with contextlib.suppress(asyncpg.UndefinedObjectError):
                await connection.execute(f'GRANT "{role}" TO CURRENT_USER')
            await connection.execute(f'DROP DATABASE IF EXISTS "{database}"')
            await connection.execute(f'DROP ROLE IF EXISTS "{role}"')
        finally:
            await connection.close()


@pytest.mark.skipif(
    any(pgtools.find_tool(tool) is None for tool in ("pg_dump", "pg_restore", "psql")),
    reason="PostgreSQL client tools are not installed",
)
def test_backup_commands(tmp_path: Path, clean_database: str) -> None:
    env = cli_env(tmp_path, clean_database)
    created = run_cli("backup", "create", "--label", "cli", "--json", env=env)
    assert created.returncode == 0, created.stdout + created.stderr
    archive = Path(json.loads(created.stdout)["path"])
    assert archive.is_file() and archive.name.endswith("-cli.zip")

    listing = json.loads(run_cli("backup", "list", "--json", env=env).stdout)
    assert [item["name"] for item in listing["backups"]] == [archive.name]
    assert run_cli("backup", "verify", str(archive), env=env).returncode == 0

    bad_label = run_cli("backup", "create", "--label", "no spaces!", env=env)
    assert bad_label.returncode == 1

    without_raw = run_cli("backup", "create", "--label", "noraw", "--no-raw-responses", env=env)
    assert without_raw.returncode == 0, without_raw.stdout + without_raw.stderr
    assert "Raw responses left out" in without_raw.stdout

    declined = run_cli("backup", "restore", str(archive), env=env, stdin="n\n")
    assert declined.returncode == 2 and "Nothing was changed" in declined.stdout
    restored = run_cli("backup", "restore", str(archive), "--yes", "--no-safety-backup", env=env)
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert "Restore complete" in restored.stdout
    assert "Raw responses: 0 restored" in restored.stdout
