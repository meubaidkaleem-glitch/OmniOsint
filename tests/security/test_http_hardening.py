"""Browser-facing defences of the local API."""

from __future__ import annotations

import httpx
import pytest

from omniosint.core.paths import AppPaths
from tests.helpers import ADMIN_PASSWORD, ApiUser, complete_setup, login_cookie

pytestmark = pytest.mark.security


async def test_security_headers_on_api_responses(client: httpx.AsyncClient):
    response = await client.get("/api/v1/system/info")
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store"
    csp = headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp and "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp
    assert "server" not in {key.lower() for key in headers}


@pytest.mark.parametrize(
    "host", ["evil.example", "attacker.test:8765", "127.0.0.1.nip.io", "192.168.1.5:8765"]
)
async def test_unknown_host_headers_are_rejected(client: httpx.AsyncClient, host: str):
    response = await client.get("/api/v1/system/info", headers={"Host": host})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "host_not_allowed"


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "[::1]:8765"])
async def test_loopback_host_headers_are_accepted(client: httpx.AsyncClient, host: str):
    response = await client.get("/api/v1/system/info", headers={"Host": host})
    assert response.status_code == 200


async def test_cross_origin_writes_are_refused(client: httpx.AsyncClient):
    body = {"username": "a", "password": "b"}
    foreign = await client.post(
        "/api/v1/auth/login", json=body, headers={"Origin": "https://evil.example"}
    )
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "origin_not_allowed"
    null_origin = await client.post("/api/v1/auth/login", json=body, headers={"Origin": "null"})
    assert null_origin.status_code == 403
    cross_site = await client.post(
        "/api/v1/auth/login", json=body, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert cross_site.status_code == 403
    same_origin = await client.post(
        "/api/v1/auth/login", json=body, headers={"Origin": "http://127.0.0.1:8765"}
    )
    assert same_origin.status_code == 401, "same-origin requests reach the endpoint"


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("application/x-www-form-urlencoded", "username=a&password=b"),
        ("multipart/form-data; boundary=x", "--x\r\n\r\n--x--"),
        ("text/plain", '{"username":"a","password":"b"}'),
    ],
)
async def test_non_json_bodies_are_refused(
    client: httpx.AsyncClient, content_type: str, content: str
):
    # What an HTML form on another site can send without a CORS preflight.
    response = await client.post(
        "/api/v1/auth/login", content=content, headers={"Content-Type": content_type}
    )
    assert response.status_code == 415


async def test_no_cors_grant_by_default(client: httpx.AsyncClient):
    response = await client.get("/api/v1/system/info", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
    preflight = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in preflight.headers


async def test_oversized_bodies_are_refused(client: httpx.AsyncClient):
    big = "x" * 1_100_000
    declared = await client.post(
        "/api/v1/auth/login", content=big, headers={"Content-Type": "application/json"}
    )
    assert declared.status_code == 413

    async def chunks():  # type: ignore[no-untyped-def]
        for _ in range(20):
            yield b"x" * 100_000

    streamed = await client.post(
        "/api/v1/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert streamed.status_code == 413


async def test_request_ids_are_sanitised(client: httpx.AsyncClient):
    good = await client.get("/api/v1/system/info", headers={"X-Request-ID": "client-id-12345"})
    assert good.headers["x-request-id"] == "client-id-12345"
    hostile = await client.get(
        "/api/v1/system/info", headers={"X-Request-ID": "bad id\r\nX-Injected: 1"}
    )
    assert hostile.headers["x-request-id"] != "bad id\r\nX-Injected: 1"
    assert "x-injected" not in hostile.headers


async def test_session_cookie_cannot_be_used_without_the_csrf_header(
    client: httpx.AsyncClient, app_paths: AppPaths
):
    # Simulates a cross-site form or fetch that rides on the browser's cookie.
    await complete_setup(client, app_paths)
    await login_cookie(client)
    response = await client.post(
        "/api/v1/admin/users",
        json={"username": "csrfvictim", "password": ADMIN_PASSWORD, "roles": ["administrator"]},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_logout_removes_a_stale_cookie(client: httpx.AsyncClient, app_paths: AppPaths):
    await complete_setup(client, app_paths)
    csrf = await login_cookie(client)
    await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    client.cookies.set("omniosint_session", "stale-token-value")
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "omniosint_session=" in response.headers.get("set-cookie", "")


async def test_admin_api_is_not_reachable_with_another_users_token(
    client: httpx.AsyncClient, admin: ApiUser
):
    forged = {"Authorization": f"Bearer {admin.token[:-4]}AAAA"}
    assert (await client.get("/api/v1/admin/users", headers=forged)).status_code == 401
