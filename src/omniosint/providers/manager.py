"""The provider manager: the one way any code calls a provider.

Around each adapter call it applies, in order: the circuit breaker, the rate
limiter, credential lookup, a timeout, and validation of the normalised
output. Identical calls already in flight are joined rather than repeated.
Caching and retries are durable and live with the job queue, which records
every attempt.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import ValidationError

from omniosint.providers.base import (
    Capability,
    CollectionContext,
    HealthResult,
    Indicator,
    IntelligenceProvider,
    Observation,
    ProgressCallback,
    RawResult,
    _no_progress,
)
from omniosint.providers.circuit import CircuitBreaker
from omniosint.providers.errors import (
    AdapterFailed,
    ProviderError,
    ProviderMalformedResponse,
    ProviderNotAvailable,
    ProviderNotConfigured,
    ProviderRejectedInput,
    ProviderTimeout,
)
from omniosint.providers.ratelimit import LocalRateLimiter, RateLimiter
from omniosint.providers.registry import ProviderRegistry

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CallResult:
    provider_id: str
    capability: Capability
    raw: RawResult
    observations: tuple[Observation, ...] | None
    normalization_error: ProviderMalformedResponse | None
    truncated: bool
    truncation_reason: str | None
    duration_ms: float
    rate_limit_wait_s: float


def call_key(
    provider_id: str, capability_id: str, indicator: Indicator, options: dict[str, Any]
) -> str:
    """Identity of a call, for joining duplicates and for the result cache."""
    canonical_options = json.dumps(options, sort_keys=True, separators=(",", ":"), default=str)
    return "|".join(
        (provider_id, capability_id, indicator.type.value, indicator.value, canonical_options)
    )


class ProviderManager:
    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        rate_limiter: RateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        credential_lookup: Callable[[str], str | None] = lambda _name: None,
        http_factory: Callable[[], Any] | None = None,
        rate_limit_max_wait: float = 30.0,
    ) -> None:
        self.registry = registry
        self.circuit = circuit_breaker or CircuitBreaker()
        self._limiter = rate_limiter or LocalRateLimiter()
        self._credential_lookup = credential_lookup
        self._http_factory = http_factory
        self._http: Any = None
        self._max_wait = rate_limit_max_wait
        self._inflight: dict[str, asyncio.Future[CallResult]] = {}

    def _http_client(self) -> Any:
        if self._http is None and self._http_factory is not None:
            self._http = self._http_factory()
        return self._http

    def _resolve(
        self, provider_id: str, capability_id: str
    ) -> tuple[IntelligenceProvider, Capability]:
        state = self.registry.state(provider_id)
        if state is None or state.adapter is None:
            raise ProviderNotAvailable(state.message if state else None)
        if state.status == "not_configured":
            raise ProviderNotConfigured(details={"missing": list(state.missing_credentials)})
        if state.status != "available":
            raise ProviderNotAvailable(state.message)
        capability = state.adapter.metadata.capability(capability_id)
        if capability is None:
            raise ProviderNotAvailable(f"{state.name} has no capability {capability_id}.")
        return state.adapter, capability

    async def call(
        self,
        provider_id: str,
        capability_id: str,
        indicator: Indicator,
        *,
        options: dict[str, Any] | None = None,
        job_id: Any = None,
        attempt: int = 1,
        progress: ProgressCallback = _no_progress,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> CallResult:
        adapter, capability = self._resolve(provider_id, capability_id)
        if indicator.type not in capability.accepts:
            raise ProviderRejectedInput(
                f"{capability.name} does not accept a {indicator.type.value.replace('_', ' ')}."
            )
        options = dict(options or {})
        key = call_key(provider_id, capability_id, indicator, options)
        existing = self._inflight.get(key)
        if existing is not None:
            return await asyncio.shield(existing)
        future: asyncio.Future[CallResult] = asyncio.get_running_loop().create_future()
        # A failure nobody else waited for must not be reported as "never retrieved".
        future.add_done_callback(lambda done: done.cancelled() or done.exception())
        self._inflight[key] = future
        try:
            result = await self._call(
                adapter, capability, indicator, options, job_id, attempt, progress, is_cancelled
            )
        except BaseException as error:
            if not future.done():
                future.set_exception(error)
            raise
        else:
            future.set_result(result)
            return result
        finally:
            self._inflight.pop(key, None)

    async def _call(
        self,
        adapter: IntelligenceProvider,
        capability: Capability,
        indicator: Indicator,
        options: dict[str, Any],
        job_id: Any,
        attempt: int,
        progress: ProgressCallback,
        is_cancelled: Callable[[], bool],
    ) -> CallResult:
        metadata = adapter.metadata
        self.circuit.before_call(metadata.id)
        waited = await self._limiter.acquire(
            metadata.id, metadata.rate_limit, max_wait=self._max_wait
        )
        credentials: dict[str, str] = {}
        for name in metadata.credential_names:
            value = self._credential_lookup(name)
            if not value:
                raise ProviderNotConfigured(details={"missing": [name]})
            credentials[name] = value
        context = CollectionContext(
            capability=capability,
            http=self._http_client(),
            credentials=credentials,
            options=options,
            job_id=job_id,
            attempt=attempt,
            max_pages=capability.max_pages,
            max_results=capability.max_results,
            progress=progress,
            is_cancelled=is_cancelled,
        )
        started = time.perf_counter()
        try:
            async with asyncio.timeout(capability.timeout_seconds):
                raw = await adapter.collect(indicator, context)
        except TimeoutError as error:
            timeout = ProviderTimeout(f"No answer within {capability.timeout_seconds:g} seconds.")
            self.circuit.record_failure(metadata.id, timeout)
            raise timeout from error
        except ProviderError as error:
            self.circuit.record_failure(metadata.id, error)
            raise
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.exception("provider.adapter_failed", provider=metadata.id, capability=capability.id)
            failure = AdapterFailed(details={"exception": type(error).__name__})
            self.circuit.record_failure(metadata.id, failure)
            raise failure from error
        duration_ms = (time.perf_counter() - started) * 1000
        observations, normalization_error, capped = self.normalize(
            adapter, indicator, capability, raw
        )
        if normalization_error is not None:
            self.circuit.record_failure(metadata.id, normalization_error)
        else:
            self.circuit.record_success(metadata.id)
        truncated = raw.truncated or capped
        reason = raw.truncation_reason or (
            f"Stopped at the result limit ({capability.max_results})." if capped else None
        )
        return CallResult(
            provider_id=metadata.id,
            capability=capability,
            raw=raw,
            observations=observations,
            normalization_error=normalization_error,
            truncated=truncated,
            truncation_reason=reason,
            duration_ms=round(duration_ms, 1),
            rate_limit_wait_s=round(waited, 3),
        )

    @staticmethod
    def normalize(
        adapter: IntelligenceProvider, indicator: Indicator, capability: Capability, raw: RawResult
    ) -> tuple[tuple[Observation, ...] | None, ProviderMalformedResponse | None, bool]:
        """Validated observations, or the reason the response could not be read.

        The raw response is kept either way, so a malformed answer can be inspected.
        """
        try:
            produced = adapter.normalize(indicator, capability, raw)
            observations = [
                item if isinstance(item, Observation) else Observation.model_validate(item)
                for item in produced
            ]
        except ProviderMalformedResponse as error:
            return None, error, False
        except (ValidationError, ValueError, KeyError, TypeError, AttributeError) as error:
            return (
                None,
                ProviderMalformedResponse(
                    f"The response could not be normalised ({type(error).__name__}).",
                    details={"exception": type(error).__name__},
                ),
                False,
            )
        capped = len(observations) > capability.max_results
        return tuple(observations[: capability.max_results]), None, capped

    async def health(self, provider_id: str) -> HealthResult:
        state = self.registry.state(provider_id)
        if state is None or state.adapter is None:
            return HealthResult(
                status="unknown", detail=state.message if state else "Unknown provider."
            )
        if state.status == "not_configured":
            return HealthResult(status="not_configured", detail=state.message)
        if state.status != "available":
            return HealthResult(status="unknown", detail=state.message)
        adapter = state.adapter
        credentials = {
            name: value
            for name in adapter.metadata.credential_names
            if (value := self._credential_lookup(name))
        }
        capability = adapter.metadata.capabilities[0]
        context = CollectionContext(
            capability=capability, http=self._http_client(), credentials=credentials
        )
        started = time.perf_counter()
        try:
            async with asyncio.timeout(capability.timeout_seconds):
                result = await adapter.health_check(context)
        except TimeoutError:
            return HealthResult(status="failed", detail="The health check timed out.")
        except ProviderError as error:
            return HealthResult(status="failed", detail=error.message)
        latency = round((time.perf_counter() - started) * 1000, 1)
        return (
            result
            if result.latency_ms is not None
            else result.model_copy(update={"latency_ms": latency})
        )

    async def aclose(self) -> None:
        for adapter in self.registry.adapters():
            await adapter.close()
        if self._http is not None:
            await self._http.aclose()
            self._http = None
