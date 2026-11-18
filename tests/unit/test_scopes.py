"""Scope rules and the scope manager (no database)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from omniosint.core.errors import ValidationFailed
from omniosint.indicators.types import IndicatorType
from omniosint.providers.base import Operation
from omniosint.scopes.manager import RuleView, ScopeView, evaluate
from omniosint.scopes.rules import covers, normalize_rule, target_for, touches

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def scope(*rules: RuleView, mode: str = "authorized_discovery", **overrides: object) -> ScopeView:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Engagement",
        "mode": mode,
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "approved_at": NOW - timedelta(days=1),
        "revoked_at": None,
        "rules": rules,
    }
    values.update(overrides)
    return ScopeView(**values)  # type: ignore[arg-type]


def rule(
    kind: str, value: str, *, exclusion: bool = False, ports: list[int] | None = None
) -> RuleView:
    restrictions = {"ports": ports} if ports is not None else {}
    return RuleView(uuid.uuid4(), kind, normalize_rule(kind, value), exclusion, restrictions)


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("domain", "Example.COM.", "example.com"),
        ("wildcard", "*.Example.com", "*.example.com"),
        ("ip", "2001:DB8::1", "2001:db8::1"),
        ("cidr", "10.0.0.5/24", "10.0.0.0/24"),
        ("url_prefix", "HTTPS://Example.com/app", "https://example.com/app"),
    ],
)
def test_rules_are_normalised(kind: str, value: str, expected: str) -> None:
    assert normalize_rule(kind, value) == expected


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("domain", "not a domain"),
        ("domain", "localhost"),
        ("wildcard", "example.com"),
        ("ip", "300.1.1.1"),
        ("cidr", "0.0.0.0/0"),
        ("cidr", "10.0.0.0/7"),
        ("cidr", "2001::/12"),
        ("url_prefix", "example.com/app"),
        ("port", "80"),
    ],
)
def test_invalid_or_too_broad_rules_are_refused(kind: str, value: str) -> None:
    with pytest.raises(ValidationFailed):
        normalize_rule(kind, value)


def test_domain_rules_are_exact_and_wildcards_exclude_the_apex() -> None:
    apex = target_for(IndicatorType.DOMAIN, "example.com")
    sub = target_for(IndicatorType.DOMAIN, "www.example.com")
    assert apex is not None and sub is not None
    assert covers("domain", "example.com", apex) and not covers("domain", "example.com", sub)
    assert covers("wildcard", "*.example.com", sub) and not covers(
        "wildcard", "*.example.com", apex
    )
    # An excluded domain excludes its subdomains too.
    assert touches("domain", "example.com", sub)


def test_ranges_must_be_wholly_inside_and_exclusions_need_only_touch() -> None:
    inside = target_for(IndicatorType.IP_RANGE, "10.0.0.0/25")
    straddling = target_for(IndicatorType.IP_RANGE, "10.0.0.0/23")
    span = target_for(IndicatorType.IP_RANGE, "10.0.0.1-10.0.0.40")
    assert inside and straddling and span
    assert covers("cidr", "10.0.0.0/24", inside)
    assert not covers("cidr", "10.0.0.0/24", straddling)
    assert covers("cidr", "10.0.0.0/24", span)
    assert touches("ip", "10.0.0.7", span)
    assert touches("cidr", "10.0.1.0/28", straddling)
    assert not touches("cidr", "10.0.1.0/28", inside)


def test_url_prefix_respects_path_boundaries() -> None:
    target = target_for(IndicatorType.URL, "https://example.com/application")
    assert target is not None
    assert not covers("url_prefix", "https://example.com/app", target)
    assert covers("url_prefix", "https://example.com/", target)


def test_passive_lookups_need_no_scope() -> None:
    decision = evaluate(Operation.LOOKUP, None, None, now=NOW)
    assert decision.allowed and decision.code == "passive_operation"


@pytest.mark.parametrize(
    ("view", "code"),
    [
        (None, "scope_required"),
        (scope(rule("ip", "198.51.100.7"), revoked_at=NOW), "scope_revoked"),
        (scope(rule("ip", "198.51.100.7"), approved_at=None), "scope_not_approved"),
        (
            scope(rule("ip", "198.51.100.7"), valid_from=NOW + timedelta(hours=1)),
            "scope_not_yet_valid",
        ),
        (scope(rule("ip", "198.51.100.7"), valid_until=NOW), "scope_expired"),
        (scope(rule("ip", "198.51.100.7"), mode="passive"), "operation_not_permitted"),
        (scope(rule("ip", "198.51.100.8")), "target_not_in_scope"),
        (
            scope(rule("cidr", "198.51.100.0/24"), rule("ip", "198.51.100.7", exclusion=True)),
            "target_excluded",
        ),
    ],
)
def test_active_operations_are_denied_with_a_reason(view: ScopeView | None, code: str) -> None:
    target = target_for(IndicatorType.IPV4, "198.51.100.7")
    decision = evaluate(Operation.DISCOVERY, target, view, now=NOW)
    assert not decision.allowed and decision.code == code and decision.reason


def test_assessment_needs_an_assessment_scope() -> None:
    target = target_for(IndicatorType.IPV4, "198.51.100.7")
    discovery = scope(rule("ip", "198.51.100.7"))
    assessment = scope(rule("ip", "198.51.100.7"), mode="active_assessment")
    assert not evaluate(Operation.ASSESSMENT, target, discovery, now=NOW).allowed
    assert evaluate(Operation.ASSESSMENT, target, assessment, now=NOW).allowed
    assert evaluate(Operation.DISCOVERY, target, assessment, now=NOW).allowed


def test_allowed_decisions_name_the_rules_that_matched() -> None:
    covering = rule("cidr", "198.51.100.0/24")
    view = scope(covering)
    decision = evaluate(
        Operation.DISCOVERY, target_for(IndicatorType.IPV4, "198.51.100.7"), view, now=NOW
    )
    assert decision.allowed and decision.matched_rules == (covering.id,)
    assert decision.scope_id == view.id


def test_port_restrictions() -> None:
    view = scope(rule("ip", "198.51.100.7", ports=[80, 443]))
    target = target_for(IndicatorType.IPV4, "198.51.100.7")
    assert evaluate(Operation.DISCOVERY, target, view, now=NOW, ports=[443]).allowed
    denied = evaluate(Operation.DISCOVERY, target, view, now=NOW, ports=[22, 443])
    assert not denied.allowed and denied.code == "port_not_permitted"


def test_indicators_that_name_no_network_target() -> None:
    assert target_for(IndicatorType.EMAIL, "a@example.com") is None
    decision = evaluate(Operation.DISCOVERY, None, scope(rule("ip", "198.51.100.7")), now=NOW)
    assert decision.code == "target_not_addressable"
