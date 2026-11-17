"""The command-line interface, run as a real subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import FAST_ARGON2, USER_PASSWORD, clean_environment

pytestmark = pytest.mark.integration

PLANNED = "Planned — integration not yet implemented"


def cli_env(home: Path, database_url: str | None = None, **extra: str) -> dict[str, str]:
    environment = clean_environment()
    environment["OMNIOSINT_HOME"] = str(home)
    environment["OMNIOSINT_ENVIRONMENT"] = "test"
    environment["PYTHONIOENCODING"] = "utf-8"
    for key, value in FAST_ARGON2.items():
        environment[f"OMNIOSINT_AUTH__{key.upper()}"] = str(value)
    if database_url:
        environment["OMNIOSINT_DATABASE__URL"] = database_url
    environment.update(extra)
    return environment


def run_cli(
    *arguments: str, env: dict[str, str], stdin: str | None = None, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "omniosint", *arguments],
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def test_version_and_help(tmp_path: Path):
    env = cli_env(tmp_path)
    version = run_cli("--version", env=env)
    assert version.returncode == 0 and version.stdout.startswith("OmniOSINT ")
    help_text = run_cli("--help", env=env)
    for command in ("start", "stop", "status", "doctor", "providers", "backup", "admin"):
        assert command in help_text.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ("cases", "list"),
        ("reports", "list"),
        ("monitoring", "list"),
        ("search", "--input", "example.com"),
        ("investigate", "--input", "example.com"),
        ("graph", "export", "--case", "C-1", "--format", "graphml"),
        ("report", "generate", "--case", "C-1", "--format", "pdf"),
    ],
)
def test_planned_commands_say_so_and_fail(tmp_path: Path, arguments: tuple[str, ...]):
    result = run_cli(*arguments, env=cli_env(tmp_path))
    assert result.returncode == 2
    assert PLANNED in result.stdout


def test_provider_commands_never_pretend(tmp_path: Path):
    env = cli_env(tmp_path)
    listing = run_cli("providers", "list", "--json", env=env)
    assert listing.returncode == 0
    body = json.loads(listing.stdout)
    assert body["counts"]["available"] == 0
    assert all(item["status"] != "available" for item in body["providers"])
    tested = run_cli("providers", "test", "--json", env=env)
    assert tested.returncode == 2
    assert json.loads(tested.stdout)["tested"] == 0


def test_configuration_errors_exit_with_code_3(tmp_path: Path):
    env = cli_env(tmp_path)
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "settings.yaml").write_text("sever: {}\n", encoding="utf-8")
    result = run_cli("config", "validate", env=env)
    assert result.returncode == 3
    assert "sever" in result.stdout
    doctor = run_cli("doctor", "--json", env=env)
    assert doctor.returncode == 1
    checks = {item["name"]: item for item in json.loads(doctor.stdout)["checks"]}
    assert checks["Configuration"]["status"] == "fail"


def test_config_show_masks_secrets(tmp_path: Path):
    env = cli_env(tmp_path, OMNIOSINT_DATABASE__PASSWORD="canary-password-value")
    result = run_cli("config", "show", "--json", env=env)
    assert result.returncode == 0
    assert "canary-password-value" not in result.stdout
    assert json.loads(result.stdout)["database"]["password"] == "**********"


def test_secrets_are_stored_without_echoing_values(tmp_path: Path):
    env = cli_env(tmp_path)
    stored = run_cli("secrets", "set", "database.password", "--stdin", env=env, stdin="s3cr3t-x\n")
    assert stored.returncode == 0 and "s3cr3t-x" not in stored.stdout + stored.stderr
    listing = run_cli("secrets", "list", env=env)
    assert "database.password" in listing.stdout and "s3cr3t-x" not in listing.stdout
    assert "s3cr3t-x" not in (tmp_path / "secrets" / "secrets.json").read_text(encoding="utf-8")
    bad = run_cli("secrets", "set", "Bad Name", "--stdin", env=env, stdin="x\n")
    assert bad.returncode == 2


def test_unreachable_database_exits_with_code_4(tmp_path: Path):
    env = cli_env(
        tmp_path,
        "postgresql://nobody:nothing@127.0.0.1:1/omniosint_test",
        OMNIOSINT_DATABASE__CONNECT_TIMEOUT_SECONDS="1",
    )
    result = run_cli("db", "check", "--json", env=env)
    assert result.returncode == 4
    body = json.loads(result.stdout)
    assert body["ok"] is False and "connection refused" in body["detail"]
    assert "nothing" not in result.stdout


def test_database_and_user_commands(tmp_path: Path, clean_database: str):
    env = cli_env(tmp_path, clean_database)
    check = run_cli("db", "check", "--json", env=env)
    assert check.returncode == 0, check.stdout + check.stderr
    assert json.loads(check.stdout)["schema_revision"] is not None

    token = run_cli("admin", "setup-token", "--json", env=env)
    body = json.loads(token.stdout)
    assert body["setup_required"] is True and "#token=" in body["open_url"]

    created = run_cli(
        "admin", "create-user", "root-admin", "--password-stdin", env=env, stdin=USER_PASSWORD
    )
    assert created.returncode == 0, created.stdout + created.stderr
    weak = run_cli("admin", "create-user", "weakling", "--password-stdin", env=env, stdin="short")
    assert weak.returncode == 1 and "at least 12" in weak.stderr

    users = json.loads(run_cli("admin", "list-users", "--json", env=env).stdout)["users"]
    assert [(user["username"], user["roles"]) for user in users] == [
        ("root-admin", ["administrator"])
    ]
    assert (
        json.loads(run_cli("admin", "setup-token", "--json", env=env).stdout)["setup_required"]
        is False
    )

    reset = run_cli(
        "admin",
        "reset-password",
        "root-admin",
        "--password-stdin",
        env=env,
        stdin="a different passphrase",
    )
    assert reset.returncode == 0
    missing = run_cli(
        "admin", "reset-password", "ghost", "--password-stdin", env=env, stdin=USER_PASSWORD
    )
    assert missing.returncode == 1


def test_doctor_reports_a_healthy_installation(tmp_path: Path, clean_database: str):
    result = run_cli("doctor", "--json", env=cli_env(tmp_path, clean_database))
    body = json.loads(result.stdout)
    checks = {item["name"]: item["status"] for item in body["checks"]}
    assert checks["Database"] == "ok"
    assert checks["Configuration"] == "ok"
    assert checks["Network exposure"] == "ok"
    assert result.returncode == (1 if body["summary"]["fail"] else 0)
