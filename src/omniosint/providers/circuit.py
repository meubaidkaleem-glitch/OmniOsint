"""Circuit breaker: stop calling a provider that keeps failing.

After ``failure_threshold`` consecutive failures that point at the provider
(timeouts, outages, malformed responses) the circuit opens and calls fail at
once with ``CircuitOpen`` for ``cooldown_seconds``. Then one trial call is let
through: success closes the circuit, failure opens it again.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from omniosint.providers.errors import (
    CircuitOpen,
    ProviderError,
    ProviderMalformedResponse,
    ProviderTimeout,
    ProviderUnavailable,
)

# Failures that say something about the provider, not about the input or the account.
_COUNTED = (ProviderTimeout, ProviderUnavailable, ProviderMalformedResponse)


@dataclass(slots=True)
class _State:
    failures: int = 0
    opened_at: float | None = None
    trial_running: bool = False


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._states: dict[str, _State] = {}

    def _state(self, provider_id: str) -> _State:
        return self._states.setdefault(provider_id, _State())

    def state(self, provider_id: str) -> str:
        state = self._states.get(provider_id)
        if state is None or state.opened_at is None:
            return "closed"
        if self._clock() - state.opened_at >= self._cooldown:
            return "half_open"
        return "open"

    def before_call(self, provider_id: str) -> None:
        state = self._state(provider_id)
        if state.opened_at is None:
            return
        remaining = self._cooldown - (self._clock() - state.opened_at)
        if remaining > 0 or state.trial_running:
            raise CircuitOpen(retry_after=max(1.0, round(remaining, 1)))
        state.trial_running = True

    def record_success(self, provider_id: str) -> None:
        self._states[provider_id] = _State()

    def record_failure(self, provider_id: str, error: BaseException) -> None:
        state = self._state(provider_id)
        state.trial_running = False
        if not isinstance(error, _COUNTED):
            if isinstance(error, ProviderError) and state.opened_at is not None:
                # A trial that failed for another reason does not prove recovery.
                state.opened_at = self._clock()
            return
        state.failures += 1
        if state.opened_at is not None or state.failures >= self._threshold:
            state.opened_at = self._clock()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            provider_id: {"state": self.state(provider_id), "consecutive_failures": state.failures}
            for provider_id, state in self._states.items()
        }
