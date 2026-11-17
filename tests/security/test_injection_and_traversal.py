"""Hostile input must be treated as data."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from omniosint.api.app import create_app
from omniosint.core.config import Settings
from omniosint.core.paths import AppPaths
from tests.helpers import ApiUser, fetch_all, make_settings

pytestmark = pytest.mark.security

SQL_PAYLOADS = [
    "' OR '1'='1",
    "admin'--",
    "'; DROP TABLE users; --",
    'x" OR 1=1 --',
    "%' UNION SELECT password_hash FROM users --",
]


@pytest.mark.parametrize("payload", SQL_PAYLOADS)
async def test_login_is_not_injectable(client: httpx.AsyncClient, admin: ApiUser, payload: str):
    response = await client.post(
        "/api/v1/auth/login", json={"username": payload, "password": payload}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("payload", SQL_PAYLOADS)
async def test_user_search_is_not_injectable(
    client: httpx.AsyncClient, admin: ApiUser, payload: str, clean_database: str
):
    response = await client.get(
        "/api/v1/admin/users", headers=admin.headers, params={"search": payload}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert "password_hash" not in response.text
    tables = await fetch_all(clean_database, "SELECT count(*) FROM users")
    assert tables[0][0] == 1, "the users table is intact"


async def test_audit_filters_are_parameterised(client: httpx.AsyncClient, admin: ApiUser):
    response = await client.get(
        "/api/v1/admin/audit-events",
        headers=admin.headers,
        params={"action": "x' OR '1'='1", "category": "auth'--"},
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_invalid_identifiers_are_validation_errors(client: httpx.AsyncClient, admin: ApiUser):
    response = await client.get("/api/v1/admin/users/not-a-uuid", headers=admin.headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


# --------------------------------------------------------------------------- static files
@pytest.fixture
async def spa_client(app_paths: AppPaths, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>OmniOSINT</title>", encoding="utf-8")
    (dist / "assets" / "app-1234.js").write_text("console.log('ok')", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP-SECRET-CANARY", encoding="utf-8")
    settings: Settings = make_settings(
        app_paths, server={"serve_frontend": True, "frontend_dist": str(dist)}
    )
    app = create_app(settings, paths=app_paths, manage_lifespan=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as http:
        yield http


async def test_spa_serves_pages_and_assets(spa_client: httpx.AsyncClient):
    index = await spa_client.get("/")
    assert index.status_code == 200 and "OmniOSINT" in index.text
    assert index.headers["cache-control"] == "no-cache"
    route = await spa_client.get("/admin/users")
    assert route.status_code == 200 and "OmniOSINT" in route.text, "client-side routes fall back"
    asset = await spa_client.get("/assets/app-1234.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    assert "content-security-policy" in asset.headers
    missing_asset = await spa_client.get("/assets/missing.js")
    assert missing_asset.status_code == 404, "missing files are not answered with the page"


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/%2e%2e/secret.txt",
        "/assets/../../secret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/..%2fsecret.txt",
        "/assets/..%5c..%5csecret.txt",
    ],
)
async def test_path_traversal_is_contained(spa_client: httpx.AsyncClient, path: str):
    response = await spa_client.get(path)
    assert "TOP-SECRET-CANARY" not in response.text


async def test_unknown_api_paths_never_fall_back_to_the_page(spa_client: httpx.AsyncClient):
    for path in ("/api/v1/unknown", "/api/anything", "/api"):
        response = await spa_client.get(path)
        assert response.status_code == 404, path
        assert response.headers["content-type"].startswith("application/json"), path
