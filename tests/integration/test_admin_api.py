from __future__ import annotations

import httpx
import pytest

from tests.helpers import (
    ADMIN_PASSWORD,
    USER_PASSWORD,
    ApiUser,
    create_user,
    fetch_all,
    login_bearer,
)

pytestmark = pytest.mark.integration


async def user_as(client: httpx.AsyncClient, admin: ApiUser, username: str, *roles: str) -> ApiUser:
    await create_user(client, admin, username=username, roles=list(roles))
    return await login_bearer(client, username, USER_PASSWORD)


async def my_id(client: httpx.AsyncClient, caller: ApiUser) -> str:
    return str((await client.get("/api/v1/auth/me", headers=caller.headers)).json()["user"]["id"])


ADMIN_ONLY = [
    ("GET", "/api/v1/admin/users"),
    ("POST", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/roles"),
    ("GET", "/api/v1/admin/audit-events"),
    ("GET", "/api/v1/system/status"),
]


async def test_permissions_are_enforced_and_denials_audited(
    client: httpx.AsyncClient, admin: ApiUser, clean_database: str
):
    analyst = await user_as(client, admin, "ana", "analyst")
    for method, path in ADMIN_ONLY:
        response = await client.request(
            method,
            path,
            headers=analyst.headers,
            json={"username": "x1x", "password": USER_PASSWORD, "roles": ["viewer"]}
            if method == "POST"
            else None,
        )
        assert response.status_code == 403, (method, path)
        assert response.json()["error"]["code"] == "permission_denied"

    denials = await fetch_all(
        clean_database,
        "SELECT actor_label, details->>'permission' FROM audit_events "
        "WHERE action = 'authz.denied'",
    )
    assert len(denials) == len(ADMIN_ONLY)
    assert {row[0] for row in denials} == {"ana"}

    for path in ("/api/v1/dashboard", "/api/v1/system/features", "/api/v1/providers"):
        assert (await client.get(path, headers=analyst.headers)).status_code == 200, path


async def test_auditor_can_read_but_not_change(client: httpx.AsyncClient, admin: ApiUser):
    auditor = await user_as(client, admin, "audrey", "auditor")
    for path in (
        "/api/v1/admin/users",
        "/api/v1/admin/roles",
        "/api/v1/admin/audit-events",
        "/api/v1/system/status",
    ):
        assert (await client.get(path, headers=auditor.headers)).status_code == 200, path
    target = await create_user(client, admin, username="target")
    change = await client.patch(
        f"/api/v1/admin/users/{target['id']}", headers=auditor.headers, json={"is_active": False}
    )
    assert change.status_code == 403
    create = await client.post(
        "/api/v1/admin/users",
        headers=auditor.headers,
        json={"username": "nope1", "password": USER_PASSWORD, "roles": ["viewer"]},
    )
    assert create.status_code == 403


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"username": "x", "roles": ["viewer"]}, "username"),
        ({"username": "bad name", "roles": ["viewer"]}, "username"),
        ({"username": "valid1", "roles": ["superuser"]}, "roles"),
        ({"username": "valid2", "roles": []}, "roles"),
        ({"username": "valid3", "roles": ["viewer"], "email": "not-an-email"}, "email"),
        ({"username": "valid4", "roles": ["viewer"], "password": "short"}, "password"),
    ],
)
async def test_user_creation_is_validated(
    client: httpx.AsyncClient, admin: ApiUser, payload: dict[str, object], field: str
):
    body = {"password": USER_PASSWORD, **payload}
    response = await client.post("/api/v1/admin/users", headers=admin.headers, json=body)
    assert response.status_code == 422, response.text
    assert field in {detail.get("field") for detail in response.json()["error"]["details"]}


async def test_usernames_and_emails_are_unique_ignoring_case(
    client: httpx.AsyncClient, admin: ApiUser
):
    created = await create_user(client, admin, username="Dave", email="Dave@Example.org")
    assert created["username"] == "dave"
    assert created["email"] == "dave@example.org"
    duplicate_name = await client.post(
        "/api/v1/admin/users",
        headers=admin.headers,
        json={"username": "DAVE", "password": USER_PASSWORD, "roles": ["viewer"]},
    )
    assert duplicate_name.status_code == 409
    duplicate_email = await client.post(
        "/api/v1/admin/users",
        headers=admin.headers,
        json={
            "username": "david",
            "password": USER_PASSWORD,
            "roles": ["viewer"],
            "email": "dave@EXAMPLE.org",
        },
    )
    assert duplicate_email.status_code == 409
    assert duplicate_email.json()["error"]["details"][0]["field"] == "email"


async def test_updates_change_only_what_is_sent(
    client: httpx.AsyncClient, admin: ApiUser, clean_database: str
):
    user = await create_user(client, admin, username="erin", email="erin@example.org")
    response = await client.patch(
        f"/api/v1/admin/users/{user['id']}",
        headers=admin.headers,
        json={"display_name": "  Erin   Example ", "roles": ["auditor", "analyst"]},
    )
    body = response.json()
    assert body["display_name"] == "Erin Example"
    assert body["roles"] == ["analyst", "auditor"]
    assert body["email"] == "erin@example.org", "email was not sent, so it must not change"

    removed = await client.patch(
        f"/api/v1/admin/users/{user['id']}", headers=admin.headers, json={"email": None}
    )
    assert removed.json()["email"] is None

    events_before = await fetch_all(
        clean_database, "SELECT count(*) FROM audit_events WHERE action = 'user.updated'"
    )
    unchanged = await client.patch(
        f"/api/v1/admin/users/{user['id']}",
        headers=admin.headers,
        json={"display_name": "Erin Example"},
    )
    assert unchanged.status_code == 200
    events_after = await fetch_all(
        clean_database, "SELECT count(*) FROM audit_events WHERE action = 'user.updated'"
    )
    assert events_after == events_before, "a no-op update is not audited as a change"


async def test_the_last_administrator_is_protected(client: httpx.AsyncClient, admin: ApiUser):
    admin_id = await my_id(client, admin)
    deactivate = await client.patch(
        f"/api/v1/admin/users/{admin_id}", headers=admin.headers, json={"is_active": False}
    )
    assert deactivate.status_code == 409
    assert deactivate.json()["error"]["code"] == "last_administrator"
    demote = await client.patch(
        f"/api/v1/admin/users/{admin_id}", headers=admin.headers, json={"roles": ["analyst"]}
    )
    assert demote.status_code == 409
    delete_self = await client.delete(f"/api/v1/admin/users/{admin_id}", headers=admin.headers)
    assert delete_self.status_code == 409

    await create_user(client, admin, username="second", roles=["administrator"])
    demote_now = await client.patch(
        f"/api/v1/admin/users/{admin_id}", headers=admin.headers, json={"roles": ["analyst"]}
    )
    assert demote_now.status_code == 200
    assert demote_now.json()["roles"] == ["analyst"]
    # The demoted caller's next request no longer carries administrator rights.
    assert (await client.get("/api/v1/admin/users", headers=admin.headers)).status_code == 403


async def test_deleted_users_cannot_sign_in_and_keep_their_name(
    client: httpx.AsyncClient, admin: ApiUser
):
    user = await create_user(client, admin, username="frank")
    frank = await login_bearer(client, "frank", USER_PASSWORD)
    assert (
        await client.delete(f"/api/v1/admin/users/{user['id']}", headers=admin.headers)
    ).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=frank.headers)).status_code == 401
    login = await client.post(
        "/api/v1/auth/login", json={"username": "frank", "password": USER_PASSWORD}
    )
    assert login.status_code == 401
    assert (
        await client.get(f"/api/v1/admin/users/{user['id']}", headers=admin.headers)
    ).status_code == 404
    reuse = await client.post(
        "/api/v1/admin/users",
        headers=admin.headers,
        json={"username": "frank", "password": USER_PASSWORD, "roles": ["viewer"]},
    )
    assert reuse.status_code == 409


async def test_password_reset_ends_sessions_and_clears_lockout(
    client: httpx.AsyncClient, admin: ApiUser
):
    user = await create_user(client, admin, username="gina")
    gina = await login_bearer(client, "gina", USER_PASSWORD)
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"username": "gina", "password": "nope nope"})
    reset = await client.post(
        f"/api/v1/admin/users/{user['id']}/reset-password",
        headers=admin.headers,
        json={"new_password": "reset by the admin", "must_change_password": True},
    )
    assert reset.status_code == 200
    assert reset.json()["must_change_password"] is True
    assert reset.json()["locked_until"] is None
    assert (await client.get("/api/v1/auth/me", headers=gina.headers)).status_code == 401
    fresh = await login_bearer(client, "gina", "reset by the admin")
    blocked = await client.get("/api/v1/dashboard", headers=fresh.headers)
    assert blocked.json()["error"]["code"] == "password_change_required"


async def test_user_listing_pages_and_searches_literally(client: httpx.AsyncClient, admin: ApiUser):
    for index in range(5):
        await create_user(client, admin, username=f"page{index}")
    await create_user(client, admin, username="under_score")

    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 2, "search": "page"}
        if cursor:
            params["cursor"] = cursor
        page = (
            await client.get("/api/v1/admin/users", headers=admin.headers, params=params)
        ).json()
        assert page["total"] == 5
        seen += [item["username"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"page{index}" for index in range(5)]

    percent = await client.get("/api/v1/admin/users", headers=admin.headers, params={"search": "%"})
    assert percent.json()["total"] == 0, "% must match literally, not as a wildcard"
    underscore = await client.get(
        "/api/v1/admin/users", headers=admin.headers, params={"search": "_"}
    )
    assert [item["username"] for item in underscore.json()["items"]] == ["under_score"]

    bad_cursor = await client.get(
        "/api/v1/admin/users", headers=admin.headers, params={"cursor": "!!!"}
    )
    assert bad_cursor.status_code == 422


async def test_audit_trail_pages_and_filters(client: httpx.AsyncClient, admin: ApiUser):
    for _ in range(3):
        await login_bearer(client, "admin", ADMIN_PASSWORD)
    await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong pass!"})

    first = (
        await client.get("/api/v1/admin/audit-events", headers=admin.headers, params={"limit": 2})
    ).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = (
        await client.get(
            "/api/v1/admin/audit-events",
            headers=admin.headers,
            params={"limit": 2, "cursor": first["next_cursor"]},
        )
    ).json()
    assert {item["id"] for item in first["items"]}.isdisjoint(
        {item["id"] for item in second["items"]}
    )
    times = [item["occurred_at"] for item in first["items"] + second["items"]]
    assert times == sorted(times, reverse=True)

    successes = (
        await client.get(
            "/api/v1/admin/audit-events",
            headers=admin.headers,
            params={"action": "auth.login.success"},
        )
    ).json()["items"]
    assert len(successes) == 4  # the fixture's sign-in plus three more
    failures = (
        await client.get(
            "/api/v1/admin/audit-events", headers=admin.headers, params={"outcome": "failure"}
        )
    ).json()["items"]
    assert [item["action"] for item in failures] == ["auth.login.failure"]
    future = (
        await client.get(
            "/api/v1/admin/audit-events",
            headers=admin.headers,
            params={"since": "2999-01-01T00:00:00Z"},
        )
    ).json()["items"]
    assert future == []


async def test_roles_listing(client: httpx.AsyncClient, admin: ApiUser):
    roles = {
        role["name"]: role
        for role in (await client.get("/api/v1/admin/roles", headers=admin.headers)).json()["items"]
    }
    assert set(roles) == {"administrator", "analyst", "auditor", "viewer"}
    assert all(role["is_system"] for role in roles.values())
    assert len(roles["administrator"]["permissions"]) == 6
    assert roles["administrator"]["member_count"] == 1
    assert roles["analyst"]["permissions"] == []
