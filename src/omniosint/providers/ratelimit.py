"""Token-bucket rate limiting per provider.

In-process by default. When Redis is configured the buckets live there, so the
API and the worker share one budget per provider; if Redis cannot be reached
the limiter falls back to its in-process buckets and says so in the log.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from omniosint.providers.base import RateLimit
from omniosint.providers.errors import ProviderRateLimited

log = structlog.get_logger(__name__)


class RateLimiter(Protocol):
    async def acquire(self, key: str, limit: RateLimit, *, max_wait: float) -> float:
        """Take one token, waiting up to ``max_wait`` seconds. Returns the time waited.

        Raises ``ProviderRateLimited`` (with ``retry_after``) when the wait would
        be longer: the job is then rescheduled instead of holding a worker.
        """
        ...


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float


class LocalRateLimiter:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    def _wait_needed(self, key: str, limit: RateLimit) -> float:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = self._buckets[key] = _Bucket(float(limit.capacity), now)
        elapsed = max(0.0, now - bucket.updated)
        bucket.tokens = min(float(limit.capacity), bucket.tokens + elapsed * limit.rate)
        bucket.updated = now
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return 0.0
        return (1 - bucket.tokens) / limit.rate

    async def acquire(self, key: str, limit: RateLimit, *, max_wait: float) -> float:
        waited = 0.0
        while True:
            async with self._lock:
                wait = self._wait_needed(key, limit)
            if wait == 0:
                return waited
            if waited + wait > max_wait:
                raise ProviderRateLimited(
                    "The provider's rate limit allows no call now.",
                    retry_after=math.ceil(wait),
                )
            await self._sleep(wait)
            waited += wait


# Atomic token bucket. KEYS[1] bucket; ARGV rate (tokens/s), capacity, now (ms).
# Returns the milliseconds to wait (0 when a token was taken).
_REDIS_SCRIPT = """
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'updated')
local tokens = tonumber(state[1]) or capacity
local updated = tonumber(state[2]) or now
local elapsed = math.max(0, now - updated) / 1000
tokens = math.min(capacity, tokens + elapsed * rate)
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = math.ceil((1 - tokens) / rate * 1000)
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated', now)
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate * 1000) + 60000)
return wait
"""


class RedisRateLimiter:
    """Shared buckets in Redis, falling back to ``LocalRateLimiter`` on errors."""

    def __init__(self, client: Any, *, prefix: str = "omniosint:ratelimit:") -> None:
        self._client = client
        self._prefix = prefix
        self._script = client.register_script(_REDIS_SCRIPT)
        self._fallback = LocalRateLimiter()
        self._warned = False

    async def acquire(self, key: str, limit: RateLimit, *, max_wait: float) -> float:
        waited = 0.0
        while True:
            try:
                wait_ms = int(
                    await self._script(
                        keys=[self._prefix + key],
                        args=[limit.rate, limit.capacity, int(time.time() * 1000)],
                    )
                )
            except Exception as error:  # any Redis failure means falling back
                if not self._warned:
                    log.warning("ratelimit.redis_unavailable", error=type(error).__name__)
                    self._warned = True
                return waited + await self._fallback.acquire(key, limit, max_wait=max_wait - waited)
            if wait_ms == 0:
                return waited
            wait = wait_ms / 1000
            if waited + wait > max_wait:
                raise ProviderRateLimited(
                    "The provider's rate limit allows no call now.", retry_after=math.ceil(wait)
                )
            await asyncio.sleep(wait)
            waited += wait
