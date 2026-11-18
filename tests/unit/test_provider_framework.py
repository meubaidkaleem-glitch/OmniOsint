"""Provider framework: contract, registry, manager, rate limiter, circuit breaker,
and the simulated provider (Phase 2 acceptance: a mock provider returns
structured data; failed provider operations are handled)."""

from __future__ import annotations

import asyncio
import ipaddress
import json
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest

from omniosint.core.errors import NOT_CONFIGURED_MESSAGE, PLANNED_MESSAGE
from omniosint.indicators.types import EntityType, IndicatorType
from omniosint.providers.base import (
    Capability,
    CollectionContext,
    Indicator,
    IntelligenceProvider,
    Observation,
    ProviderMetadata,
    RateLimit,
    RawPage,
    RawResult,
)
from omniosint.providers.catalog import load_catalogue
from omniosint.providers.circuit import CircuitBreaker
from omniosint.providers.errors import (
    AdapterFailed,
    CircuitOpen,
    ProviderAuthFailed,
    ProviderMalformedResponse,
    ProviderNotAvailable,
    ProviderNotConfigured,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderRejectedInput,
    ProviderTimeout,
    ProviderUnavailable,
)
from omniosint.providers.manager import ProviderManager
from omniosint.providers.ratelimit import LocalRateLimiter
from omniosint.providers.registry import ProviderRegistry
from omniosint.providers.simulated import LOOKUP, NOTICE, PROBE, SimulatedProvider

DOMAIN = Indicator(IndicatorType.DOMAIN, "example.org", "example.org", EntityType.DOMAIN)
TEST_NET_1 = ipaddress.ip_network("192.0.2.0/24")


def registry(**kwargs: Any) -> ProviderRegistry:
    kwargs.setdefault("simulated_enabled", True)
    return ProviderRegistry(load_catalogue(), **kwargs)


def manager(**kwargs: Any) -> ProviderManager:
    return ProviderManager(registry(**kwargs))


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


# --------------------------------------------------------------------------- registry
def test_simulated_provider_is_disabled_unless_enabled() -> None:
    state = registry(simulated_enabled=False).state("simulated")
    assert state is not None and state.status == "disabled" and not state.runnable
    assert "enable_simulated_provider" in state.message
    assert registry().state("simulated").runnable  # type: ignore[union-attr]


def test_catalogue_entries_without_adapters_are_planned_or_excluded() -> None:
    states = {state.id: state for state in registry().states()}
    shodan = states["shodan"]
    assert shodan.status == "planned" and shodan.message == PLANNED_MESSAGE
    assert shodan.adapter is None and not shodan.runnable
    excluded = [state for state in states.values() if state.status == "excluded"]
    assert excluded and all(state.adapter is None for state in excluded)
    assert not [
        state for state in states.values() if state.status == "available" and not state.simulated
    ]


class KeyedProvider(IntelligenceProvider):
    metadata: ClassVar[ProviderMetadata] = ProviderMetadata(
        id="keyed",
        name="Keyed test provider",
        category="test",
        version="1",
        description="Needs a key.",
        capabilities=(
            Capability("keyed.lookup", "Lookup", "Test", frozenset({IndicatorType.DOMAIN})),
        ),
        rate_limit=RateLimit(100, 1.0),
        credential_names=("providers.keyed.api_key",),
    )
    calls: ClassVar[list[dict[str, str]]] = []

    async def collect(self, indicator: Indicator, context: CollectionContext) -> RawResult:
        self.calls.append(dict(context.credentials))
        return RawResult(pages=(RawPage(b"{}", "application/json", datetime.now(UTC)),))

    def normalize(
        self, indicator: Indicator, capability: Capability, raw: RawResult
    ) -> list[Observation]:
        return []


def test_missing_credentials_read_not_configured() -> None:
    state = registry(adapters=[KeyedProvider()]).state("keyed")
    assert state is not None and state.status == "not_configured"
    assert state.message == NOT_CONFIGURED_MESSAGE == "Not configured — API credentials required."
    assert state.missing_credentials == ("providers.keyed.api_key",)
    configured = registry(adapters=[KeyedProvider()], has_secret=lambda name: True).state("keyed")
    assert configured is not None and configured.runnable


def test_disabled_by_administrator() -> None:
    state = registry(disabled_ids={"simulated"}).state("simulated")
    assert state is not None and state.status == "disabled"


def test_options_for_an_indicator_type() -> None:
    options = registry().options_for(IndicatorType.DOMAIN)
    assert {option.capability.id for option in options} == {
        "simulated.lookup",
        "simulated.paid_lookup",
        "simulated.probe",
    }
    assert {option.capability.id for option in registry().options_for(IndicatorType.CVE)} == {
        "simulated.lookup",
        "simulated.paid_lookup",
    }
    assert registry().options_for(IndicatorType.QUESTION) == []


def test_planned_providers_by_module() -> None:
    planned = {state.id for state in registry().planned_for(["internet_assets"])}
    assert {"shodan", "censys"} <= planned


# --------------------------------------------------------------------------- simulated
async def test_simulated_lookup_returns_structured_labelled_data() -> None:
    result = await manager().call("simulated", "simulated.lookup", DOMAIN)
    assert result.normalization_error is None
    assert result.observations
    body = json.loads(result.raw.pages[0].content)
    assert body["simulated"] is True and body["notice"] == NOTICE
    for observation in result.observations:
        assert observation.entity_type is EntityType.DOMAIN
        assert observation.entity_value == "example.org"
        assert observation.attributes["simulated"] is True
        assert observation.original  # the provider's own record is kept
        for related in observation.related:
            if related.type is EntityType.IP_ADDRESS:
                assert ipaddress.ip_address(related.value) in TEST_NET_1
            else:
                assert related.value.endswith(".simulated.example")


async def test_simulated_data_is_deterministic() -> None:
    first = await manager().call("simulated", "simulated.lookup", DOMAIN)
    second = await manager().call("simulated", "simulated.lookup", DOMAIN)
    assert first.raw.pages[0].content == second.raw.pages[0].content
    other = await manager().call(
        "simulated",
        "simulated.lookup",
        Indicator(IndicatorType.DOMAIN, "example.net", "example.net"),
    )
    assert other.raw.pages[0].content != first.raw.pages[0].content


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("timeout", ProviderTimeout),
        ("unavailable", ProviderUnavailable),
        ("rate_limited", ProviderRateLimited),
        ("quota", ProviderQuotaExceeded),
        ("auth", ProviderAuthFailed),
    ],
)
async def test_simulated_failures_raise_typed_errors(mode: str, error: type[Exception]) -> None:
    with pytest.raises(error) as raised:
        await manager().call("simulated", "simulated.lookup", DOMAIN, options={"simulate": mode})
    assert raised.value.code.startswith("provider_")  # type: ignore[attr-defined]


async def test_malformed_response_is_kept_and_reported() -> None:
    result = await manager().call(
        "simulated", "simulated.lookup", DOMAIN, options={"simulate": "malformed"}
    )
    assert result.observations is None
    assert isinstance(result.normalization_error, ProviderMalformedResponse)
    assert result.raw.pages[0].content.startswith(b'{"records"')


async def test_empty_and_paginated_results() -> None:
    empty = await manager().call(
        "simulated", "simulated.lookup", DOMAIN, options={"simulate": "empty"}
    )
    assert empty.observations == ()
    paged = await manager().call("simulated", "simulated.lookup", DOMAIN, options={"pages": 3})
    assert len(paged.raw.pages) == 3 and not paged.truncated
    assert {observation.page for observation in paged.observations or ()} == {1, 2, 3}
    capped = await manager().call("simulated", "simulated.lookup", DOMAIN, options={"pages": 50})
    assert len(capped.raw.pages) == LOOKUP.max_pages and capped.truncated
    assert "page limit" in (capped.truncation_reason or "")


async def test_partial_result_keeps_the_pages_that_arrived() -> None:
    result = await manager().call(
        "simulated", "simulated.lookup", DOMAIN, options={"simulate": "partial", "pages": 3}
    )
    assert len(result.raw.pages) == 1 and result.truncated
    assert "Page 2 failed" in (result.truncation_reason or "")


async def test_flaky_provider_succeeds_on_a_later_attempt() -> None:
    with pytest.raises(ProviderUnavailable):
        await manager().call(
            "simulated", "simulated.lookup", DOMAIN, options={"simulate": "flaky"}, attempt=1
        )
    result = await manager().call(
        "simulated", "simulated.lookup", DOMAIN, options={"simulate": "flaky"}, attempt=2
    )
    assert result.observations


async def test_probe_is_declared_active() -> None:
    assert PROBE.active and not LOOKUP.active
    result = await manager().call(
        "simulated",
        "simulated.probe",
        Indicator(IndicatorType.IPV4, "198.51.100.7", "198.51.100.7"),
    )
    assert result.observations and result.observations[0].kind == "simulated.open_port"


# --------------------------------------------------------------------------- manager
async def test_unknown_disabled_and_rejected() -> None:
    with pytest.raises(ProviderNotAvailable):
        await manager().call("nonexistent", "x", DOMAIN)
    with pytest.raises(ProviderNotAvailable):
        await manager(simulated_enabled=False).call("simulated", "simulated.lookup", DOMAIN)
    with pytest.raises(ProviderNotAvailable):
        await manager().call("simulated", "simulated.nothing", DOMAIN)
    with pytest.raises(ProviderRejectedInput):
        await manager().call(
            "simulated",
            "simulated.probe",
            Indicator(IndicatorType.CVE, "CVE-2021-44228", "CVE-2021-44228"),
        )


async def test_credentials_are_looked_up_and_required() -> None:
    lookups: dict[str, str] = {"providers.keyed.api_key": "test-key"}
    keyed = ProviderManager(
        registry(adapters=[KeyedProvider()], has_secret=lambda name: name in lookups),
        credential_lookup=lookups.get,
    )
    KeyedProvider.calls.clear()
    await keyed.call("keyed", "keyed.lookup", DOMAIN)
    assert KeyedProvider.calls == [{"providers.keyed.api_key": "test-key"}]
    missing = ProviderManager(registry(adapters=[KeyedProvider()]))
    with pytest.raises(ProviderNotConfigured) as raised:
        await missing.call("keyed", "keyed.lookup", DOMAIN)
    assert raised.value.message == NOT_CONFIGURED_MESSAGE


class SlowProvider(IntelligenceProvider):
    metadata: ClassVar[ProviderMetadata] = ProviderMetadata(
        id="slow",
        name="Slow test provider",
        category="test",
        version="1",
        description="Never answers in time.",
        capabilities=(
            Capability(
                "slow.lookup",
                "Lookup",
                "Test",
                frozenset({IndicatorType.DOMAIN}),
                timeout_seconds=0.05,
            ),
        ),
        rate_limit=RateLimit(100, 1.0),
    )
    started = 0

    async def collect(self, indicator: Indicator, context: CollectionContext) -> RawResult:
        SlowProvider.started += 1
        await asyncio.sleep(10)
        raise AssertionError("unreachable")

    def normalize(
        self, indicator: Indicator, capability: Capability, raw: RawResult
    ) -> list[Observation]:
        return []


async def test_timeouts_are_enforced_and_open_the_circuit() -> None:
    slow = ProviderManager(
        registry(adapters=[SlowProvider()]), circuit_breaker=CircuitBreaker(failure_threshold=2)
    )
    for _ in range(2):
        with pytest.raises(ProviderTimeout):
            await slow.call("slow", "slow.lookup", DOMAIN)
    with pytest.raises(CircuitOpen):
        await slow.call("slow", "slow.lookup", DOMAIN)
    assert slow.circuit.state("slow") == "open"


class BrokenProvider(KeyedProvider):
    metadata: ClassVar[ProviderMetadata] = ProviderMetadata(
        id="broken",
        name="Broken test provider",
        category="test",
        version="1",
        description="Has bugs.",
        capabilities=(
            Capability("broken.crash", "Crash", "Test", frozenset({IndicatorType.DOMAIN})),
            Capability("broken.garbage", "Garbage", "Test", frozenset({IndicatorType.DOMAIN})),
        ),
        rate_limit=RateLimit(100, 1.0),
    )

    async def collect(self, indicator: Indicator, context: CollectionContext) -> RawResult:
        if context.capability.id == "broken.crash":
            raise RuntimeError("bug in the adapter")
        return RawResult(pages=(RawPage(b"[]", "application/json", datetime.now(UTC)),))

    def normalize(self, indicator: Indicator, capability: Capability, raw: RawResult) -> list[Any]:
        return [{"kind": "x", "entity_type": "not-a-type", "entity_value": "example.org"}]


async def test_adapter_bugs_and_invalid_output_become_recorded_failures() -> None:
    broken = ProviderManager(registry(adapters=[BrokenProvider()]))
    with pytest.raises(AdapterFailed) as raised:
        await broken.call("broken", "broken.crash", DOMAIN)
    assert raised.value.details == {"exception": "RuntimeError"}
    result = await broken.call("broken", "broken.garbage", DOMAIN)
    assert result.observations is None
    assert isinstance(result.normalization_error, ProviderMalformedResponse)


async def test_identical_calls_in_flight_are_joined() -> None:
    calls = 0
    simulated = SimulatedProvider()
    original = simulated.collect

    async def counting(indicator: Indicator, context: CollectionContext) -> RawResult:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return await original(indicator, context)

    simulated.collect = counting  # type: ignore[method-assign]
    shared = ProviderManager(registry(adapters=[simulated]))
    first, second = await asyncio.gather(
        shared.call("simulated", "simulated.lookup", DOMAIN),
        shared.call("simulated", "simulated.lookup", DOMAIN),
    )
    assert calls == 1 and first is second
    await shared.call("simulated", "simulated.lookup", DOMAIN, options={"pages": 2})
    assert calls == 2


async def test_health_check() -> None:
    health = await manager().health("simulated")
    assert health.status == "ok"
    assert (await manager().health("shodan")).detail == PLANNED_MESSAGE


# --------------------------------------------------------------------------- rate limiter
async def test_token_bucket_waits_then_refuses() -> None:
    clock = FakeClock()
    limiter = LocalRateLimiter(clock=clock, sleep=clock.sleep)
    limit = RateLimit(requests=1, per_seconds=1.0, burst=2)
    assert await limiter.acquire("p", limit, max_wait=5) == 0
    assert await limiter.acquire("p", limit, max_wait=5) == 0
    assert await limiter.acquire("p", limit, max_wait=5) == pytest.approx(1.0)
    with pytest.raises(ProviderRateLimited) as raised:
        await limiter.acquire("p", limit, max_wait=0.5)
    assert raised.value.retry_after == 1
    assert await limiter.acquire("other", limit, max_wait=0) == 0  # buckets are per key


# --------------------------------------------------------------------------- circuit breaker
def test_circuit_breaker_cycle() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=30, clock=clock)
    breaker.record_failure("p", ProviderRejectedInput())
    breaker.record_failure("p", ProviderAuthFailed())
    breaker.before_call("p")  # input and account problems do not open the circuit
    breaker.record_failure("p", ProviderTimeout())
    breaker.record_failure("p", ProviderUnavailable())
    with pytest.raises(CircuitOpen) as raised:
        breaker.before_call("p")
    assert raised.value.retry_after == 30
    clock.now += 31
    assert breaker.state("p") == "half_open"
    breaker.before_call("p")  # one trial call
    with pytest.raises(CircuitOpen):
        breaker.before_call("p")  # and only one
    breaker.record_failure("p", ProviderTimeout())
    assert breaker.state("p") == "open"
    clock.now += 31
    breaker.before_call("p")
    breaker.record_success("p")
    assert breaker.state("p") == "closed"
    breaker.before_call("p")
