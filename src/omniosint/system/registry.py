"""Registry of running OmniOSINT processes.

Each API and worker process records itself and refreshes a heartbeat. Health
checks read the registry to tell whether a worker is alive, without needing
any channel other than the database.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint import __version__
from omniosint.core.logging import get_logger
from omniosint.core.timeutil import utcnow
from omniosint.database.engine import Database
from omniosint.database.models import ServiceInstance

log = get_logger(__name__)

_STOPPED_RETENTION = timedelta(days=7)


async def register(session: AsyncSession, service: str) -> uuid.UUID:
    instance = ServiceInstance(service=service, pid=os.getpid(), version=__version__)
    session.add(instance)
    await session.commit()
    return instance.id


async def heartbeat(session: AsyncSession, instance_id: uuid.UUID) -> None:
    await session.execute(
        update(ServiceInstance)
        .where(ServiceInstance.id == instance_id)
        .values(last_heartbeat_at=utcnow(), stopped_at=None)
    )
    await session.commit()


async def mark_stopped(session: AsyncSession, instance_id: uuid.UUID) -> None:
    await session.execute(
        update(ServiceInstance)
        .where(ServiceInstance.id == instance_id, ServiceInstance.stopped_at.is_(None))
        .values(stopped_at=utcnow())
    )
    await session.commit()


async def latest(session: AsyncSession, service: str) -> ServiceInstance | None:
    """Most recently seen instance of ``service`` that has not stopped."""
    result = await session.execute(
        select(ServiceInstance)
        .where(ServiceInstance.service == service, ServiceInstance.stopped_at.is_(None))
        .order_by(ServiceInstance.last_heartbeat_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def reap_stale(session: AsyncSession, silent_for: timedelta) -> int:
    """Mark instances that stopped heartbeating as stopped; drop old records."""
    now = utcnow()
    marked = await session.execute(
        update(ServiceInstance)
        .where(
            ServiceInstance.stopped_at.is_(None),
            ServiceInstance.last_heartbeat_at < now - silent_for,
        )
        .values(stopped_at=now)
    )
    await session.execute(
        delete(ServiceInstance).where(
            ServiceInstance.stopped_at.is_not(None),
            ServiceInstance.stopped_at < now - _STOPPED_RETENTION,
        )
    )
    await session.commit()
    return int(getattr(marked, "rowcount", 0) or 0)


class ServiceHeartbeat:
    """Keeps this process's registry record fresh.

    Database errors are logged and retried: a database outage must not take the
    process down, and the record is re-created once the database returns.
    """

    def __init__(self, db: Database, service: str, interval_seconds: float) -> None:
        self._db = db
        self._service = service
        self._interval = interval_seconds
        self._instance_id: uuid.UUID | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def instance_id(self) -> uuid.UUID | None:
        return self._instance_id

    async def beat(self) -> bool:
        """Register or refresh once. Returns whether it succeeded."""
        try:
            async with self._db.session() as session:
                if self._instance_id is None:
                    self._instance_id = await register(session, self._service)
                else:
                    await heartbeat(session, self._instance_id)
            return True
        except Exception as exc:
            log.warning("heartbeat.failed", service=self._service, error=type(exc).__name__)
            return False

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self.beat()

    async def start(self) -> None:
        await self.beat()
        self._task = asyncio.create_task(self._run(), name=f"{self._service}-heartbeat")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._instance_id is None:
            return
        try:
            async with self._db.session() as session:
                await mark_stopped(session, self._instance_id)
        except Exception as exc:
            log.warning("heartbeat.stop_failed", service=self._service, error=type(exc).__name__)
