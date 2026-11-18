"""Periodic maintenance run by the worker."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.core.timeutil import utcnow
from omniosint.database.models import RawObject, UserSession
from omniosint.evidence.objectstore import ObjectStore


async def purge_sessions(session: AsyncSession, retention_days: int) -> int:
    """Delete sessions that ended more than ``retention_days`` ago.

    Ended sessions are kept for a while so that the audit trail can still be
    matched to a session record, then removed.
    """
    cutoff = utcnow() - timedelta(days=retention_days)
    result = await session.execute(
        delete(UserSession).where(
            or_(
                UserSession.expires_at < cutoff,
                UserSession.revoked_at < cutoff,
            )
        )
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_raw_objects(session: AsyncSession, store: ObjectStore, *, batch: int = 500) -> int:
    """Delete raw responses whose retention period has passed.

    The bytes and their record go; results and evidence keep the hash, so the
    integrity of what was derived from them can still be stated.
    """
    expired = list(
        (
            await session.execute(
                select(RawObject.sha256)
                .where(RawObject.retain_until < utcnow())
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for sha256 in expired:
        store.delete(sha256)
    if expired:
        await session.execute(delete(RawObject).where(RawObject.sha256.in_(expired)))
    await session.commit()
    return len(expired)
