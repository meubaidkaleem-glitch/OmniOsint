"""Runs leased collection jobs.

For one job, in order:

1. stop if cancellation was requested; for an active operation, ask the scope
   manager again (a scope can expire or be revoked after planning);
2. reuse a fresh earlier result if there is one;
3. call the provider through the manager, renewing the lease meanwhile;
4. store each raw page in the object store (encrypted, content-addressed);
5. in one transaction: raw object records, results, evidence for every
   observation, usage, the job's outcome and its history.

A failure is recorded as itself (timeout, quota, malformed data...). A
malformed response keeps its raw bytes so it can be inspected.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.audit.service import SYSTEM_ACTOR, record
from omniosint.collection import queue
from omniosint.collection.planner import find_fresh_result
from omniosint.core.config import Settings
from omniosint.core.timeutil import isoformat, utcnow
from omniosint.database.engine import Database
from omniosint.database.models import (
    CollectionJob,
    CollectionResult,
    Evidence,
    ProviderUsage,
    RawObject,
)
from omniosint.evidence.objectstore import ENCRYPTION, ObjectStore
from omniosint.evidence.service import Provenance, record_observation
from omniosint.indicators.types import EntityType, IndicatorType
from omniosint.providers.base import Indicator, Operation
from omniosint.providers.errors import (
    InternalCollectionError,
    ProviderError,
    ProviderNotAvailable,
    ScopeDenied,
)
from omniosint.providers.manager import CallResult, ProviderManager
from omniosint.scopes.manager import evaluate
from omniosint.scopes.rules import target_for
from omniosint.scopes.service import load_view

log = structlog.get_logger(__name__)


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def indicator_of(job: CollectionJob) -> Indicator:
    stored = job.options.get("indicator", {})
    entity_type = stored.get("entity_type")
    return Indicator(
        type=IndicatorType(job.indicator_type),
        value=job.indicator_value,
        display=stored.get("display") or job.indicator_value,
        entity_type=EntityType(entity_type) if entity_type else None,
        details=stored.get("details") or {},
    )


class Collector:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        manager: ProviderManager,
        store: ObjectStore,
        *,
        owner: str | None = None,
        clock: Callable[[], Any] = utcnow,
    ) -> None:
        self._db = database
        self._settings = settings
        self._collection = settings.collection
        self._manager = manager
        self._store = store
        self.owner = owner or worker_identity()
        self._clock = clock
        self._semaphore = asyncio.Semaphore(self._collection.max_concurrent_jobs)

    # ------------------------------------------------------------------ loop
    async def run_pending(self, *, limit: int | None = None) -> int:
        """Lease due jobs and run them concurrently. Returns how many ran."""
        count = limit or self._collection.max_concurrent_jobs
        async with self._db.session() as session:
            jobs = await queue.lease_jobs(
                session,
                owner=self.owner,
                lease_seconds=self._collection.job_lease_seconds,
                limit=count,
            )
        if jobs:
            await asyncio.gather(*(self._guarded(job.id) for job in jobs))
        return len(jobs)

    async def run_forever(self, stop: asyncio.Event, *, recovery_interval: float = 30.0) -> None:
        """Keep up to ``max_concurrent_jobs`` jobs running until ``stop`` is set.

        Running jobs are allowed to finish on shutdown, up to the shutdown
        timeout; jobs cut short then are recovered from their expired lease.
        """
        loop = asyncio.get_running_loop()
        running: set[asyncio.Task[None]] = set()
        next_recovery = loop.time()
        limit = self._collection.max_concurrent_jobs
        try:
            while not stop.is_set():
                if loop.time() >= next_recovery:
                    try:
                        async with self._db.session() as session:
                            recovered = await queue.recover_expired_leases(
                                session, self._collection
                            )
                        if recovered:
                            log.warning("collection.leases_recovered", jobs=recovered)
                    except Exception as error:
                        log.warning("collection.recovery_failed", error=type(error).__name__)
                    next_recovery = loop.time() + recovery_interval
                leased: list[CollectionJob] = []
                free = limit - len(running)
                if free > 0:
                    try:
                        async with self._db.session() as session:
                            leased = await queue.lease_jobs(
                                session,
                                owner=self.owner,
                                lease_seconds=self._collection.job_lease_seconds,
                                limit=free,
                            )
                    except Exception as error:
                        log.warning("collection.lease_failed", error=type(error).__name__)
                for job in leased:
                    task = asyncio.create_task(self._guarded(job.id))
                    running.add(task)
                    task.add_done_callback(running.discard)
                if leased and len(running) < limit:
                    continue  # more may be due
                waiters: set[asyncio.Future[Any]] = {asyncio.ensure_future(stop.wait())}
                waiters |= set(running)
                await asyncio.wait(
                    waiters,
                    timeout=self._collection.poll_interval_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for waiter in waiters - set(running):
                    if not waiter.done():
                        waiter.cancel()
        finally:
            if running:
                grace = self._settings.runtime.shutdown_timeout_seconds / 2
                _done, unfinished = await asyncio.wait(running, timeout=grace)
                for task in unfinished:
                    task.cancel()
                await asyncio.gather(*unfinished, return_exceptions=True)

    async def drain(self, *, max_rounds: int = 50) -> int:
        """Run until no job is due (used by the CLI and tests). Returns jobs run."""
        total = 0
        for _ in range(max_rounds):
            ran = await self.run_pending()
            if ran == 0:
                break
            total += ran
        return total

    async def _guarded(self, job_id: uuid.UUID) -> None:
        async with self._semaphore:
            try:
                await self.execute(job_id)
            except Exception:
                log.exception("collection.job_crashed", job_id=str(job_id))
                await self._record_failure(job_id, InternalCollectionError())

    # ------------------------------------------------------------------ one job
    async def execute(self, job_id: uuid.UUID) -> None:
        async with self._db.session() as session:
            job = await session.get(CollectionJob, job_id)
            if job is None or job.status != "running" or job.lease_owner != self.owner:
                return
            if job.cancel_requested_at is not None:
                queue.finish(session, job, "cancelled", "Cancelled before it started.")
                await queue.refresh_request_status(session, job.request_id)
                await session.commit()
                return
            indicator = indicator_of(job)
            if job.is_active and not await self._scope_allows(session, job, indicator):
                await session.commit()
                return
            if not job.options.get("force_refresh") and await self._reuse_cached(session, job):
                await session.commit()
                return
            await session.commit()
            attempt = job.attempt
            provider_id, capability_id = job.provider_id, job.capability
            provider_options = dict(job.options.get("provider_options") or {})

        call = asyncio.create_task(
            self._manager.call(
                provider_id,
                capability_id,
                indicator,
                options=provider_options,
                job_id=job_id,
                attempt=attempt,
                progress=lambda progress: self._progress(job_id, progress),
            )
        )
        try:
            state = await self._watch(job_id, call)
        except asyncio.CancelledError:
            # The worker itself is stopping: abandon the call; the lease will
            # expire and housekeeping puts the job back in the queue.
            call.cancel()
            raise
        if state == "cancel_requested":
            await self._mark_cancelled(job_id)
            return
        if state == "lease_lost":
            log.warning("collection.lease_lost", job_id=str(job_id), worker=self.owner)
            return
        try:
            result = call.result()
        except ProviderError as error:
            await self._record_failure(
                job_id, error, provider_id=provider_id, capability=capability_id
            )
            return
        await self._store_result(job_id, indicator, result)

    async def _watch(self, job_id: uuid.UUID, call: asyncio.Task[CallResult]) -> str:
        """Renew the lease while the call runs; stop it if the user cancels the job
        or the lease was lost. Returns "done", "cancel_requested" or "lease_lost"."""
        interval = max(1.0, self._collection.job_lease_seconds / 3)
        while not call.done():
            done, _pending = await asyncio.wait({call}, timeout=interval)
            if done:
                break
            async with self._db.session() as session:
                ours, cancel_requested = await queue.renew_lease(
                    session,
                    job_id,
                    owner=self.owner,
                    lease_seconds=self._collection.job_lease_seconds,
                )
            if not ours or cancel_requested:
                call.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await call
                return "cancel_requested" if ours else "lease_lost"
        return "done"

    async def _progress(self, job_id: uuid.UUID, progress: dict[str, Any]) -> None:
        async with self._db.session() as session:
            job = await session.get(CollectionJob, job_id)
            if job is not None and job.status == "running":
                job.progress = {**progress, "updated_at": isoformat(utcnow())}
                await session.commit()

    # ------------------------------------------------------------------ gates
    async def _scope_allows(
        self, session: AsyncSession, job: CollectionJob, indicator: Indicator
    ) -> bool:
        adapter = self._manager.registry.adapter(job.provider_id)
        capability = adapter.metadata.capability(job.capability) if adapter else None
        operation = capability.operation if capability else Operation.DISCOVERY
        scope = await load_view(session, job.scope_id) if job.scope_id else None
        decision = evaluate(
            operation, target_for(indicator.type, indicator.value), scope, now=self._clock()
        )
        record(
            session,
            action="scope.checked",
            actor=SYSTEM_ACTOR,
            outcome="success" if decision.allowed else "denied",
            target_type="collection_job",
            target_id=job.id,
            details={"when": "before_run", **decision.as_dict(), "target": indicator.value},
        )
        if decision.allowed:
            queue.add_event(session, job.id, "scope_checked", decision.reason, decision.as_dict())
            return True
        error = ScopeDenied(decision.reason, details=decision.as_dict())
        queue.finish(session, job, "failed", decision.reason, error=error.as_dict())
        await queue.refresh_request_status(session, job.request_id)
        return False

    async def _reuse_cached(self, session: AsyncSession, job: CollectionJob) -> bool:
        adapter = self._manager.registry.adapter(job.provider_id)
        capability = adapter.metadata.capability(job.capability) if adapter else None
        if capability is None or capability.cache_ttl_seconds <= 0:
            return False
        cached = await find_fresh_result(session, job.cache_key, self._clock())
        if cached is None:
            return False
        evidence_count = (
            await session.execute(
                select(func.count()).select_from(Evidence).where(Evidence.job_id == cached.job_id)
            )
        ).scalar_one()
        session.add(
            CollectionResult(
                job_id=job.id,
                provider_id=job.provider_id,
                capability=job.capability,
                page=1,
                raw_sha256=cached.raw_sha256,
                raw_size=cached.raw_size,
                content_type=cached.content_type,
                status_code=cached.status_code,
                normalized=cached.normalized,
                item_count=cached.item_count,
                from_cache=True,
                reused_result_id=cached.id,
                cache_key=job.cache_key,
                is_simulated=cached.is_simulated,
                received_at=cached.received_at,
                expires_at=None,
            )
        )
        await self._usage(session, job.provider_id, job.capability, cache_hit=True)
        queue.finish(
            session,
            job,
            "succeeded",
            "Reused a fresh result from an earlier job; the provider was not called.",
            outcome={
                "from_cache": True,
                "reused_job_id": str(cached.job_id),
                "items": cached.item_count,
                "evidence": evidence_count,
                "fresh_until": isoformat(cached.expires_at),
            },
        )
        await queue.refresh_request_status(session, job.request_id)
        return True

    # ------------------------------------------------------------------ outcomes
    async def _usage(
        self,
        session: AsyncSession,
        provider_id: str,
        capability: str,
        *,
        failed: bool = False,
        cache_hit: bool = False,
        credits: float = 0.0,
    ) -> None:
        if self._manager.registry.adapter(provider_id) is None:
            return
        statement = insert(ProviderUsage).values(
            provider_id=provider_id,
            day=self._clock().date(),
            capability=capability,
            requests=0 if cache_hit else 1,
            failures=1 if failed else 0,
            cache_hits=1 if cache_hit else 0,
            credits=Decimal(str(credits)),
        )
        excluded = statement.excluded
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["provider_id", "day", "capability"],
                set_={
                    "requests": ProviderUsage.requests + excluded.requests,
                    "failures": ProviderUsage.failures + excluded.failures,
                    "cache_hits": ProviderUsage.cache_hits + excluded.cache_hits,
                    "credits": ProviderUsage.credits + excluded.credits,
                },
            )
        )

    async def _record_failure(
        self,
        job_id: uuid.UUID,
        error: ProviderError,
        *,
        provider_id: str | None = None,
        capability: str | None = None,
    ) -> None:
        async with self._db.session() as session:
            job = await session.get(CollectionJob, job_id)
            if job is None or job.status != "running":
                return
            if provider_id and capability and not isinstance(error, ProviderNotAvailable):
                await self._usage(session, provider_id, capability, failed=True)
            queue.fail_or_retry(session, job, error, self._collection)
            await queue.refresh_request_status(session, job.request_id)
            await session.commit()

    async def _mark_cancelled(self, job_id: uuid.UUID) -> None:
        async with self._db.session() as session:
            job = await session.get(CollectionJob, job_id)
            if job is not None and job.status == "running":
                queue.finish(session, job, "cancelled", "Cancelled while running, as requested.")
                await queue.refresh_request_status(session, job.request_id)
                await session.commit()

    async def _store_result(
        self, job_id: uuid.UUID, indicator: Indicator, result: CallResult
    ) -> None:
        created: list[str] = []
        try:
            stored = []
            for page in result.raw.pages:
                item = self._store.put(page.content)
                if item.created:
                    created.append(item.sha256)
                stored.append(item)
            async with self._db.session() as session:
                job = await session.get(CollectionJob, job_id)
                if job is None or job.status != "running" or job.lease_owner != self.owner:
                    return
                await self._persist(session, job, result, stored)
                await session.commit()
        except Exception:
            for sha256 in created:
                self._store.delete(sha256)
            raise

    async def _persist(
        self, session: AsyncSession, job: CollectionJob, result: CallResult, stored: list[Any]
    ) -> None:
        adapter = self._manager.registry.adapter(job.provider_id)
        assert adapter is not None
        metadata = adapter.metadata
        simulated = metadata.simulated
        now = self._clock()
        retain_until = now + timedelta(days=self._collection.raw_retention_days)
        ttl = result.capability.cache_ttl_seconds
        valid = result.normalization_error is None
        observations = result.observations or ()
        evidence_count = 0
        for number, (page, item) in enumerate(zip(result.raw.pages, stored, strict=True), start=1):
            raw_row = insert(RawObject).values(
                sha256=item.sha256,
                size=item.size,
                content_type=page.content_type[:128],
                encryption=ENCRYPTION,
                retain_until=retain_until,
            )
            await session.execute(
                raw_row.on_conflict_do_update(
                    index_elements=[RawObject.sha256],
                    set_={
                        "retain_until": func.greatest(
                            RawObject.retain_until, raw_row.excluded.retain_until
                        )
                    },
                )
            )
            page_observations = [obs for obs in observations if obs.page == number]
            row = CollectionResult(
                job_id=job.id,
                provider_id=job.provider_id,
                capability=job.capability,
                page=number,
                raw_sha256=item.sha256,
                raw_size=item.size,
                content_type=page.content_type[:128],
                status_code=page.status_code,
                normalized=[obs.model_dump(mode="json") for obs in page_observations]
                if valid
                else None,
                item_count=len(page_observations),
                normalization_error=None if valid else result.normalization_error.as_dict(),  # type: ignore[union-attr]
                from_cache=False,
                cache_key=job.cache_key,
                is_simulated=simulated,
                received_at=page.received_at,
                expires_at=page.received_at + timedelta(seconds=ttl) if valid and ttl > 0 else None,
            )
            session.add(row)
            await session.flush()
            if valid:
                provenance = Provenance(
                    source_id=metadata.id,
                    provider_id=metadata.id,
                    adapter_version=metadata.version,
                    capability=job.capability,
                    job_id=job.id,
                    result_id=row.id,
                    raw_sha256=item.sha256,
                    collected_at=page.received_at,
                    simulated=simulated,
                )
                for observation in page_observations:
                    await record_observation(session, observation, provenance)
                    evidence_count += 1
        credits = result.capability.cost.credits_per_call or 0.0
        await self._usage(
            session, job.provider_id, job.capability, failed=not valid, credits=credits
        )
        outcome = {
            "from_cache": False,
            "pages": len(result.raw.pages),
            "items": len(observations),
            "evidence": evidence_count,
            "truncated": result.truncated,
            "truncation_reason": result.truncation_reason,
            "duration_ms": result.duration_ms,
            "rate_limit_wait_s": result.rate_limit_wait_s,
            "simulated": simulated,
        }
        job.outcome = outcome
        if not valid:
            error = result.normalization_error
            assert error is not None
            message = f"{error.message} The raw response was kept for inspection."
            queue.finish(session, job, "failed", message, outcome=outcome, error=error.as_dict())
        else:
            message = (
                f"Collected {len(observations)} observation(s) on {len(result.raw.pages)} page(s)."
            )
            if result.truncated:
                message += f" Incomplete: {result.truncation_reason}"
            queue.finish(session, job, "succeeded", message, outcome=outcome)
        await queue.refresh_request_status(session, job.request_id)
