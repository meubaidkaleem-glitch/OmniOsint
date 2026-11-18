"""The collection pipeline against PostgreSQL (Phase 2 acceptance).

* A mock provider returns structured data through the real pipeline.
* Results are normalised and stored; evidence stays linked to its source.
* Failed provider operations are handled and visible in job history.
* No active operation runs without passing the scope manager.
"""

from __future__ import annotations

import asyncio
import ipaddress
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from omniosint.audit.service import Actor
from omniosint.collection import queue
from omniosint.collection import service as collection
from omniosint.collection.executor import Collector
from omniosint.collection.planner import PlanOptions
from omniosint.collection.runtime import IntelRuntime
from omniosint.core.config import Settings
from omniosint.core.errors import Conflict, ValidationFailed
from omniosint.core.paths import AppPaths
from omniosint.core.timeutil import utcnow
from omniosint.database.engine import Database
from omniosint.database.models import (
    AuditEvent,
    CollectionJob,
    CollectionJobEvent,
    CollectionResult,
    Entity,
    Evidence,
    EvidenceSource,
    ProviderUsage,
    RawObject,
)
from omniosint.evidence.service import check_integrity, raw_view
from omniosint.indicators import classify
from omniosint.providers.base import Indicator
from omniosint.scopes import service as scopes
from tests.helpers import make_settings

ACTOR = Actor(user_id=None, label="tester")
TEST_NET_1 = ipaddress.ip_network("192.0.2.0/24")


@pytest.fixture
def pipeline_settings(app_paths: AppPaths, clean_database: str) -> Settings:
    return make_settings(
        app_paths,
        clean_database,
        collection={
            "enable_simulated_provider": True,
            "retry_base_seconds": 0.1,
            "retry_max_seconds": 0.5,
            "max_attempts": 3,
        },
    )


@pytest.fixture
async def database(pipeline_settings: Settings, app_paths: AppPaths) -> AsyncIterator[Database]:
    db = Database.from_settings(pipeline_settings, app_paths)
    yield db
    await db.dispose()


@pytest.fixture
async def runtime(
    pipeline_settings: Settings, app_paths: AppPaths, database: Database
) -> AsyncIterator[IntelRuntime]:
    built = await IntelRuntime.build(pipeline_settings, app_paths, database)
    yield built
    await built.aclose()


@pytest.fixture
def collector(database: Database, pipeline_settings: Settings, runtime: IntelRuntime) -> Collector:
    return Collector(database, pipeline_settings, runtime.manager, runtime.store)


def indicator(text_input: str) -> Indicator:
    best = classify(text_input).best
    assert best is not None, text_input
    return Indicator(best.type, best.value, best.display, best.entity_type, best.details)


async def submit(
    database: Database, runtime: IntelRuntime, text_input: str, **options: Any
) -> uuid.UUID:
    async with database.session() as session:
        request = await collection.submit(
            session,
            runtime,
            indicator=indicator(text_input),
            input_text=text_input,
            options=PlanOptions(**options),
            actor=ACTOR,
        )
        return request.id


async def run_until_settled(
    collector: Collector, database: Database, request_id: uuid.UUID
) -> None:
    """Run due jobs, waiting for scheduled retries, until the request settles."""
    for _ in range(100):
        await collector.drain()
        async with database.session() as session:
            detail = await collection.get_request(session, request_id)
        if all(job.status not in ("queued", "running") for job in detail.jobs):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the request did not settle")


async def jobs_of(database: Database, request_id: uuid.UUID) -> list[CollectionJob]:
    async with database.session() as session:
        return (await collection.get_request(session, request_id)).jobs


async def events_of(database: Database, job_id: uuid.UUID) -> list[str]:
    async with database.session() as session:
        rows = await session.execute(
            select(CollectionJobEvent.kind)
            .where(CollectionJobEvent.job_id == job_id)
            .order_by(CollectionJobEvent.occurred_at, CollectionJobEvent.id)
        )
        return [row[0] for row in rows]


# --------------------------------------------------------------------------- plan
async def test_plan_shows_every_provider_with_its_real_status(
    database: Database, runtime: IntelRuntime
) -> None:
    async with database.session() as session:
        plan = await collection.preview(session, runtime, indicator("example.org"), PlanOptions())
    by_capability = {step.capability_id: step for step in plan.steps if step.capability_id}
    assert by_capability["simulated.lookup"].status == "ready"
    assert by_capability["simulated.paid_lookup"].status == "skipped"
    assert by_capability["simulated.probe"].status == "blocked"
    planned = [step for step in plan.steps if step.status == "planned"]
    assert planned and all(
        step.message == "Planned — integration not yet implemented." for step in planned
    )
    assert any("simulated" in warning for warning in plan.warnings)
    with_paid = await _preview(database, runtime, "example.org", strategy="include_paid")
    assert with_paid["simulated.paid_lookup"].status == "needs_approval"


async def _preview(
    database: Database, runtime: IntelRuntime, text_input: str, **options: Any
) -> dict[str, Any]:
    async with database.session() as session:
        plan = await collection.preview(
            session, runtime, indicator(text_input), PlanOptions(**options)
        )
    return {step.capability_id: step for step in plan.steps if step.capability_id}


async def test_nothing_runnable_is_refused(database: Database, runtime: IntelRuntime) -> None:
    with pytest.raises(ValidationFailed):
        await submit(database, runtime, "example.org", providers=("shodan",))


# --------------------------------------------------------------------------- the pipeline
async def test_mock_provider_data_goes_through_the_real_pipeline(
    database: Database, runtime: IntelRuntime, collector: Collector
) -> None:
    request_id = await submit(database, runtime, "Example.ORG")
    await run_until_settled(collector, database, request_id)
    (job,) = await jobs_of(database, request_id)
    assert job.status == "succeeded"
    assert job.outcome and job.outcome["evidence"] == 3 and job.outcome["simulated"] is True
    assert await events_of(database, job.id) == ["created", "started", "succeeded"]

    async with database.session() as session:
        detail = await collection.get_request(session, request_id)
        assert detail.request.status == "completed"
        evidence = list(
            (await session.execute(select(Evidence).where(Evidence.job_id == job.id))).scalars()
        )
        assert len(evidence) == 3
        result = (
            await session.execute(select(CollectionResult).where(CollectionResult.job_id == job.id))
        ).scalar_one()
        source = await session.get(EvidenceSource, "simulated")
        assert source is not None and source.is_simulated
        subject = await session.get(Entity, evidence[0].entity_id)
        assert subject is not None and subject.canonical_key == "example.org"
        assert subject.type == "domain" and subject.is_simulated is False  # the input is real
        for item in evidence:
            assert item.is_simulated is True
            assert item.source_id == "simulated" and item.provider_id == "simulated"
            assert item.collection_result_id == result.id
            assert item.raw_sha256 == result.raw_sha256
            assert item.normalized["original"]  # provider values kept as they were
            integrity = await check_integrity(session, item, runtime.store)
            assert integrity.content_hash_valid and integrity.raw_hash_valid, integrity.detail
        related = [
            entry
            for item in evidence
            for entry in item.normalized["related"]
            if "entity_id" in entry
        ]
        assert related
        for entry in related:
            entity = await session.get(Entity, uuid.UUID(entry["entity_id"]))
            assert entity is not None and entity.is_simulated is True
            if entity.type == "ip_address":
                assert ipaddress.ip_address(entity.canonical_key) in TEST_NET_1
        raw = await session.get(RawObject, result.raw_sha256)
        assert raw is not None and raw.encryption == "aes-256-gcm"
        view = raw_view(runtime.store.get(result.raw_sha256), result.content_type, redacted=True)
        assert view["body"]["simulated"] is True
        usage = (
            await session.execute(
                select(ProviderUsage).where(ProviderUsage.provider_id == "simulated")
            )
        ).scalar_one()
        assert usage.requests == 1 and usage.failures == 0


async def test_fresh_results_are_reused_not_fetched_again(
    database: Database, runtime: IntelRuntime, collector: Collector
) -> None:
    first = await submit(database, runtime, "example.org")
    await run_until_settled(collector, database, first)
    plan = await _preview(database, runtime, "example.org")
    assert plan["simulated.lookup"].status == "cached"
    second = await submit(database, runtime, "example.org")
    await run_until_settled(collector, database, second)
    (job,) = await jobs_of(database, second)
    assert job.status == "succeeded" and job.outcome and job.outcome["from_cache"] is True
    async with database.session() as session:
        evidence = (await session.execute(select(func.count()).select_from(Evidence))).scalar_one()
        assert evidence == 3  # not duplicated
        usage = (
            await session.execute(
                select(ProviderUsage).where(ProviderUsage.provider_id == "simulated")
            )
        ).scalar_one()
        assert usage.requests == 1 and usage.cache_hits == 1
    forced = await submit(database, runtime, "example.org", force_refresh=True)
    await run_until_settled(collector, database, forced)
    (job,) = await jobs_of(database, forced)
    assert job.outcome and job.outcome["from_cache"] is False


# --------------------------------------------------------------------------- failures
@pytest.mark.parametrize(
    ("mode", "code", "attempts", "kinds"),
    [
        (
            "timeout",
            "provider_timeout",
            3,
            [
                "created",
                "started",
                "retry_scheduled",
                "started",
                "retry_scheduled",
                "started",
                "failed",
            ],
        ),
        ("quota", "provider_quota_exceeded", 1, ["created", "started", "failed"]),
        ("auth", "provider_auth_failed", 1, ["created", "started", "failed"]),
        ("malformed", "provider_malformed_response", 1, ["created", "started", "failed"]),
    ],
)
async def test_failures_are_recorded_in_job_history(
    database: Database,
    runtime: IntelRuntime,
    collector: Collector,
    mode: str,
    code: str,
    attempts: int,
    kinds: list[str],
) -> None:
    request_id = await submit(database, runtime, "example.org", provider_options={"simulate": mode})
    await run_until_settled(collector, database, request_id)
    (job,) = await jobs_of(database, request_id)
    assert job.status == "failed"
    assert job.error and job.error["code"] == code
    assert job.attempt == attempts
    assert await events_of(database, job.id) == kinds
    async with database.session() as session:
        detail = await collection.get_request(session, request_id)
        assert detail.request.status == "failed"
        evidence = (await session.execute(select(func.count()).select_from(Evidence))).scalar_one()
        assert evidence == 0
        if mode == "malformed":
            result = (
                await session.execute(
                    select(CollectionResult).where(CollectionResult.job_id == job.id)
                )
            ).scalar_one()
            assert result.normalization_error and result.normalized is None
            assert runtime.store.get(result.raw_sha256).startswith(b'{"records"')  # kept


async def test_transient_failures_are_retried(
    database: Database, runtime: IntelRuntime, collector: Collector
) -> None:
    request_id = await submit(
        database, runtime, "example.org", provider_options={"simulate": "flaky"}
    )
    await run_until_settled(collector, database, request_id)
    (job,) = await jobs_of(database, request_id)
    assert job.status == "succeeded" and job.attempt == 2
    assert await events_of(database, job.id) == [
        "created",
        "started",
        "retry_scheduled",
        "started",
        "succeeded",
    ]


async def test_partial_results_are_kept_and_marked(
    database: Database, runtime: IntelRuntime, collector: Collector
) -> None:
    request_id = await submit(
        database, runtime, "example.org", provider_options={"simulate": "partial", "pages": 3}
    )
    await run_until_settled(collector, database, request_id)
    (job,) = await jobs_of(database, request_id)
    assert job.status == "succeeded"
    assert job.outcome and job.outcome["truncated"] is True and job.outcome["pages"] == 1


async def test_lost_workers_are_recovered(
    database: Database, runtime: IntelRuntime, pipeline_settings: Settings
) -> None:
    request_id = await submit(database, runtime, "example.org")
    async with database.session() as session:
        (job,) = await queue.lease_jobs(session, owner="crashed-worker", lease_seconds=30, limit=1)
        await session.execute(
            update(CollectionJob)
            .where(CollectionJob.id == job.id)
            .values(lease_expires_at=utcnow() - timedelta(seconds=1))
        )
        await session.commit()
    async with database.session() as session:
        assert await queue.recover_expired_leases(session, pipeline_settings.collection) == 1
    (job,) = await jobs_of(database, request_id)
    assert job.status == "queued" and job.error and job.error["code"] == "worker_lost"


async def test_two_workers_never_take_the_same_job(
    database: Database, runtime: IntelRuntime
) -> None:
    for name in ("one.example", "two.example", "three.example"):
        await submit(database, runtime, name)
    async with database.session() as first, database.session() as second:
        leased = await asyncio.gather(
            queue.lease_jobs(first, owner="a", lease_seconds=30, limit=2),
            queue.lease_jobs(second, owner="b", lease_seconds=30, limit=2),
        )
    ids = [job.id for batch in leased for job in batch]
    assert len(ids) == len(set(ids)) == 3


# --------------------------------------------------------------------------- user actions
async def test_cancel_and_retry(
    database: Database, runtime: IntelRuntime, collector: Collector
) -> None:
    request_id = await submit(
        database, runtime, "example.org", provider_options={"simulate": "quota"}
    )
    (job,) = await jobs_of(database, request_id)
    async with database.session() as session:
        await collection.cancel_job(session, job.id, actor=ACTOR)
    (job,) = await jobs_of(database, request_id)
    assert job.status == "cancelled"
    async with database.session() as session:
        assert (await collection.get_request(session, request_id)).request.status == "cancelled"
        with pytest.raises(Conflict):
            await collection.cancel_job(session, job.id, actor=ACTOR)
    async with database.session() as session:
        await collection.retry_job(session, job.id, actor=ACTOR)
    await run_until_settled(collector, database, request_id)
    (job,) = await jobs_of(database, request_id)
    assert job.status == "failed" and job.error and job.error["code"] == "provider_quota_exceeded"


# --------------------------------------------------------------------------- scope gate
async def _scope(
    database: Database, *, mode: str = "authorized_discovery", **rules: Any
) -> uuid.UUID:
    async with database.session() as session:
        scope = await scopes.create_scope(
            session,
            scopes.ScopeInput(
                name="Test engagement",
                mode=mode,
                authorized_by="Owner of 198.51.100.0/24 (test letter)",
                valid_until=utcnow() + timedelta(days=7),
                authorization_confirmed=True,
                rules=tuple(scopes.RuleInput(**rule) for rule in rules.get("rules", ())),
            ),
            actor=ACTOR,
        )
        return scope.id


async def test_active_operations_need_a_scope_and_approval(
    database: Database, runtime: IntelRuntime, collector: Collector
) -> None:
    no_scope = await _preview(database, runtime, "198.51.100.7", mode="active")
    assert no_scope["simulated.probe"].status == "blocked"
    assert no_scope["simulated.probe"].scope_decision["code"] == "scope_required"

    scope_id = await _scope(
        database,
        rules=[
            {"kind": "cidr", "value": "198.51.100.0/24"},
            {"kind": "ip", "value": "198.51.100.66", "is_exclusion": True},
        ],
    )
    excluded = await _preview(database, runtime, "198.51.100.66", mode="active", scope_id=scope_id)
    assert excluded["simulated.probe"].scope_decision["code"] == "target_excluded"
    outside = await _preview(database, runtime, "203.0.113.9", mode="active", scope_id=scope_id)
    assert outside["simulated.probe"].scope_decision["code"] == "target_not_in_scope"

    request_id = await submit(
        database,
        runtime,
        "198.51.100.7",
        mode="active",
        scope_id=scope_id,
        providers=("simulated",),
    )
    jobs = {job.capability: job for job in await jobs_of(database, request_id)}
    probe = jobs["simulated.probe"]
    assert probe.status == "awaiting_approval" and probe.is_active and probe.scope_id == scope_id
    await run_until_settled(collector, database, request_id)
    probe = {job.capability: job for job in await jobs_of(database, request_id)}["simulated.probe"]
    assert probe.status == "awaiting_approval"  # never ran without approval

    async with database.session() as session:
        await collection.approve_job(session, probe.id, actor=ACTOR)
    await run_until_settled(collector, database, request_id)
    probe = {job.capability: job for job in await jobs_of(database, request_id)}["simulated.probe"]
    assert probe.status == "succeeded"
    assert "scope_checked" in await events_of(database, probe.id)
    async with database.session() as session:
        checks = (
            await session.execute(
                select(AuditEvent.outcome).where(
                    AuditEvent.action == "scope.checked", AuditEvent.target_id == str(probe.id)
                )
            )
        ).all()
        assert [row[0] for row in checks] == ["success"]


async def test_revoked_scope_stops_an_approved_job(
    database: Database, runtime: IntelRuntime, collector: Collector
) -> None:
    scope_id = await _scope(database, rules=[{"kind": "ip", "value": "198.51.100.7"}])
    request_id = await submit(
        database,
        runtime,
        "198.51.100.7",
        mode="active",
        scope_id=scope_id,
        providers=("simulated",),
    )
    probe = {job.capability: job for job in await jobs_of(database, request_id)}["simulated.probe"]
    async with database.session() as session:
        await collection.approve_job(session, probe.id, actor=ACTOR)
    async with database.session() as session:
        await scopes.revoke_scope(session, scope_id, "Engagement ended early.", actor=ACTOR)
    await run_until_settled(collector, database, request_id)
    probe = {job.capability: job for job in await jobs_of(database, request_id)}["simulated.probe"]
    assert probe.status == "failed" and probe.error and probe.error["code"] == "scope_denied"
    async with database.session() as session:
        denied = (
            await session.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "scope.checked", AuditEvent.outcome == "denied")
            )
        ).scalar_one()
        assert denied == 1
    # A retried active job must be approved again, and a revoked scope refuses it.
    async with database.session() as session:
        retried = await collection.retry_job(session, probe.id, actor=ACTOR)
        assert retried.status == "awaiting_approval"
    async with database.session() as session:
        with pytest.raises(Conflict, match="no longer permits"):
            await collection.approve_job(session, probe.id, actor=ACTOR)


# --------------------------------------------------------------------------- evidence store
async def test_evidence_is_append_only(
    database: Database, runtime: IntelRuntime, collector: Collector
) -> None:
    request_id = await submit(database, runtime, "example.org")
    await run_until_settled(collector, database, request_id)
    async with database.session() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text("UPDATE evidence SET observation_kind = 'tampered'"))
        await session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text("DELETE FROM evidence"))
        await session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text("TRUNCATE evidence CASCADE"))
        await session.rollback()
        await session.execute(text("SET LOCAL omniosint.evidence_purge = 'on'"))
        await session.execute(text("DELETE FROM evidence"))
        await session.rollback()
        remaining = (await session.execute(select(func.count()).select_from(Evidence))).scalar_one()
        assert remaining == 3
