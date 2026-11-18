"""The durable job queue (ADR-004).

Jobs are rows in ``collection_jobs``. A worker leases queued jobs with
``FOR UPDATE SKIP LOCKED``, so several workers never take the same job, and
renews the lease while it works. A lease that runs out (the worker died) is
recovered by housekeeping. Every change of state is written to the job's
history, with the reason.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.core.config import CollectionSettings
from omniosint.core.timeutil import utcnow
from omniosint.database.models import CollectionJob, CollectionJobEvent, CollectionRequest
from omniosint.database.models.collection import FINISHED_JOB_STATUSES
from omniosint.providers.errors import ProviderError, WorkerLost


def add_event(
    session: AsyncSession,
    job_id: uuid.UUID,
    kind: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        CollectionJobEvent(job_id=job_id, kind=kind, message=message[:1024], details=details or {})
    )


async def lease_jobs(
    session: AsyncSession, *, owner: str, lease_seconds: int, limit: int
) -> list[CollectionJob]:
    """Take up to ``limit`` due jobs. Commits."""
    due = (
        select(CollectionJob.id)
        .where(CollectionJob.status == "queued", CollectionJob.scheduled_at <= func.now())
        .order_by(CollectionJob.priority.desc(), CollectionJob.scheduled_at, CollectionJob.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    statement = (
        update(CollectionJob)
        .where(CollectionJob.id.in_(due.scalar_subquery()))
        .values(
            status="running",
            lease_owner=owner,
            lease_expires_at=func.now() + timedelta(seconds=lease_seconds),
            attempt=CollectionJob.attempt + 1,
            started_at=func.coalesce(CollectionJob.started_at, func.now()),
            updated_at=func.now(),
        )
        .returning(CollectionJob)
        .execution_options(synchronize_session=False)
    )
    jobs = list((await session.execute(statement)).scalars())
    for job in jobs:
        add_event(
            session,
            job.id,
            "started",
            f"Attempt {job.attempt} of {job.max_attempts} started.",
            {"worker": owner},
        )
        await _set_request_status(session, job.request_id)
    await session.commit()
    return jobs


async def renew_lease(
    session: AsyncSession, job_id: uuid.UUID, *, owner: str, lease_seconds: int
) -> tuple[bool, bool]:
    """Extend the lease. Returns (still ours, cancellation requested). Commits."""
    result = await session.execute(
        update(CollectionJob)
        .where(
            CollectionJob.id == job_id,
            CollectionJob.lease_owner == owner,
            CollectionJob.status == "running",
        )
        .values(lease_expires_at=func.now() + timedelta(seconds=lease_seconds))
        .returning(CollectionJob.cancel_requested_at)
        .execution_options(synchronize_session=False)
    )
    row = result.first()
    await session.commit()
    if row is None:
        return False, False
    return True, row[0] is not None


def retry_delay(attempt: int, settings: CollectionSettings, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(max(retry_after, 0.5), settings.retry_max_seconds)
    delay = settings.retry_base_seconds * float(2 ** max(0, attempt - 1))
    return min(delay, settings.retry_max_seconds) * random.uniform(0.8, 1.2)  # noqa: S311 - jitter


def finish(
    session: AsyncSession,
    job: CollectionJob,
    status: str,
    message: str,
    *,
    outcome: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    job.status = status
    job.finished_at = utcnow()
    job.lease_owner = None
    job.lease_expires_at = None
    if outcome is not None:
        job.outcome = outcome
    if error is not None:
        job.error = error
    add_event(session, job.id, status, message, error or outcome)


def fail_or_retry(
    session: AsyncSession,
    job: CollectionJob,
    error: ProviderError,
    settings: CollectionSettings,
    *,
    now: datetime | None = None,
) -> str:
    """Record ``error``; reschedule when it is retryable and attempts remain."""
    details = error.as_dict()
    job.error = details
    if error.retryable and job.attempt < job.max_attempts:
        delay = retry_delay(job.attempt, settings, error.retry_after)
        job.status = "queued"
        job.scheduled_at = (now or utcnow()) + timedelta(seconds=delay)
        job.lease_owner = None
        job.lease_expires_at = None
        add_event(
            session,
            job.id,
            "retry_scheduled",
            f"{error.message} Trying again in {delay:.0f} s "
            f"(attempt {job.attempt + 1} of {job.max_attempts}).",
            details,
        )
        return "retry"
    reason = error.message
    if error.retryable:
        reason += f" No attempts left ({job.attempt} of {job.max_attempts})."
    finish(session, job, "failed", reason, error=details)
    return "failed"


async def recover_expired_leases(session: AsyncSession, settings: CollectionSettings) -> int:
    """Jobs whose worker stopped renewing its lease go back to the queue. Commits."""
    expired = list(
        (
            await session.execute(
                select(CollectionJob)
                .where(
                    CollectionJob.status == "running", CollectionJob.lease_expires_at < func.now()
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for job in expired:
        fail_or_retry(session, job, WorkerLost(), settings)
        await _set_request_status(session, job.request_id)
    await session.commit()
    return len(expired)


async def _set_request_status(session: AsyncSession, request_id: uuid.UUID) -> None:
    await session.flush()
    statuses = [
        row[0]
        for row in (
            await session.execute(
                select(CollectionJob.status).where(CollectionJob.request_id == request_id)
            )
        ).all()
    ]
    request = await session.get(CollectionRequest, request_id)
    if request is None:
        return
    status = request_status(statuses)
    if status != request.status:
        request.status = status
        request.finished_at = (
            utcnow() if status in ("completed", "partial", "failed", "cancelled") else None
        )


async def refresh_request_status(session: AsyncSession, request_id: uuid.UUID) -> None:
    await _set_request_status(session, request_id)


def request_status(statuses: list[str]) -> str:
    """The state of a request, from the states of its jobs."""
    if not statuses:
        return "completed"
    if any(status in ("running",) for status in statuses):
        return "running"
    if any(status == "queued" for status in statuses):
        return (
            "running" if any(status in FINISHED_JOB_STATUSES for status in statuses) else "pending"
        )
    if any(status == "awaiting_approval" for status in statuses):
        return "awaiting_approval"
    finished = [status for status in statuses if status != "skipped"]
    if not finished:
        return "completed"
    if all(status == "succeeded" for status in finished):
        return "completed"
    if all(status == "cancelled" for status in finished):
        return "cancelled"
    if all(status in ("failed", "cancelled") for status in finished):
        return "failed"
    return "partial"
