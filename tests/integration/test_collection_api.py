"""Universal search, collection, evidence and scopes over HTTP."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from omniosint.collection.executor import Collector
from omniosint.core.config import Settings
from omniosint.core.paths import AppPaths
from omniosint.core.timeutil import isoformat, utcnow
from tests.helpers import (
    USER_PASSWORD,
    ApiUser,
    create_user,
    fetch_all,
    login_bearer,
    make_settings,
)

pytestmark = pytest.mark.integration

PLANNED = "Planned — integration not yet implemented."


@pytest.fixture
def db_settings(app_paths: AppPaths, clean_database: str) -> Settings:
    return make_settings(
        app_paths,
        clean_database,
        collection={"enable_simulated_provider": True, "retry_base_seconds": 0.1},
    )


async def user_as(client: httpx.AsyncClient, admin: ApiUser, username: str, *roles: str) -> ApiUser:
    await create_user(client, admin, username=username, roles=list(roles))
    return await login_bearer(client, username, USER_PASSWORD)


async def run_jobs(app: FastAPI) -> int:
    context = app.state.ctx
    intel = context.intel
    collector = Collector(context.db, context.settings, intel.manager, intel.store)
    return await collector.drain()


async def post(
    client: httpx.AsyncClient, user: ApiUser, path: str, body: Any = None
) -> httpx.Response:
    return await client.post(f"/api/v1{path}", headers=user.headers, json=body or {})


async def get(client: httpx.AsyncClient, user: ApiUser, path: str, **params: Any) -> httpx.Response:
    return await client.get(f"/api/v1{path}", headers=user.headers, params=params)


# --------------------------------------------------------------------------- search
async def test_classify_and_history(client: httpx.AsyncClient, admin: ApiUser) -> None:
    response = await post(client, admin, "/search/classify", {"input": " Example.ORG "})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "recognized"
    assert (
        body["candidates"][0]["type"] == "domain"
        and body["candidates"][0]["value"] == "example.org"
    )

    ambiguous = (await post(client, admin, "/search/classify", {"input": "Acme Widgets"})).json()
    assert ambiguous["status"] == "ambiguous" and len(ambiguous["candidates"]) == 2

    history = (await get(client, admin, "/search/history")).json()["items"]
    assert [item["query"] for item in history] == ["Acme Widgets", "Example.ORG"]
    private = await post(
        client, admin, "/search/classify", {"input": "secret.example", "remember": False}
    )
    assert private.status_code == 200
    assert len((await get(client, admin, "/search/history")).json()["items"]) == 2
    cleared = await client.delete("/api/v1/search/history", headers=admin.headers)
    assert cleared.status_code == 204
    assert (await get(client, admin, "/search/history")).json()["items"] == []


async def test_classify_rejects_oversized_and_control_input(
    client: httpx.AsyncClient, admin: ApiUser
) -> None:
    too_long = await post(client, admin, "/search/classify", {"input": "a" * 2001})
    assert too_long.status_code == 422
    control = await post(client, admin, "/search/classify", {"input": "example.com\u0000"})
    assert control.status_code == 422


async def test_input_types_and_saved_searches(client: httpx.AsyncClient, admin: ApiUser) -> None:
    types = (await get(client, admin, "/search/types")).json()["items"]
    assert len(types) == 24
    created = await post(
        client,
        admin,
        "/search/saved",
        {"name": "Watch", "query": "example.org", "indicator_type": "domain"},
    )
    assert created.status_code == 201
    duplicate = await post(client, admin, "/search/saved", {"name": "Watch", "query": "x.example"})
    assert duplicate.status_code == 409
    saved = (await get(client, admin, "/search/saved")).json()["items"]
    assert [item["name"] for item in saved] == ["Watch"]
    deleted = await client.delete(f"/api/v1/search/saved/{saved[0]['id']}", headers=admin.headers)
    assert deleted.status_code == 204


# --------------------------------------------------------------------------- collection
async def test_plan_preview(client: httpx.AsyncClient, admin: ApiUser) -> None:
    response = await post(client, admin, "/collection/plan", {"input": "example.org"})
    assert response.status_code == 200, response.text
    plan = response.json()
    steps = {step["capability_id"] or step["provider_id"]: step for step in plan["steps"]}
    assert steps["simulated.lookup"]["status"] == "ready" and steps["simulated.lookup"]["selected"]
    assert steps["simulated.probe"]["status"] == "blocked"
    planned = [step for step in plan["steps"] if step["status"] == "planned"]
    assert planned and {step["message"] for step in planned} == {PLANNED}
    assert plan["indicator"]["entity_type"] == "domain"
    assert any(module["id"] == "domain" for module in plan["modules"])


async def test_ambiguous_input_needs_a_choice(client: httpx.AsyncClient, admin: ApiUser) -> None:
    sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    refused = await post(client, admin, "/collection/plan", {"input": sha256})
    assert refused.status_code == 422
    readings = {detail["message"].split(":")[0] for detail in refused.json()["error"]["details"]}
    assert readings == {"file_hash", "certificate_fingerprint"}
    chosen = await post(client, admin, "/collection/plan", {"input": sha256, "type": "file_hash"})
    assert chosen.status_code == 200 and chosen.json()["indicator"]["type"] == "file_hash"


async def test_collection_end_to_end(
    client: httpx.AsyncClient, admin: ApiUser, app: FastAPI
) -> None:
    submitted = await post(client, admin, "/collection/requests", {"input": "example.org"})
    assert submitted.status_code == 201, submitted.text
    request_id = submitted.json()["id"]
    assert await run_jobs(app) == 1

    detail = (await get(client, admin, f"/collection/requests/{request_id}")).json()
    assert detail["request"]["status"] == "completed" and detail["request"]["is_simulated"] is True
    (job,) = detail["jobs"]
    assert job["status"] == "succeeded" and job["outcome"]["evidence"] == 3
    assert detail["plan"]["steps"]  # the plan as shown is kept with the request

    job_detail = (await get(client, admin, f"/collection/jobs/{job['id']}")).json()
    assert [event["kind"] for event in job_detail["events"]] == ["created", "started", "succeeded"]
    assert job_detail["evidence_count"] == 3 and len(job_detail["results"]) == 1

    evidence = (await get(client, admin, "/evidence", job_id=job["id"])).json()["items"]
    assert len(evidence) == 3 and all(item["is_simulated"] for item in evidence)
    one = (await get(client, admin, f"/evidence/{evidence[0]['id']}")).json()
    assert one["integrity"]["content_hash_valid"] and one["integrity"]["raw_hash_valid"]
    assert one["source"]["id"] == "simulated" and one["source"]["is_simulated"]
    assert one["entity"]["canonical_key"] == "example.org"

    raw = (await get(client, admin, f"/evidence/{evidence[0]['id']}/raw")).json()
    assert raw["format"] == "json" and raw["redacted"] and raw["simulated"]
    unmasked = (
        await get(client, admin, f"/evidence/{evidence[0]['id']}/raw", unmasked="true")
    ).json()
    assert unmasked["redacted"] is False

    entities = (await get(client, admin, "/entities", type="domain", search="example")).json()[
        "items"
    ]
    assert any(item["canonical_key"] == "example.org" for item in entities)
    sources = {item["id"] for item in (await get(client, admin, "/sources")).json()["items"]}
    assert {"simulated", "shodan", "omniosint.input"} <= sources
    jobs = (await get(client, admin, "/collection/jobs", status="succeeded")).json()["items"]
    assert [item["id"] for item in jobs] == [job["id"]]


async def test_failures_are_visible_over_the_api(
    client: httpx.AsyncClient, admin: ApiUser, app: FastAPI
) -> None:
    submitted = await post(
        client,
        admin,
        "/collection/requests",
        {"input": "example.org", "provider_options": {"simulate": "quota"}},
    )
    request_id = submitted.json()["id"]
    await run_jobs(app)
    (job,) = (await get(client, admin, f"/collection/requests/{request_id}")).json()["jobs"]
    assert job["status"] == "failed" and job["error"]["code"] == "provider_quota_exceeded"
    assert job["error"]["message"] == "Simulated quota exhaustion."
    retried = await post(client, admin, f"/collection/jobs/{job['id']}/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    cancelled = await post(client, admin, f"/collection/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    again = await post(client, admin, f"/collection/jobs/{job['id']}/cancel")
    assert again.status_code == 409


# --------------------------------------------------------------------------- permissions
async def test_permissions_per_role(
    client: httpx.AsyncClient, admin: ApiUser, app: FastAPI
) -> None:
    viewer = await user_as(client, admin, "viewer1", "viewer")
    analyst = await user_as(client, admin, "analyst1", "analyst")
    auditor = await user_as(client, admin, "auditor1", "auditor")

    assert (
        await post(client, viewer, "/search/classify", {"input": "example.org"})
    ).status_code == 403
    assert (
        await post(client, auditor, "/collection/requests", {"input": "example.org"})
    ).status_code == 403
    assert (
        await post(client, auditor, "/collection/plan", {"input": "example.org"})
    ).status_code == 200
    submitted = await post(client, analyst, "/collection/requests", {"input": "example.org"})
    assert submitted.status_code == 201
    await run_jobs(app)
    evidence = (await get(client, analyst, "/evidence")).json()["items"]
    raw = await get(client, analyst, f"/evidence/{evidence[0]['id']}/raw", unmasked="true")
    assert raw.status_code == 403
    assert (await get(client, analyst, f"/evidence/{evidence[0]['id']}/raw")).status_code == 200
    scope = await post(client, analyst, "/scopes", _scope_body())
    assert scope.status_code == 403
    denials = await fetch_all(
        app.state.ctx.settings.database.url.get_secret_value(),
        "SELECT count(*) FROM audit_events WHERE action = 'authz.denied'",
    )
    assert denials[0][0] == 4  # viewer, auditor, unmasked raw, scope creation


def _scope_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Test engagement",
        "mode": "authorized_discovery",
        "authorized_by": "Owner of 198.51.100.0/24 (test letter)",
        "authorization_reference": "TEST-1",
        "valid_until": isoformat(utcnow() + timedelta(days=7)),
        "authorization_confirmed": True,
        "rules": [{"kind": "cidr", "value": "198.51.100.0/24"}],
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- scopes
async def test_scope_lifecycle(client: httpx.AsyncClient, admin: ApiUser) -> None:
    unconfirmed = await post(client, admin, "/scopes", _scope_body(authorization_confirmed=False))
    assert unconfirmed.status_code == 422
    too_broad = await post(
        client, admin, "/scopes", _scope_body(rules=[{"kind": "cidr", "value": "0.0.0.0/0"}])
    )
    assert too_broad.status_code == 422
    created = await post(client, admin, "/scopes", _scope_body())
    assert created.status_code == 201, created.text
    scope = created.json()["scope"]
    assert scope["status"] == "active" and scope["approved_at"]

    excluded = await post(
        client,
        admin,
        f"/scopes/{scope['id']}/rules",
        {"kind": "ip", "value": "198.51.100.66", "is_exclusion": True},
    )
    assert excluded.status_code == 201 and len(excluded.json()["rules"]) == 2
    inside = (
        await post(client, admin, f"/scopes/{scope['id']}/check", {"input": "198.51.100.7"})
    ).json()
    assert inside["allowed"] and inside["code"] == "allowed"
    blocked = (
        await post(client, admin, f"/scopes/{scope['id']}/check", {"input": "198.51.100.66"})
    ).json()
    assert not blocked["allowed"] and blocked["code"] == "target_excluded"
    assessment = (
        await post(
            client,
            admin,
            f"/scopes/{scope['id']}/check",
            {"input": "198.51.100.7", "operation": "assessment"},
        )
    ).json()
    assert assessment["code"] == "operation_not_permitted"

    revoked = await post(
        client, admin, f"/scopes/{scope['id']}/revoke", {"reason": "Engagement over."}
    )
    assert revoked.status_code == 200 and revoked.json()["scope"]["status"] == "revoked"
    late = await post(
        client, admin, f"/scopes/{scope['id']}/rules", {"kind": "ip", "value": "198.51.100.9"}
    )
    assert late.status_code == 409
    listed = (await get(client, admin, "/scopes")).json()["items"]
    assert [item["status"] for item in listed] == ["revoked"]


async def test_active_operation_through_the_api(
    client: httpx.AsyncClient, admin: ApiUser, app: FastAPI
) -> None:
    analyst = await user_as(client, admin, "analyst2", "analyst")
    scope = (await post(client, admin, "/scopes", _scope_body())).json()["scope"]
    body = {
        "input": "198.51.100.7",
        "mode": "active",
        "scope_id": scope["id"],
        "providers": ["simulated"],
    }
    plan = (await post(client, analyst, "/collection/plan", body)).json()
    probe = next(step for step in plan["steps"] if step["capability_id"] == "simulated.probe")
    assert probe["status"] == "needs_approval" and probe["scope_decision"]["allowed"]

    request_id = (await post(client, analyst, "/collection/requests", body)).json()["id"]
    await run_jobs(app)
    jobs = {
        job["capability"]: job
        for job in (await get(client, admin, f"/collection/requests/{request_id}")).json()["jobs"]
    }
    assert jobs["simulated.probe"]["status"] == "awaiting_approval"
    assert (
        await post(client, analyst, f"/collection/jobs/{jobs['simulated.probe']['id']}/approve")
    ).status_code == 403
    approved = await post(
        client, admin, f"/collection/jobs/{jobs['simulated.probe']['id']}/approve"
    )
    assert approved.status_code == 200 and approved.json()["status"] == "queued"
    await run_jobs(app)
    final = (await get(client, admin, f"/collection/jobs/{jobs['simulated.probe']['id']}")).json()
    assert final["job"]["status"] == "succeeded"
    assert "scope_checked" in [event["kind"] for event in final["events"]]


# --------------------------------------------------------------------------- providers
async def test_adapters_and_health(client: httpx.AsyncClient, admin: ApiUser) -> None:
    adapters = (await get(client, admin, "/providers/adapters")).json()["items"]
    (simulated,) = adapters
    assert (
        simulated["id"] == "simulated"
        and simulated["status"] == "available"
        and simulated["simulated"]
    )
    assert {capability["id"] for capability in simulated["capabilities"]} == {
        "simulated.lookup",
        "simulated.paid_lookup",
        "simulated.probe",
    }
    health = (await post(client, admin, "/providers/simulated/health")).json()
    assert health["status"] == "ok"
    planned = (await post(client, admin, "/providers/shodan/health")).json()
    assert planned["detail"] == PLANNED
    catalogue = (await get(client, admin, "/providers/shodan")).json()
    assert catalogue["status"] == "planned"
