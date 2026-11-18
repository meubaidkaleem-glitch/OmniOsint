"""Collection requests and jobs: submit a plan, approve, cancel, retry, list.

Every change is audited. A request records the plan exactly as it was shown,
including the providers that could not run and why, so the collection history
is complete.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.audit.service import Actor, RequestInfo, record
from omniosint.collection import queue
from omniosint.collection.planner import (
    CollectionPlan,
    PlanOptions,
    PlanStep,
    options_for_provider,
)
from omniosint.collection.runtime import IntelRuntime
from omniosint.core.errors import Conflict, NotFound, ValidationFailed
from omniosint.core.pagination import Page, clamp_limit, decode_cursor, encode_cursor
from omniosint.core.timeutil import utcnow
from omniosint.database.models import (
    CollectionJob,
    CollectionJobEvent,
    CollectionRequest,
    CollectionResult,
    Evidence,
    SavedSearch,
    SearchHistoryEntry,
)
from omniosint.database.models.collection import FINISHED_JOB_STATUSES
from omniosint.evidence.entities import canonical_value, upsert_entity
from omniosint.indicators.model import Classification
from omniosint.indicators.types import IndicatorType
from omniosint.providers.base import Indicator, Operation
from omniosint.scopes.manager import evaluate
from omniosint.scopes.rules import target_for
from omniosint.scopes.service import load_view

HISTORY_LIMIT = 200


def _uuid_cursor(cursor: str | None) -> uuid.UUID | None:
    if not cursor:
        return None
    (position,) = decode_cursor(cursor, parts=1)
    try:
        return uuid.UUID(str(position))
    except ValueError as error:
        raise ValidationFailed("The cursor is not valid.") from error


# --------------------------------------------------------------------------- plans
async def preview(
    session: AsyncSession,
    runtime: IntelRuntime,
    indicator: Indicator,
    options: PlanOptions,
    *,
    now: datetime | None = None,
) -> CollectionPlan:
    scope = None
    if options.scope_id is not None:
        try:
            scope = await load_view(session, options.scope_id)
        except NotFound as error:
            raise ValidationFailed(
                "The scope was not found.",
                details=[{"field": "scope_id", "message": "Unknown scope."}],
            ) from error
    return await runtime.planner.plan(session, indicator, options, scope=scope, now=now or utcnow())


async def submit(
    session: AsyncSession,
    runtime: IntelRuntime,
    *,
    indicator: Indicator,
    input_text: str,
    options: PlanOptions,
    actor: Actor,
    request: RequestInfo | None = None,
) -> CollectionRequest:
    """Create a request and its jobs from a freshly computed plan. Commits."""
    plan = await preview(session, runtime, indicator, options)
    selected = plan.selected
    if not selected:
        raise ValidationFailed(
            "Nothing in the plan can run for this indicator.",
            details=[{"field": "plan", "message": message} for message in plan.warnings],
        )
    entity_id = None
    if indicator.entity_type is not None:
        try:
            key, display = canonical_value(indicator.entity_type, indicator.value)
        except ValueError:
            key, display = indicator.value, indicator.display
        entity_id = await upsert_entity(
            session,
            indicator.entity_type,
            key,
            indicator.display or display,
            observed_at=None,
            simulated=False,
        )
    collection_request = CollectionRequest(
        input_text=input_text[:4000],
        indicator_type=indicator.type.value,
        indicator_value=indicator.value,
        entity_id=entity_id,
        mode=options.mode,
        strategy=options.strategy,
        scope_id=options.scope_id,
        options={
            "providers": list(options.providers) if options.providers is not None else None,
            "force_refresh": options.force_refresh,
            "provider_options": options.provider_options,
        },
        plan=plan.as_dict(),
        status="pending",
        is_simulated=all(step.simulated for step in selected),
        created_by=actor.user_id,
    )
    session.add(collection_request)
    await session.flush()
    settings = runtime.settings.collection
    pairs: list[tuple[CollectionJob, PlanStep]] = []
    for step in selected:
        if step.capability_id is None or step.cache_key is None:
            continue  # catalogue entries are never selected
        status = "awaiting_approval" if step.status == "needs_approval" else "queued"
        job = CollectionJob(
            request_id=collection_request.id,
            entity_id=entity_id,
            indicator_type=indicator.type.value,
            indicator_value=indicator.value,
            provider_id=step.provider_id,
            capability=step.capability_id,
            is_active=step.active,
            is_simulated=step.simulated,
            scope_id=options.scope_id if step.active else None,
            status=status,
            max_attempts=settings.max_attempts,
            options={
                "provider_options": options_for_provider(options, step.simulated),
                "force_refresh": options.force_refresh,
                "operation": step.operation,
                "indicator": {
                    "display": indicator.display,
                    "entity_type": indicator.entity_type.value if indicator.entity_type else None,
                    "details": dict(indicator.details),
                },
            },
            cost=step.cost,
            cache_key=step.cache_key,
            requested_by=actor.user_id,
        )
        session.add(job)
        pairs.append((job, step))
    await session.flush()
    jobs = [job for job, _step in pairs]
    for job, step in pairs:
        queue.add_event(
            session,
            job.id,
            "created",
            step.message if job.status == "awaiting_approval" else "Queued.",
            {"status": job.status, "plan_status": step.status},
        )
    collection_request.status = queue.request_status([job.status for job in jobs])
    record(
        session,
        action="collection.requested",
        actor=actor,
        target_type="collection_request",
        target_id=collection_request.id,
        request=request,
        details={
            "indicator_type": indicator.type.value,
            "indicator": indicator.value,
            "mode": options.mode,
            "scope_id": str(options.scope_id) if options.scope_id else None,
            "jobs": len(jobs),
            "awaiting_approval": sum(1 for job in jobs if job.status == "awaiting_approval"),
            "simulated": collection_request.is_simulated,
        },
    )
    await session.commit()
    return collection_request


# --------------------------------------------------------------------------- jobs
async def _job(session: AsyncSession, job_id: uuid.UUID) -> CollectionJob:
    job = await session.get(CollectionJob, job_id, with_for_update=True)
    if job is None:
        raise NotFound("The job was not found.")
    return job


async def approve_job(
    session: AsyncSession, job_id: uuid.UUID, *, actor: Actor, request: RequestInfo | None = None
) -> CollectionJob:
    job = await _job(session, job_id)
    if job.status != "awaiting_approval":
        raise Conflict(f"Only a job awaiting approval can be approved (this one is {job.status}).")
    details: dict[str, Any] = {}
    if job.is_active:
        scope = await load_view(session, job.scope_id) if job.scope_id else None
        decision = evaluate(
            Operation(job.options.get("operation") or Operation.DISCOVERY.value),
            target_for(IndicatorType(job.indicator_type), job.indicator_value),
            scope,
            now=utcnow(),
        )
        details["scope"] = decision.as_dict()
        if not decision.allowed:
            record(
                session,
                action="collection.job.approval_refused",
                actor=actor,
                outcome="denied",
                target_type="collection_job",
                target_id=job.id,
                request=request,
                details=details,
            )
            await session.commit()
            raise Conflict(f"The scope no longer permits this job: {decision.reason}")
    now = utcnow()
    job.status = "queued"
    job.approved_by = actor.user_id
    job.approved_at = now
    job.scheduled_at = now
    queue.add_event(session, job.id, "approved", f"Approved by {actor.label}.", details)
    await queue.refresh_request_status(session, job.request_id)
    record(
        session,
        action="collection.job.approved",
        actor=actor,
        target_type="collection_job",
        target_id=job.id,
        request=request,
        details={"provider": job.provider_id, "capability": job.capability, **details},
    )
    await session.commit()
    return job


async def cancel_job(
    session: AsyncSession, job_id: uuid.UUID, *, actor: Actor, request: RequestInfo | None = None
) -> CollectionJob:
    job = await _job(session, job_id)
    if job.status in FINISHED_JOB_STATUSES:
        raise Conflict(f"The job has already finished ({job.status}).")
    if job.status == "running":
        if job.cancel_requested_at is None:
            job.cancel_requested_at = utcnow()
            queue.add_event(
                session, job.id, "cancel_requested", f"Cancellation requested by {actor.label}."
            )
    else:
        queue.finish(session, job, "cancelled", f"Cancelled by {actor.label}.")
    await queue.refresh_request_status(session, job.request_id)
    record(
        session,
        action="collection.job.cancelled",
        actor=actor,
        target_type="collection_job",
        target_id=job.id,
        request=request,
        details={"provider": job.provider_id, "capability": job.capability, "status": job.status},
    )
    await session.commit()
    return job


async def retry_job(
    session: AsyncSession, job_id: uuid.UUID, *, actor: Actor, request: RequestInfo | None = None
) -> CollectionJob:
    job = await _job(session, job_id)
    if job.status not in ("failed", "cancelled"):
        raise Conflict(f"Only a failed or cancelled job can be retried (this one is {job.status}).")
    job.max_attempts = max(job.max_attempts, job.attempt + 1)
    job.finished_at = None
    job.cancel_requested_at = None
    job.scheduled_at = utcnow()
    # An active operation is approved again, against the scope as it is now.
    job.status = "awaiting_approval" if job.is_active else "queued"
    if job.is_active:
        job.approved_by = None
        job.approved_at = None
    queue.add_event(
        session,
        job.id,
        "retry_requested",
        f"Retry requested by {actor.label}.",
        {"status": job.status},
    )
    await queue.refresh_request_status(session, job.request_id)
    record(
        session,
        action="collection.job.retried",
        actor=actor,
        target_type="collection_job",
        target_id=job.id,
        request=request,
        details={"provider": job.provider_id, "capability": job.capability, "status": job.status},
    )
    await session.commit()
    return job


async def cancel_request(
    session: AsyncSession,
    request_id: uuid.UUID,
    *,
    actor: Actor,
    request: RequestInfo | None = None,
) -> CollectionRequest:
    collection_request = await session.get(CollectionRequest, request_id)
    if collection_request is None:
        raise NotFound("The collection request was not found.")
    jobs = list(
        (
            await session.execute(
                select(CollectionJob)
                .where(CollectionJob.request_id == request_id)
                .with_for_update()
            )
        ).scalars()
    )
    changed = 0
    for job in jobs:
        if job.status in ("queued", "awaiting_approval"):
            queue.finish(session, job, "cancelled", f"Cancelled with the request by {actor.label}.")
            changed += 1
        elif job.status == "running" and job.cancel_requested_at is None:
            job.cancel_requested_at = utcnow()
            queue.add_event(
                session, job.id, "cancel_requested", f"Cancellation requested by {actor.label}."
            )
            changed += 1
    await queue.refresh_request_status(session, request_id)
    record(
        session,
        action="collection.request.cancelled",
        actor=actor,
        target_type="collection_request",
        target_id=request_id,
        request=request,
        details={"jobs_affected": changed},
    )
    await session.commit()
    return collection_request


# --------------------------------------------------------------------------- queries
async def list_requests(
    session: AsyncSession, *, limit: int | None = None, cursor: str | None = None
) -> Page[CollectionRequest]:
    size = clamp_limit(limit)
    query = select(CollectionRequest)
    position = _uuid_cursor(cursor)
    if position is not None:
        query = query.where(CollectionRequest.id < position)
    rows = list(
        (
            await session.execute(query.order_by(CollectionRequest.id.desc()).limit(size + 1))
        ).scalars()
    )
    next_cursor = encode_cursor([str(rows[size - 1].id)]) if len(rows) > size else None
    return Page(items=rows[:size], next_cursor=next_cursor)


@dataclass(frozen=True, slots=True)
class RequestDetail:
    request: CollectionRequest
    jobs: list[CollectionJob]


async def get_request(session: AsyncSession, request_id: uuid.UUID) -> RequestDetail:
    collection_request = await session.get(CollectionRequest, request_id)
    if collection_request is None:
        raise NotFound("The collection request was not found.")
    jobs = list(
        (
            await session.execute(
                select(CollectionJob)
                .where(CollectionJob.request_id == request_id)
                .order_by(CollectionJob.created_at, CollectionJob.id)
            )
        ).scalars()
    )
    return RequestDetail(collection_request, jobs)


async def list_jobs(
    session: AsyncSession,
    *,
    status: str | None = None,
    provider_id: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[CollectionJob]:
    size = clamp_limit(limit)
    filters: list[ColumnElement[bool]] = []
    if status:
        filters.append(CollectionJob.status == status)
    if provider_id:
        filters.append(CollectionJob.provider_id == provider_id)
    position = _uuid_cursor(cursor)
    if position is not None:
        filters.append(CollectionJob.id < position)
    query = select(CollectionJob).where(*filters).order_by(CollectionJob.id.desc()).limit(size + 1)
    rows = list((await session.execute(query)).scalars())
    next_cursor = encode_cursor([str(rows[size - 1].id)]) if len(rows) > size else None
    return Page(items=rows[:size], next_cursor=next_cursor)


@dataclass(frozen=True, slots=True)
class JobDetail:
    job: CollectionJob
    events: list[CollectionJobEvent]
    results: list[CollectionResult]
    evidence_count: int


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> JobDetail:
    job = await session.get(CollectionJob, job_id)
    if job is None:
        raise NotFound("The job was not found.")
    events = list(
        (
            await session.execute(
                select(CollectionJobEvent)
                .where(CollectionJobEvent.job_id == job_id)
                .order_by(CollectionJobEvent.occurred_at, CollectionJobEvent.id)
            )
        ).scalars()
    )
    results = list(
        (
            await session.execute(
                select(CollectionResult)
                .where(CollectionResult.job_id == job_id)
                .order_by(CollectionResult.page)
            )
        ).scalars()
    )
    evidence_count = (
        await session.execute(
            select(func.count()).select_from(Evidence).where(Evidence.job_id == job_id)
        )
    ).scalar_one()
    return JobDetail(job, events, results, int(evidence_count))


# --------------------------------------------------------------------------- search history
async def record_search(
    session: AsyncSession, user_id: uuid.UUID, classification: Classification
) -> None:
    """Remember a search for its user (the newest 200 are kept). Commits."""
    if not classification.input:
        return
    session.add(
        SearchHistoryEntry(
            user_id=user_id,
            query=classification.input[:2000],
            status=classification.status,
            types=[item.type.value for item in classification.candidates[:5]],
        )
    )
    await session.flush()
    keep = (
        select(SearchHistoryEntry.id)
        .where(SearchHistoryEntry.user_id == user_id)
        .order_by(SearchHistoryEntry.created_at.desc(), SearchHistoryEntry.id.desc())
        .limit(HISTORY_LIMIT)
    )
    await session.execute(
        delete(SearchHistoryEntry).where(
            SearchHistoryEntry.user_id == user_id, SearchHistoryEntry.id.not_in(keep)
        )
    )
    await session.commit()


async def list_history(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = 50
) -> Sequence[SearchHistoryEntry]:
    return list(
        (
            await session.execute(
                select(SearchHistoryEntry)
                .where(SearchHistoryEntry.user_id == user_id)
                .order_by(SearchHistoryEntry.created_at.desc(), SearchHistoryEntry.id.desc())
                .limit(max(1, min(limit, HISTORY_LIMIT)))
            )
        ).scalars()
    )


async def clear_history(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(
        delete(SearchHistoryEntry).where(SearchHistoryEntry.user_id == user_id)
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def list_saved(session: AsyncSession, user_id: uuid.UUID) -> Sequence[SavedSearch]:
    return list(
        (
            await session.execute(
                select(SavedSearch).where(SavedSearch.user_id == user_id).order_by(SavedSearch.name)
            )
        ).scalars()
    )


async def save_search(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    query: str,
    indicator_type: str | None,
    options: dict[str, Any],
) -> SavedSearch:
    clean = " ".join(name.split())
    if not 1 <= len(clean) <= 128:
        raise ValidationFailed(
            "The name must be 1 to 128 characters.",
            details=[{"field": "name", "message": "1 to 128 characters."}],
        )
    existing = (
        await session.execute(
            select(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.name == clean)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise Conflict("A saved search with this name exists.")
    saved = SavedSearch(
        user_id=user_id,
        name=clean,
        query=query[:2000],
        indicator_type=indicator_type,
        options=options,
    )
    session.add(saved)
    await session.commit()
    return saved


async def delete_saved(session: AsyncSession, user_id: uuid.UUID, saved_id: uuid.UUID) -> None:
    saved = await session.get(SavedSearch, saved_id)
    if saved is None or saved.user_id != user_id:
        raise NotFound("The saved search was not found.")
    await session.delete(saved)
    await session.commit()
