"""Credentials and tokens must not leak through responses, errors or logs."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from omniosint.core.config import LoggingSettings
from omniosint.core.logging import configure_logging
from omniosint.core.paths import AppPaths
from tests.helpers import ADMIN_PASSWORD, ApiUser, create_user

pytestmark = pytest.mark.security

CANARY = "Canary-Passphrase-4711"


async def test_user_payloads_never_contain_hashes(client: httpx.AsyncClient, admin: ApiUser):
    await create_user(client, admin, username="hashless")
    for path in ("/api/v1/admin/users", "/api/v1/auth/me", "/api/v1/dashboard"):
        response = await client.get(path, headers=admin.headers)
        assert "password_hash" not in response.text, path
        assert "$argon2" not in response.text, path


async def test_validation_errors_do_not_echo_submitted_values(client: httpx.AsyncClient):
    response = await client.post(
        "/api/v1/auth/login", json={"username": CANARY, "password": ["not", "a", CANARY]}
    )
    assert response.status_code == 422
    assert CANARY not in response.text


async def test_passwords_and_tokens_stay_out_of_logs(
    client: httpx.AsyncClient, app_paths: AppPaths, tmp_path: Path
):
    logs = tmp_path / "logs"
    configure_logging(
        LoggingSettings(level="DEBUG", file_enabled=True, access_log=True),
        service="security-test",
        logs_dir=logs,
        console=False,
    )
    try:
        status = (await client.get("/api/v1/auth/setup-status")).json()
        token = Path(status["token_file"]).read_text(encoding="utf-8").strip()
        await client.post(
            "/api/v1/auth/setup",
            json={"setup_token": token, "username": "admin", "password": ADMIN_PASSWORD},
        )
        await client.post("/api/v1/auth/login", json={"username": "admin", "password": CANARY})
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": ADMIN_PASSWORD, "session_type": "bearer"},
        )
        session_token = login.json()["access_token"]
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session_token}"})
    finally:
        for handler in logging.getLogger().handlers:
            handler.flush()
    text = "".join(path.read_text(encoding="utf-8") for path in logs.glob("*.log"))
    for secret in (CANARY, ADMIN_PASSWORD, session_token, token):
        assert secret not in text


async def test_setup_token_file_is_private(client: httpx.AsyncClient, app_paths: AppPaths):
    import sys

    status = (await client.get("/api/v1/auth/setup-status")).json()
    token_file = Path(status["token_file"])
    if sys.platform != "win32":
        assert token_file.stat().st_mode & 0o077 == 0


async def test_audit_details_never_contain_credentials(
    client: httpx.AsyncClient, admin: ApiUser, clean_database: str
):
    from tests.helpers import fetch_all

    await client.post("/api/v1/auth/login", json={"username": "admin", "password": CANARY})
    await create_user(client, admin, username="audited", password=CANARY + "-x")
    rows = await fetch_all(clean_database, "SELECT details::text FROM audit_events")
    assert rows
    assert all(CANARY not in row[0] for row in rows)
