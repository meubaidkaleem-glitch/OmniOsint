"""Schemas: universal search, collection plans, requests, jobs, evidence, scopes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from omniosint.indicators.classifier import MAX_INPUT_LENGTH
from omniosint.indicators.types import EntityType, IndicatorType


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- search
class ClassifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(max_length=MAX_INPUT_LENGTH)
    remember: bool = Field(default=True, description="Add the search to your search history.")


class CandidateOut(_Out):
    type: IndicatorType
    label: str
    value: str
    display: str
    rank: Literal["strong", "plausible", "weak"]
    reason: str
    notes: list[str]
    details: dict[str, Any]
    entity_type: EntityType | None
    modules: list[str]


class ClassificationOut(_Out):
    input: str
    status: Literal["recognized", "ambiguous", "unrecognized"]
    message: str
    candidates: list[CandidateOut]
    mentions: list[CandidateOut]
    refanged: bool
    hints: list[str]


class InputTypeOut(BaseModel):
    type: IndicatorType
    label: str
    description: str
    input_kind: Literal["text", "file"]
    entity_type: EntityType | None
    modules: list[str]
    example: str


class InputTypeList(BaseModel):
    items: list[InputTypeOut]


class HistoryEntryOut(_Out):
    id: uuid.UUID
    query: str
    status: str
    types: list[str]
    created_at: datetime


class HistoryList(BaseModel):
    items: list[HistoryEntryOut]


class SavedSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)
    indicator_type: IndicatorType | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class SavedSearchOut(_Out):
    id: uuid.UUID
    name: str
    query: str
    indicator_type: str | None
    options: dict[str, Any]
    created_at: datetime


class SavedSearchList(BaseModel):
    items: list[SavedSearchOut]


# --------------------------------------------------------------------------- plans
class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)
    type: IndicatorType | None = Field(
        default=None,
        description="The reading to use. Required when the input is ambiguous.",
    )
    mode: Literal["passive", "active"] = "passive"
    strategy: Literal["free_first", "include_paid"] = "free_first"
    providers: list[str] | None = Field(default=None, max_length=50)
    scope_id: uuid.UUID | None = None
    force_refresh: bool = False
    provider_options: dict[str, Any] = Field(
        default_factory=dict,
        description="Options for the simulated provider only (for example simulate=timeout).",
    )

    @field_validator("provider_options")
    @classmethod
    def _small(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 10 or any(len(str(key)) > 32 for key in value):
            raise ValueError("at most 10 options with short names")
        return value


class PlanIndicatorOut(BaseModel):
    type: IndicatorType
    label: str
    value: str
    display: str
    entity_type: EntityType | None


class PlanStepOut(BaseModel):
    provider_id: str
    provider_name: str
    capability_id: str | None
    capability_name: str | None
    description: str | None
    operation: str | None
    active: bool
    cost: dict[str, Any]
    simulated: bool
    status: Literal[
        "ready",
        "cached",
        "needs_approval",
        "blocked",
        "skipped",
        "unavailable",
        "planned",
        "excluded",
    ]
    message: str
    selected: bool
    phase: int | None
    cached_result_id: str | None
    cache_fresh_until: str | None
    scope_decision: dict[str, Any] | None


class PlanModuleOut(BaseModel):
    id: str
    title: str
    phase: int


class PlanScopeOut(BaseModel):
    id: uuid.UUID
    name: str | None


class PlanOut(BaseModel):
    indicator: PlanIndicatorOut
    mode: Literal["passive", "active"]
    strategy: Literal["free_first", "include_paid"]
    providers: list[str] | None
    scope: PlanScopeOut | None
    force_refresh: bool
    modules: list[PlanModuleOut]
    steps: list[PlanStepOut]
    summary: dict[str, int]
    warnings: list[str]


# --------------------------------------------------------------------------- requests and jobs
class JobOut(_Out):
    id: uuid.UUID
    request_id: uuid.UUID
    indicator_type: str
    indicator_value: str
    provider_id: str
    capability: str
    is_active: bool
    is_simulated: bool
    scope_id: uuid.UUID | None
    status: str
    attempt: int
    max_attempts: int
    scheduled_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    progress: dict[str, Any]
    error: dict[str, Any] | None
    outcome: dict[str, Any] | None
    cost: dict[str, Any]
    approved_at: datetime | None
    created_at: datetime


class JobList(BaseModel):
    items: list[JobOut]
    next_cursor: str | None


class JobEventOut(_Out):
    id: uuid.UUID
    occurred_at: datetime
    kind: str
    message: str
    details: dict[str, Any]


class ResultOut(_Out):
    id: uuid.UUID
    page: int
    raw_sha256: str
    raw_size: int
    content_type: str
    status_code: int | None
    item_count: int
    normalization_error: dict[str, Any] | None
    from_cache: bool
    reused_result_id: uuid.UUID | None
    is_simulated: bool
    received_at: datetime
    expires_at: datetime | None


class JobDetailOut(BaseModel):
    job: JobOut
    events: list[JobEventOut]
    results: list[ResultOut]
    evidence_count: int


class RequestOut(_Out):
    id: uuid.UUID
    input_text: str
    indicator_type: str
    indicator_value: str
    entity_id: uuid.UUID | None
    mode: str
    strategy: str
    scope_id: uuid.UUID | None
    status: str
    is_simulated: bool
    created_by: uuid.UUID | None
    created_at: datetime
    finished_at: datetime | None


class RequestList(BaseModel):
    items: list[RequestOut]
    next_cursor: str | None


class RequestDetailOut(BaseModel):
    request: RequestOut
    plan: dict[str, Any]
    jobs: list[JobOut]


# --------------------------------------------------------------------------- evidence
class EvidenceOut(_Out):
    id: uuid.UUID
    entity_id: uuid.UUID
    source_id: str
    provider_id: str | None
    job_id: uuid.UUID | None
    collection_result_id: uuid.UUID | None
    observation_kind: str
    source_url: str | None
    provider_object_id: str | None
    collected_at: datetime
    observed_at: datetime | None
    normalized: dict[str, Any]
    raw_sha256: str | None
    raw_pointer: str | None
    content_hash: str
    verification_status: str
    is_redacted: bool
    is_simulated: bool
    transformation_history: list[dict[str, Any]]
    created_at: datetime


class EvidenceList(BaseModel):
    items: list[EvidenceOut]
    next_cursor: str | None


class IntegrityOut(BaseModel):
    content_hash_valid: bool
    raw_available: bool
    raw_hash_valid: bool | None
    detail: str


class EvidenceDetailOut(BaseModel):
    evidence: EvidenceOut
    integrity: IntegrityOut
    entity: EntityOut
    source: SourceOut | None


class RawOut(BaseModel):
    sha256: str
    content_type: str
    size: int
    format: Literal["json", "text"]
    body: Any
    redacted: bool
    simulated: bool


class EntityOut(_Out):
    id: uuid.UUID
    type: str
    canonical_key: str
    display_name: str
    attributes: dict[str, Any]
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    is_simulated: bool
    created_at: datetime


class EntityList(BaseModel):
    items: list[EntityOut]
    next_cursor: str | None


class SourceOut(_Out):
    id: str
    name: str
    kind: str
    provider_id: str | None
    homepage_url: str | None
    reliability: str
    upstream_source_ids: list[str]
    terms_note: str | None
    is_simulated: bool


class SourceList(BaseModel):
    items: list[SourceOut]


# --------------------------------------------------------------------------- scopes
class ScopeRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["domain", "wildcard", "ip", "cidr", "url_prefix"]
    value: str = Field(min_length=1, max_length=2048)
    is_exclusion: bool = False
    ports: list[int] | None = Field(default=None, max_length=100)


class ScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=128)
    mode: Literal["passive", "authorized_discovery", "active_assessment"]
    authorized_by: str = Field(
        min_length=2, max_length=256, description="Who gave the written authorisation."
    )
    authorization_reference: str | None = Field(default=None, max_length=256)
    authorization_note: str | None = Field(default=None, max_length=4000)
    description: str | None = Field(default=None, max_length=4000)
    valid_from: datetime | None = None
    valid_until: datetime
    authorization_confirmed: bool = Field(
        description="Must be true: written authorisation exists for every target listed."
    )
    rules: list[ScopeRuleIn] = Field(default_factory=list, max_length=500)


class ScopeRuleOut(_Out):
    id: uuid.UUID
    kind: str
    value: str
    is_exclusion: bool
    restrictions: dict[str, Any]
    created_at: datetime


class ScopeOut(_Out):
    id: uuid.UUID
    name: str
    description: str | None
    mode: str
    status: Literal["active", "not_approved", "not_yet_valid", "expired", "revoked"]
    authorized_by: str
    authorization_reference: str | None
    authorization_note: str | None
    valid_from: datetime
    valid_until: datetime
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    revoked_at: datetime | None
    revoke_reason: str | None
    created_at: datetime


class ScopeDetailOut(BaseModel):
    scope: ScopeOut
    rules: list[ScopeRuleOut]


class ScopeList(BaseModel):
    items: list[ScopeOut]


class RevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=512)


class ScopeCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)
    type: IndicatorType | None = None
    operation: Literal["discovery", "assessment"] = "discovery"
    ports: list[int] = Field(default_factory=list, max_length=100)


class ScopeDecisionOut(BaseModel):
    allowed: bool
    code: str
    reason: str
    scope_id: str | None
    matched_rules: list[str]
    target: str | None


# --------------------------------------------------------------------------- providers
class CapabilityOut(BaseModel):
    id: str
    name: str
    description: str
    accepts: list[IndicatorType]
    operation: str
    active: bool
    cost: dict[str, Any]
    cache_ttl_seconds: int
    timeout_seconds: float
    max_pages: int


class AdapterOut(BaseModel):
    id: str
    name: str
    category: str
    version: str
    description: str
    status: Literal["available", "not_configured", "disabled"]
    message: str
    simulated: bool
    verified_live: bool
    requires_credentials: bool
    missing_credentials: list[str]
    circuit: str
    rate_limit: dict[str, Any]
    capabilities: list[CapabilityOut]
    usage_today: dict[str, Any]


class AdapterList(BaseModel):
    items: list[AdapterOut]


class HealthOut(BaseModel):
    status: str
    detail: str
    latency_ms: float | None
    quota: dict[str, Any] | None


EvidenceDetailOut.model_rebuild()
