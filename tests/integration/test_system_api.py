from __future__ import annotations

import httpx
import pytest

from omniosint.api.app import create_app
from omniosint.core.errors import PLANNED_MESSAGE
from omniosint.core.paths import AppPaths
from tests.helpers import USER_PASSWORD, ApiUser, create_user, login_bearer, make_settings

pytestmark = pytest.mark.integration


async def test_liveness_and_readiness(client: httpx.AsyncClient):
    live = await client.get("/api/v1/system/health/live")
    assert live.status_code == 200 and live.json() == {"status": "ok"}
    ready = await client.get("/api/v1/system/health/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] in ("ok", "degraded")
    components = {item["name"]: item for item in body["components"]}
    assert components["database"]["status"] == "ok"
    assert components["storage"]["status"] == "ok"
    assert "detail" not in components["database"], "readiness exposes no details"


async def test_readiness_fails_without_a_database(app_paths: AppPaths):
    settings = make_settings(
        app_paths,
        "postgresql://nobody:nothing@127.0.0.1:1/omniosint_test",
        database={"connect_timeout_seconds": 1},
    )
    app = create_app(settings, paths=app_paths)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as http:
            ready = await http.get("/api/v1/system/health/ready")
            assert ready.status_code == 503
            assert ready.json()["status"] == "unavailable"
            assert (await http.get("/api/v1/system/health/live")).status_code == 200
            info = (await http.get("/api/v1/system/info")).json()
            assert info["setup_required"] is None
            login = await http.post("/api/v1/auth/login", json={"username": "a", "password": "b"})
            assert login.status_code == 503
            assert login.json()["error"]["code"] == "database_unavailable"


async def test_info_is_public(client: httpx.AsyncClient):
    body = (await client.get("/api/v1/system/info")).json()
    assert body["service"] == "omniosint"
    assert body["api_version"] == "v1"
    assert body["setup_required"] is True


async def test_feature_registry(client: httpx.AsyncClient, admin: ApiUser):
    assert (await client.get("/api/v1/system/features")).status_code == 401
    body = (await client.get("/api/v1/system/features", headers=admin.headers)).json()
    assert body["current_phase"] == 2
    assert len(body["features"]) == 20
    assert body["counts"] == {"available": 1, "partial": 3, "planned": 16}
    search = next(f for f in body["features"] if f["key"] == "universal_search")
    assert search["status"] == "partial" and search["phase"] == 2 and search["limitations"]


async def test_dashboard_numbers_are_records_or_explicitly_unavailable(
    client: httpx.AsyncClient, admin: ApiUser
):
    body = (await client.get("/api/v1/dashboard", headers=admin.headers)).json()
    metrics = {metric["key"]: metric for metric in body["metrics"]}
    assert metrics["users_active"]["value"] == 1
    assert metrics["my_active_sessions"]["value"] == 1
    assert metrics["sign_ins_24h"]["value"] == 1
    assert metrics["failed_sign_ins_24h"]["value"] == 0
    for key in ("investigations_total", "alerts_recent", "monitored_assets", "provider_quota"):
        metric = metrics[key]
        assert metric["available"] is False
        assert metric["value"] is None, "an unavailable metric must never be reported as 0"
        assert metric["planned_phase"] > 1
    assert body["providers"]["available"] == 0
    assert body["activity_scope"] == "all"
    assert any(item["action"] == "auth.setup.completed" for item in body["recent_activity"])
    assert all(component["detail"] for component in body["health"]["components"])


async def test_dashboard_limits_what_basic_users_see(client: httpx.AsyncClient, admin: ApiUser):
    await create_user(client, admin, username="basic", roles=["viewer"])
    basic = await login_bearer(client, "basic", USER_PASSWORD)
    body = (await client.get("/api/v1/dashboard", headers=basic.headers)).json()
    assert body["activity_scope"] == "own"
    assert {item["actor_label"] for item in body["recent_activity"]} == {"basic"}
    assert all(component["detail"] is None for component in body["health"]["components"])
    keys = {metric["key"] for metric in body["metrics"]}
    assert "users_active" not in keys and "sign_ins_24h" not in keys


async def test_system_status_details(client: httpx.AsyncClient, admin: ApiUser):
    body = (await client.get("/api/v1/system/status", headers=admin.headers)).json()
    assert body["server"]["local_only"] is True
    assert body["environment"] == "test"
    database = next(item for item in body["components"] if item["name"] == "database")
    assert database["data"]["schema_revision"] == database["data"]["schema_head"]


async def test_provider_catalogue_is_read_only_and_honest(
    client: httpx.AsyncClient, admin: ApiUser
):
    listing = (await client.get("/api/v1/providers", headers=admin.headers)).json()
    assert listing["counts"]["available"] == 0
    assert listing["counts"]["total"] == len(listing["items"])
    assert all(item["status"] != "available" for item in listing["items"])
    threat = (
        await client.get("/api/v1/providers", headers=admin.headers, params={"category": "threat"})
    ).json()
    assert threat["items"] and {item["category"] for item in threat["items"]} == {"threat"}
    excluded = (
        await client.get("/api/v1/providers", headers=admin.headers, params={"status": "excluded"})
    ).json()
    assert all(item["notes"] for item in excluded["items"])
    shodan = (await client.get("/api/v1/providers/shodan", headers=admin.headers)).json()
    assert shodan["status_message"] == PLANNED_MESSAGE
    missing = await client.get("/api/v1/providers/no-such-thing", headers=admin.headers)
    assert missing.status_code == 404
    # There is no endpoint to configure or test a provider yet.
    assert (
        await client.post("/api/v1/providers/shodan/test", headers=admin.headers)
    ).status_code in (404, 405)


async def test_unknown_api_routes_are_json_404(client: httpx.AsyncClient):
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


async def test_openapi_document(client: httpx.AsyncClient):
    spec = (await client.get("/api/v1/openapi.json")).json()
    assert all(path.startswith("/api/v1/") for path in spec["paths"])
    users = spec["paths"]["/api/v1/admin/users"]
    assert users["get"]["x-permission"] == "users:read"
    assert users["post"]["x-permission"] == "users:manage"
    assert spec["paths"]["/api/v1/auth/login"]["post"]["x-access"] == "public"
    assert (await client.get("/api/docs")).status_code == 404, "docs are off outside development"
