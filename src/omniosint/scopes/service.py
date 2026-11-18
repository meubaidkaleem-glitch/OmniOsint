"""Scopes in the database: create, list, change rules, revoke. Every change is audited.

Creating a scope is a statement by the user that written authorisation exists
for the listed targets; the scope records who gave that authorisation and the
user who recorded it. Scopes are never deleted, only revoked, so that the
authority behind past operations stays on record.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.audit.service import Actor, RequestInfo, record
from omniosint.core.errors import Conflict, NotFound, ValidationFailed
from omniosint.core.timeutil import ensure_utc, isoformat, utcnow
from omniosint.database.models import Scope, ScopeRule
from omniosint.database.models.scope import RULE_KINDS, SCOPE_MODES
from omniosint.scopes.manager import RuleView, ScopeView
from omniosint.scopes.rules import normalize_rule

MAX_VALIDITY = timedelta(days=366)
MAX_RULES = 500


@dataclass(frozen=True, slots=True)
class RuleInput:
    kind: str
    value: str
    is_exclusion: bool = False
    ports: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class ScopeInput:
    name: str
    mode: str
    authorized_by: str
    valid_until: datetime
    authorization_confirmed: bool
    valid_from: datetime | None = None
    description: str | None = None
    authorization_reference: str | None = None
    authorization_note: str | None = None
    rules: tuple[RuleInput, ...] = ()


def _field(field: str, message: str) -> ValidationFailed:
    return ValidationFailed(message, details=[{"field": field, "message": message}])


def _restrictions(rule: RuleInput) -> dict[str, Any]:
    if rule.ports is None:
        return {}
    ports = sorted(set(rule.ports))
    if not ports or any(not 1 <= port <= 65535 for port in ports):
        raise _field("ports", "Ports must be between 1 and 65535.")
    return {"ports": ports}


def view_of(scope: Scope, rules: Sequence[ScopeRule]) -> ScopeView:
    return ScopeView(
        id=scope.id,
        name=scope.name,
        mode=scope.mode,
        valid_from=scope.valid_from,
        valid_until=scope.valid_until,
        approved_at=scope.approved_at,
        revoked_at=scope.revoked_at,
        rules=tuple(
            RuleView(rule.id, rule.kind, rule.value, rule.is_exclusion, dict(rule.restrictions))
            for rule in rules
        ),
    )


async def get_scope(session: AsyncSession, scope_id: uuid.UUID) -> tuple[Scope, list[ScopeRule]]:
    scope = await session.get(Scope, scope_id)
    if scope is None:
        raise NotFound("The scope was not found.")
    rules = list(
        (
            await session.execute(
                select(ScopeRule)
                .where(ScopeRule.scope_id == scope_id)
                .order_by(ScopeRule.is_exclusion.desc(), ScopeRule.kind, ScopeRule.value)
            )
        ).scalars()
    )
    return scope, rules


async def load_view(session: AsyncSession, scope_id: uuid.UUID) -> ScopeView:
    scope, rules = await get_scope(session, scope_id)
    return view_of(scope, rules)


async def list_scopes(session: AsyncSession, *, include_revoked: bool = True) -> list[Scope]:
    query = select(Scope).order_by(Scope.created_at.desc())
    if not include_revoked:
        query = query.where(Scope.revoked_at.is_(None))
    return list((await session.execute(query)).scalars())


def _scope_status(scope: Scope, now: datetime) -> str:
    if scope.revoked_at is not None:
        return "revoked"
    if scope.approved_at is None:
        return "not_approved"
    if now < scope.valid_from:
        return "not_yet_valid"
    if now >= scope.valid_until:
        return "expired"
    return "active"


def scope_status(scope: Scope) -> str:
    return _scope_status(scope, utcnow())


async def create_scope(
    session: AsyncSession, data: ScopeInput, *, actor: Actor, request: RequestInfo | None = None
) -> Scope:
    if not data.authorization_confirmed:
        raise _field(
            "authorization_confirmed",
            "Confirm that written authorisation exists for every target in this scope.",
        )
    name = " ".join(data.name.split())
    if not 3 <= len(name) <= 128:
        raise _field("name", "The name must be 3 to 128 characters.")
    if data.mode not in SCOPE_MODES:
        raise _field("mode", f"The mode must be one of: {', '.join(SCOPE_MODES)}.")
    authorized_by = data.authorized_by.strip()
    if not 2 <= len(authorized_by) <= 256:
        raise _field("authorized_by", "Say who gave the authorisation (2 to 256 characters).")
    now = utcnow()
    valid_from = ensure_utc(data.valid_from) if data.valid_from else now
    valid_until = ensure_utc(data.valid_until)
    if valid_until <= valid_from:
        raise _field("valid_until", "The end of validity must be after its start.")
    if valid_until <= now:
        raise _field("valid_until", "The end of validity must be in the future.")
    if valid_until - valid_from > MAX_VALIDITY:
        raise _field(
            "valid_until", "A scope can be valid for at most a year; create a new one after."
        )
    if len(data.rules) > MAX_RULES:
        raise _field("rules", f"A scope can have at most {MAX_RULES} rules.")
    scope = Scope(
        name=name,
        description=(data.description or "").strip() or None,
        mode=data.mode,
        authorized_by=authorized_by,
        authorization_reference=(data.authorization_reference or "").strip() or None,
        authorization_note=(data.authorization_note or "").strip() or None,
        valid_from=valid_from,
        valid_until=valid_until,
        created_by=actor.user_id,
        approved_by=actor.user_id,
        approved_at=now,
    )
    session.add(scope)
    await session.flush()
    added = [_new_rule(scope.id, rule) for rule in data.rules]
    session.add_all(added)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise Conflict("The same rule is listed twice.") from error
    record(
        session,
        action="scope.created",
        actor=actor,
        target_type="scope",
        target_id=scope.id,
        request=request,
        details={
            "name": name,
            "mode": data.mode,
            "authorized_by": authorized_by,
            "authorization_reference": scope.authorization_reference,
            "valid_from": isoformat(valid_from),
            "valid_until": isoformat(valid_until),
            "rules": [_describe(rule) for rule in added],
        },
    )
    await session.commit()
    return scope


def _new_rule(scope_id: uuid.UUID, rule: RuleInput) -> ScopeRule:
    if rule.kind not in RULE_KINDS:
        raise _field("kind", f"The rule kind must be one of: {', '.join(RULE_KINDS)}.")
    return ScopeRule(
        scope_id=scope_id,
        kind=rule.kind,
        value=normalize_rule(rule.kind, rule.value),
        is_exclusion=rule.is_exclusion,
        restrictions=_restrictions(rule),
    )


def _describe(rule: ScopeRule) -> dict[str, Any]:
    return {
        "kind": rule.kind,
        "value": rule.value,
        "exclusion": rule.is_exclusion,
        "restrictions": rule.restrictions,
    }


def _require_open(scope: Scope) -> None:
    if scope.revoked_at is not None:
        raise Conflict("The scope has been revoked; create a new one.")


async def add_rule(
    session: AsyncSession,
    scope_id: uuid.UUID,
    rule: RuleInput,
    *,
    actor: Actor,
    request: RequestInfo | None = None,
) -> ScopeRule:
    scope, rules = await get_scope(session, scope_id)
    _require_open(scope)
    if len(rules) >= MAX_RULES:
        raise _field("rules", f"A scope can have at most {MAX_RULES} rules.")
    new = _new_rule(scope.id, rule)
    session.add(new)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise Conflict("The scope already has this rule.") from error
    record(
        session,
        action="scope.rule_added",
        actor=actor,
        target_type="scope",
        target_id=scope.id,
        request=request,
        details=_describe(new),
    )
    await session.commit()
    return new


async def remove_rule(
    session: AsyncSession,
    scope_id: uuid.UUID,
    rule_id: uuid.UUID,
    *,
    actor: Actor,
    request: RequestInfo | None = None,
) -> None:
    scope, _rules = await get_scope(session, scope_id)
    _require_open(scope)
    rule = await session.get(ScopeRule, rule_id)
    if rule is None or rule.scope_id != scope.id:
        raise NotFound("The rule was not found.")
    details = _describe(rule)
    await session.delete(rule)
    record(
        session,
        action="scope.rule_removed",
        actor=actor,
        target_type="scope",
        target_id=scope.id,
        request=request,
        details=details,
    )
    await session.commit()


async def revoke_scope(
    session: AsyncSession,
    scope_id: uuid.UUID,
    reason: str,
    *,
    actor: Actor,
    request: RequestInfo | None = None,
) -> Scope:
    scope, _rules = await get_scope(session, scope_id)
    _require_open(scope)
    text = reason.strip()
    if not 3 <= len(text) <= 512:
        raise _field("reason", "Give a reason of 3 to 512 characters.")
    scope.revoked_at = utcnow()
    scope.revoked_by = actor.user_id
    scope.revoke_reason = text
    record(
        session,
        action="scope.revoked",
        actor=actor,
        target_type="scope",
        target_id=scope.id,
        request=request,
        details={"reason": text},
    )
    await session.commit()
    return scope
