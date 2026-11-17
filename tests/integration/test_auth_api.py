from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from omniosint.core.paths import AppPaths
from tests.helpers import (
    ADMIN_PASSWORD,
    USER_PASSWORD,
    ApiUser,
    complete_setup,
    create_user,
    execute_sql,
    fetch_all,
    login_bearer,
    login_cookie,
)

pytestmark = pytest.mark.integration


async def audit_actions(database_url: str, action: str) -> list[tuple[str, str]]:
    rows = await fetch_all(
        database_url,
        "SELECT actor_label, outcome FROM audit_events WHERE action = :action ORDER BY occurred_at",
        action=action,
    )
    return [(row[0], row[1]) for row in rows]


# --------------------------------------------------------------------------- setup
async def test_setup_status_reports_pending_setup(client: httpx.AsyncClient, app_paths: AppPaths):
    body = (await client.get("/api/v1/auth/setup-status")).json()
    assert body["setup_required"] is True
    token_file = Path(body["token_file"])
    assert token_file == app_paths.setup_token_file
    token = token_file.read_text(encoding="utf-8").strip()
    assert len(token) >= 24
    again = (await client.get("/api/v1/auth/setup-status")).json()
    assert Path(again["token_file"]).read_text(encoding="utf-8").strip() == token


async def test_setup_rejects_a_wrong_token_and_audits_it(
    client: httpx.AsyncClient, clean_database: str
):
    response = await client.post(
        "/api/v1/auth/setup",
        json={"setup_token": "wrong-token-value", "username": "admin", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "setup_token_invalid"
    assert await audit_actions(clean_database, "auth.setup.failure") == [("anonymous", "denied")]
    assert (await client.get("/api/v1/system/info")).json()["setup_required"] is True


async def test_setup_validates_the_password(client: httpx.AsyncClient, app_paths: AppPaths):
    token_file = Path((await client.get("/api/v1/auth/setup-status")).json()["token_file"])
    response = await client.post(
        "/api/v1/auth/setup",
        json={
            "setup_token": token_file.read_text(encoding="utf-8").strip(),
            "username": "admin",
            "password": "weak",
        },
    )
    assert response.status_code == 422
    assert {d["field"] for d in response.json()["error"]["details"]} == {"password"}


async def test_setup_creates_one_administrator_exactly_once(
    client: httpx.AsyncClient, app_paths: AppPaths, clean_database: str
):
    body = await complete_setup(client, app_paths, username="Owner")
    assert body["user"]["username"] == "owner"
    assert body["user"]["roles"] == ["administrator"]
    assert not app_paths.setup_token_file.exists(), "the token file is removed after use"

    status = (await client.get("/api/v1/auth/setup-status")).json()
    assert status == {"setup_required": False, "token_file": None}
    again = await client.post(
        "/api/v1/auth/setup",
        json={"setup_token": "anything-at-all", "username": "other", "password": ADMIN_PASSWORD},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "setup_already_completed"
    assert await audit_actions(clean_database, "auth.setup.completed") == [("owner", "success")]


# --------------------------------------------------------------------------- login
async def test_cookie_login_sets_a_hardened_cookie(client: httpx.AsyncClient, app_paths: AppPaths):
    await complete_setup(client, app_paths)
    response = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    body = response.json()
    assert body["csrf_token"]
    assert body["access_token"] is None
    assert body["user"]["username"] == "admin"
    assert "password_hash" not in response.text

    me = (await client.get("/api/v1/auth/me")).json()
    assert me["user"]["username"] == "admin"
    assert me["csrf_token"] == body["csrf_token"]
    assert "users:manage" in me["permissions"]


async def test_bearer_login_returns_a_token_and_no_cookie(
    client: httpx.AsyncClient, app_paths: AppPaths
):
    await complete_setup(client, app_paths)
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": ADMIN_PASSWORD,
            "session_type": "bearer",
            "client": "cli",
        },
    )
    body = response.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert body["csrf_token"] is None
    assert "set-cookie" not in response.headers
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.json()["session"]["auth_method"] == "bearer"


async def test_failed_logins_are_indistinguishable(client: httpx.AsyncClient, app_paths: AppPaths):
    await complete_setup(client, app_paths)
    unknown = await client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": ADMIN_PASSWORD}
    )
    wrong = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "not the password"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


async def test_repeated_failures_lock_the_account(
    client: httpx.AsyncClient, admin: ApiUser, clean_database: str
):
    user = await create_user(client, admin, username="locky")
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/login", json={"username": "locky", "password": "wrong password!"}
        )
        assert response.status_code == 401
    locked = await client.post(
        "/api/v1/auth/login", json={"username": "locky", "password": USER_PASSWORD}
    )
    assert locked.status_code == 401, "the correct password must not work while locked"
    detail = await client.get(f"/api/v1/admin/users/{user['id']}", headers=admin.headers)
    assert detail.json()["locked_until"] is not None
    assert await audit_actions(clean_database, "user.locked") == [("locky", "failure")]

    unlock = await client.post(f"/api/v1/admin/users/{user['id']}/unlock", headers=admin.headers)
    assert unlock.status_code == 200 and unlock.json()["locked_until"] is None
    await login_bearer(client, "locky", USER_PASSWORD)


async def test_login_attempts_are_throttled(client: httpx.AsyncClient, clean_database: str):
    for _ in range(10):
        response = await client.post(
            "/api/v1/auth/login", json={"username": "ghost", "password": "irrelevant!"}
        )
        assert response.status_code == 401
    throttled = await client.post(
        "/api/v1/auth/login", json={"username": "ghost", "password": "irrelevant!"}
    )
    assert throttled.status_code == 429
    assert int(throttled.headers["retry-after"]) >= 1
    assert throttled.json()["error"]["code"] == "rate_limited"
    assert await audit_actions(clean_database, "auth.login.throttled") == [("anonymous", "denied")]


# --------------------------------------------------------------------------- sessions
async def test_logout_ends_the_session(client: httpx.AsyncClient, app_paths: AppPaths):
    await complete_setup(client, app_paths)
    csrf = await login_cookie(client)
    response = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 401


async def test_csrf_token_is_required_for_cookie_sessions(
    client: httpx.AsyncClient, app_paths: AppPaths
):
    await complete_setup(client, app_paths)
    csrf = await login_cookie(client)
    missing = await client.post("/api/v1/auth/logout")
    assert missing.status_code == 403 and missing.json()["error"]["code"] == "csrf_failed"
    wrong = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf[:-2] + "xx"})
    assert wrong.status_code == 403
    assert (await client.get("/api/v1/auth/me")).status_code == 200, "safe methods need no token"
    ok = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 204


async def test_bearer_sessions_do_not_need_csrf(client: httpx.AsyncClient, admin: ApiUser):
    response = await client.post(
        "/api/v1/admin/users",
        headers=admin.headers,
        json={"username": "nocsrf", "password": USER_PASSWORD, "roles": ["viewer"]},
    )
    assert response.status_code == 201


async def test_change_password_ends_other_sessions(client: httpx.AsyncClient, admin: ApiUser):
    other = await login_bearer(client, "admin", ADMIN_PASSWORD)
    response = await client.post(
        "/api/v1/auth/change-password",
        headers=admin.headers,
        json={"current_password": ADMIN_PASSWORD, "new_password": "a brand new passphrase"},
    )
    assert response.status_code == 200
    assert response.json()["other_sessions_ended"] == 1
    assert (await client.get("/api/v1/auth/me", headers=other.headers)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=admin.headers)).status_code == 200
    old = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert old.status_code == 401
    await login_bearer(client, "admin", "a brand new passphrase")


async def test_change_password_checks_current_and_new(client: httpx.AsyncClient, admin: ApiUser):
    wrong = await client.post(
        "/api/v1/auth/change-password",
        headers=admin.headers,
        json={"current_password": "not it at all", "new_password": "a brand new passphrase"},
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["details"][0]["field"] == "current_password"
    same = await client.post(
        "/api/v1/auth/change-password",
        headers=admin.headers,
        json={"current_password": ADMIN_PASSWORD, "new_password": ADMIN_PASSWORD},
    )
    assert same.status_code == 422
    weak = await client.post(
        "/api/v1/auth/change-password",
        headers=admin.headers,
        json={"current_password": ADMIN_PASSWORD, "new_password": "short"},
    )
    assert weak.status_code == 422


async def test_required_password_change_restricts_access(client: httpx.AsyncClient, admin: ApiUser):
    await create_user(client, admin, username="newbie", must_change_password=True)
    newbie = await login_bearer(client, "newbie", USER_PASSWORD)
    blocked = await client.get("/api/v1/dashboard", headers=newbie.headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "password_change_required"
    me = await client.get("/api/v1/auth/me", headers=newbie.headers)
    assert me.status_code == 200 and me.json()["user"]["must_change_password"] is True
    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=newbie.headers,
        json={"current_password": USER_PASSWORD, "new_password": "my own new passphrase"},
    )
    assert changed.status_code == 200
    assert (await client.get("/api/v1/dashboard", headers=newbie.headers)).status_code == 200


async def test_idle_and_absolute_expiry(
    client: httpx.AsyncClient, admin: ApiUser, clean_database: str
):
    await execute_sql(
        clean_database, "UPDATE user_sessions SET last_seen_at = now() - interval '3 hours'"
    )
    idle = await client.get("/api/v1/auth/me", headers=admin.headers)
    assert idle.status_code == 401 and idle.json()["error"]["code"] == "session_expired"
    rows = await fetch_all(clean_database, "SELECT revoke_reason FROM user_sessions")
    assert [row[0] for row in rows] == ["idle_timeout"]

    fresh = await login_bearer(client, "admin", ADMIN_PASSWORD)
    await execute_sql(
        clean_database,
        "UPDATE user_sessions SET expires_at = now() - interval '1 minute' "
        "WHERE revoked_at IS NULL",
    )
    expired = await client.get("/api/v1/auth/me", headers=fresh.headers)
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "session_expired"


async def test_list_and_revoke_own_sessions(client: httpx.AsyncClient, admin: ApiUser):
    other = await login_bearer(client, "admin", ADMIN_PASSWORD)
    listing = (await client.get("/api/v1/auth/sessions", headers=admin.headers)).json()["items"]
    assert len(listing) == 2
    assert sum(1 for item in listing if item["current"]) == 1
    other_id = (await client.get("/api/v1/auth/me", headers=other.headers)).json()["session"]["id"]
    revoked = await client.delete(f"/api/v1/auth/sessions/{other_id}", headers=admin.headers)
    assert revoked.status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=other.headers)).status_code == 401
    again = await client.delete(f"/api/v1/auth/sessions/{other_id}", headers=admin.headers)
    assert again.status_code == 404


async def test_sessions_of_other_users_cannot_be_revoked(client: httpx.AsyncClient, admin: ApiUser):
    await create_user(client, admin, username="victim")
    victim = await login_bearer(client, "victim", USER_PASSWORD)
    victim_session = (await client.get("/api/v1/auth/me", headers=victim.headers)).json()
    response = await client.delete(
        f"/api/v1/auth/sessions/{victim_session['session']['id']}", headers=admin.headers
    )
    assert response.status_code == 404
    assert (await client.get("/api/v1/auth/me", headers=victim.headers)).status_code == 200


async def test_deactivation_ends_sessions_and_blocks_sign_in(
    client: httpx.AsyncClient, admin: ApiUser
):
    user = await create_user(client, admin, username="leaver")
    leaver = await login_bearer(client, "leaver", USER_PASSWORD)
    response = await client.patch(
        f"/api/v1/admin/users/{user['id']}", headers=admin.headers, json={"is_active": False}
    )
    assert response.status_code == 200 and response.json()["is_active"] is False
    assert (await client.get("/api/v1/auth/me", headers=leaver.headers)).status_code == 401
    login = await client.post(
        "/api/v1/auth/login", json={"username": "leaver", "password": USER_PASSWORD}
    )
    assert login.status_code == 401


async def test_unauthenticated_requests_are_refused(client: httpx.AsyncClient):
    for path in ("/api/v1/auth/me", "/api/v1/dashboard", "/api/v1/admin/users"):
        response = await client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "authentication_required"
    garbage = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert garbage.status_code == 401 and garbage.json()["error"]["code"] == "session_invalid"
