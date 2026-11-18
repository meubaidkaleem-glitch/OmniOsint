"""The scope manager: the single gate for active operations.

A passive lookup asks a third party and never contacts the target, so it
needs no scope. Any other operation runs only when an approved, unrevoked
scope, valid at that moment, permits that kind of operation, covers the whole
target and excludes no part of it. Exclusions always win. The decision is
evaluated when a job is planned and again immediately before it runs.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from omniosint.providers.base import Operation
from omniosint.scopes.rules import Target, covers, touches

MODE_OPERATIONS: dict[str, frozenset[Operation]] = {
    "passive": frozenset(),
    "authorized_discovery": frozenset({Operation.DISCOVERY}),
    "active_assessment": frozenset({Operation.DISCOVERY, Operation.ASSESSMENT}),
}


@dataclass(frozen=True, slots=True)
class RuleView:
    id: uuid.UUID
    kind: str
    value: str
    is_exclusion: bool
    restrictions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScopeView:
    id: uuid.UUID
    name: str
    mode: str
    valid_from: datetime
    valid_until: datetime
    approved_at: datetime | None
    revoked_at: datetime | None
    rules: tuple[RuleView, ...]


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    allowed: bool
    code: str
    reason: str
    scope_id: uuid.UUID | None = None
    matched_rules: tuple[uuid.UUID, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "scope_id": str(self.scope_id) if self.scope_id else None,
            "matched_rules": [str(rule) for rule in self.matched_rules],
        }


def _deny(
    code: str, reason: str, scope: ScopeView | None = None, rules: Sequence[uuid.UUID] = ()
) -> ScopeDecision:
    return ScopeDecision(False, code, reason, scope.id if scope else None, tuple(rules))


def evaluate(
    operation: Operation,
    target: Target | None,
    scope: ScopeView | None,
    *,
    now: datetime,
    ports: Sequence[int] = (),
) -> ScopeDecision:
    if operation is Operation.LOOKUP:
        return ScopeDecision(
            True,
            "passive_operation",
            "Passive lookup: third-party sources are asked; the target is not contacted.",
        )
    if scope is None:
        return _deny(
            "scope_required", "This operation contacts the target and needs an approved scope."
        )
    if scope.revoked_at is not None:
        return _deny("scope_revoked", f"The scope {scope.name!r} has been revoked.", scope)
    if scope.approved_at is None:
        return _deny(
            "scope_not_approved", f"The scope {scope.name!r} has not been approved.", scope
        )
    if now < scope.valid_from:
        return _deny("scope_not_yet_valid", f"The scope {scope.name!r} is not valid yet.", scope)
    if now >= scope.valid_until:
        return _deny("scope_expired", f"The scope {scope.name!r} has expired.", scope)
    if operation not in MODE_OPERATIONS.get(scope.mode, frozenset()):
        return _deny(
            "operation_not_permitted",
            f"A {scope.mode.replace('_', ' ')} scope does not permit {operation.value} operations.",
            scope,
        )
    if target is None:
        return _deny(
            "target_not_addressable", "This indicator does not name a network target.", scope
        )
    excluded = [
        rule.id
        for rule in scope.rules
        if rule.is_exclusion and touches(rule.kind, rule.value, target)
    ]
    if excluded:
        return _deny(
            "target_excluded", f"{target.describe()} is excluded by the scope.", scope, excluded
        )
    matched = [
        rule
        for rule in scope.rules
        if not rule.is_exclusion and covers(rule.kind, rule.value, target)
    ]
    if not matched:
        return _deny(
            "target_not_in_scope", f"{target.describe()} is not covered by the scope.", scope
        )
    if ports:
        allowed_ports: set[int] = set()
        unrestricted = False
        for rule in matched:
            listed = rule.restrictions.get("ports")
            if listed is None:
                unrestricted = True
            else:
                allowed_ports.update(int(port) for port in listed)
        if not unrestricted and not set(ports) <= allowed_ports:
            return _deny(
                "port_not_permitted",
                f"Ports {sorted(set(ports) - allowed_ports)} are not permitted by the scope.",
                scope,
                [rule.id for rule in matched],
            )
    return ScopeDecision(
        True,
        "allowed",
        f"Covered by the scope {scope.name!r}.",
        scope.id,
        tuple(rule.id for rule in matched),
    )
