"""The contract every provider adapter implements (ADR-015).

An adapter declares what it can do as metadata, fetches raw responses, and
turns them into observations. Everything around it (credentials, rate limits,
the circuit breaker, timeouts, caching, storage of raw responses, evidence) is
supplied by the framework, so adapters stay small and behave the same way.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from omniosint.indicators.types import EntityType, IndicatorType

if TYPE_CHECKING:
    from omniosint.net.http import SafeHttpClient


class CostKind(StrEnum):
    FREE = "free"
    CREDITS = "credits"
    PAID = "paid"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Cost:
    kind: CostKind = CostKind.FREE
    credits_per_call: float | None = None
    note: str | None = None

    @property
    def is_free(self) -> bool:
        return self.kind is CostKind.FREE

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "credits_per_call": self.credits_per_call,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class RateLimit:
    """At most ``requests`` per ``per_seconds``, bursting up to ``burst``."""

    requests: int
    per_seconds: float
    burst: int | None = None

    @property
    def rate(self) -> float:
        return self.requests / self.per_seconds

    @property
    def capacity(self) -> int:
        return self.burst or self.requests


class Operation(StrEnum):
    """What a capability does to its target. Only ``LOOKUP`` is passive."""

    LOOKUP = "lookup"  # asks a third party about the target; the target is not contacted
    DISCOVERY = "discovery"  # contacts the target to find what exists (needs a scope)
    ASSESSMENT = "assessment"  # tests the target's behaviour (needs an assessment scope)


@dataclass(frozen=True, slots=True)
class Capability:
    id: str
    name: str
    description: str
    accepts: frozenset[IndicatorType]
    operation: Operation = Operation.LOOKUP
    cost: Cost = field(default_factory=Cost)
    cache_ttl_seconds: int = 24 * 3600
    timeout_seconds: float = 30.0
    max_pages: int = 5
    max_results: int = 500

    @property
    def active(self) -> bool:
        return self.operation is not Operation.LOOKUP


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    id: str
    name: str
    category: str
    version: str
    description: str
    capabilities: tuple[Capability, ...]
    rate_limit: RateLimit
    homepage_url: str | None = None
    terms_note: str | None = None
    credential_names: tuple[str, ...] = ()
    source_kind: str = "api"
    upstream_sources: tuple[str, ...] = ()
    simulated: bool = False
    verified_live: bool = False

    @property
    def requires_credentials(self) -> bool:
        return bool(self.credential_names)

    def capability(self, capability_id: str) -> Capability | None:
        return next((item for item in self.capabilities if item.id == capability_id), None)


@dataclass(frozen=True, slots=True)
class Indicator:
    """The normalised input a capability runs on."""

    type: IndicatorType
    value: str
    display: str
    entity_type: EntityType | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawPage:
    """One response, kept byte for byte."""

    content: bytes
    content_type: str
    received_at: datetime
    status_code: int | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class RawResult:
    pages: tuple[RawPage, ...]
    # Collection stopped early (page limit, result limit, or a later page failed).
    truncated: bool = False
    truncation_reason: str | None = None


class Quota(BaseModel):
    """What the provider says is left. Fields the provider does not expose stay unset."""

    model_config = ConfigDict(frozen=True)

    plan: str | None = None
    remaining: float | None = None
    limit: float | None = None
    unit: str | None = None
    resets_at: datetime | None = None


class HealthResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str  # "ok", "degraded", "failed", "not_configured", "unknown"
    detail: str
    latency_ms: float | None = None
    quota: Quota | None = None


class RelatedEntity(BaseModel):
    """Another entity an observation mentions, and how. Becomes a candidate
    relationship in the graph engine (Phase 7); it is not a confirmed link."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: EntityType
    value: str = Field(min_length=1, max_length=2048)
    display: str | None = None
    relation: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")


class Observation(BaseModel):
    """One normalised statement from a provider about one entity.

    ``original`` keeps the provider's own values unmodified: normalisation adds
    structure, it never discards what the source said.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.]*$")
    entity_type: EntityType
    entity_value: str = Field(min_length=1, max_length=2048)
    entity_display: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    related: tuple[RelatedEntity, ...] = ()
    observed_at: datetime | None = None
    source_url: str | None = Field(default=None, max_length=2048)
    provider_object_id: str | None = Field(default=None, max_length=256)
    page: int = Field(default=1, ge=1)
    raw_pointer: str | None = Field(default=None, max_length=256)
    original: dict[str, Any] = Field(default_factory=dict)


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def _no_progress(_progress: dict[str, Any]) -> None:
    return None


@dataclass(slots=True)
class CollectionContext:
    """What an adapter is given for one call. ``credentials`` must never be logged."""

    capability: Capability
    http: SafeHttpClient | None
    credentials: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    job_id: uuid.UUID | None = None
    attempt: int = 1
    max_pages: int = 5
    max_results: int = 500
    progress: ProgressCallback = _no_progress
    is_cancelled: Callable[[], bool] = lambda: False


class IntelligenceProvider(ABC):
    """Base class of every adapter."""

    metadata: ClassVar[ProviderMetadata]

    @abstractmethod
    async def collect(self, indicator: Indicator, context: CollectionContext) -> RawResult:
        """Fetch raw responses for ``indicator``. Raise a ``ProviderError`` on failure."""

    @abstractmethod
    def normalize(
        self, indicator: Indicator, capability: Capability, raw: RawResult
    ) -> list[Observation]:
        """Turn raw responses into observations. Raise on malformed data."""

    async def health_check(self, context: CollectionContext) -> HealthResult:
        return HealthResult(status="unknown", detail="This provider has no health check.")

    async def get_quota(self, context: CollectionContext) -> Quota | None:
        """``None`` when the provider does not expose its quota."""
        return None

    async def close(self) -> None:
        return None
