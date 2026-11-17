"""Audit trail: recording and querying security-relevant actions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.core.errors import ValidationFailed
from omniosint.core.logging import redact
from omniosint.core.pagination import Page, clamp_limit, decode_cursor, encode_cursor
from omniosint.core.timeutil import ensure_utc, isoformat
from omniosint.database.models import AuditEvent

Outcome = Literal["success", "failure", "denied"]


@dataclass(frozen=True, slots=True)
class RequestInfo:
    """Where a request came from, as far as the server can tell."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: uuid.UUID | None
    label: str


SYSTEM_ACTOR = Actor(user_id=None, label="system")
CLI_ACTOR = Actor(user_id=None, label="cli")
ANONYMOUS_ACTOR = Actor(user_id=None, label="anonymous")


def _clip(value: str | None, length: int) -> str | None:
    return value[:length] if value else value


def record(
    session: AsyncSession,
    *,
    action: str,
    actor: Actor,
    outcome: Outcome = "success",
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    request: RequestInfo | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction.

    The event is committed together with the change it describes. ``action`` is
    a stable dotted code such as ``auth.login.failure``; its first segment is
    the category. ``details`` is masked for credential-like keys as a second
    line of defence, but callers must not pass secrets in the first place.
    """
    request = request or RequestInfo()
    event = AuditEvent(
        category=action.split(".", 1)[0][:32],
        action=action[:96],
        outcome=outcome,
        actor_user_id=actor.user_id,
        actor_label=actor.label[:128],
        target_type=_clip(target_type, 64),
        target_id=_clip(str(target_id), 128) if target_id is not None else None,
        ip_address=_clip(request.ip_address, 64),
        user_agent=_clip(request.user_agent, 255),
        request_id=_clip(request.request_id, 64),
        details=redact(details or {}),
    )
    session.add(event)
    return event


async def list_events(
    session: AsyncSession,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    category: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Page[AuditEvent]:
    """Newest first, keyset-paginated on ``(occurred_at, id)``."""
    page_size = clamp_limit(limit)
    query = select(AuditEvent)
    if category:
        query = query.where(AuditEvent.category == category)
    if action:
        query = query.where(AuditEvent.action == action)
    if outcome:
        query = query.where(AuditEvent.outcome == outcome)
    if actor_user_id is not None:
        query = query.where(AuditEvent.actor_user_id == actor_user_id)
    if since is not None:
        query = query.where(AuditEvent.occurred_at >= ensure_utc(since))
    if until is not None:
        query = query.where(AuditEvent.occurred_at < ensure_utc(until))

    if cursor:
        raw_time, raw_id = decode_cursor(cursor, parts=2)
        try:
            cursor_time = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
            cursor_id = uuid.UUID(str(raw_id))
        except ValueError as exc:
            raise ValidationFailed(
                "The cursor is not valid.",
                details=[{"field": "cursor", "message": "Invalid cursor."}],
            ) from exc
        query = query.where(
            or_(
                AuditEvent.occurred_at < cursor_time,
                and_(AuditEvent.occurred_at == cursor_time, AuditEvent.id < cursor_id),
            )
        )

    query = query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(
        page_size + 1
    )
    rows = list((await session.execute(query)).scalars())
    has_more = len(rows) > page_size
    items = rows[:page_size]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor([isoformat(last.occurred_at), str(last.id)])
    return Page(items=items, next_cursor=next_cursor)
