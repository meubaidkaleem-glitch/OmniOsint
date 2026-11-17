"""Periodic maintenance run by the worker."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.core.timeutil import utcnow
from omniosint.database.models import UserSession


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
