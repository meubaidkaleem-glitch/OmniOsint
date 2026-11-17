"""System, feature registry, dashboard and provider catalogue schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from omniosint.core.features import PHASES, Feature
from omniosint.providers.catalog import ProviderEntry
from omniosint.system.health import ComponentHealth

HealthStatus = Literal["ok", "degraded", "unavailable", "not_configured"]


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ComponentSummary(BaseModel):
    name: str
    label: str
    status: HealthStatus
    required: bool


class ReadyResponse(BaseModel):
    status: HealthStatus
    checked_at: datetime
    components: list[ComponentSummary]


class SystemInfo(BaseModel):
    service: Literal["omniosint"] = "omniosint"
    version: str
    api_version: Literal["v1"] = "v1"
    setup_required: bool | None = Field(
        description="Whether the first administrator still has to be created. "
        "Null when the database cannot be reached."
    )


class ComponentDetail(ComponentSummary):
    detail: str
    latency_ms: float | None
    data: dict[str, Any]

    @classmethod
    def from_health(cls, item: ComponentHealth) -> ComponentDetail:
        return cls(
            name=item.name,
            label=item.label,
            status=item.status.value,
            required=item.required,
            detail=item.detail,
            latency_ms=round(item.latency_ms, 2) if item.latency_ms is not None else None,
            data=item.data,
        )


class RuntimeInfo(BaseModel):
    python: str
    platform: str
    pid: int


class ServerInfo(BaseModel):
    host: str
    port: int
    local_only: bool


class SystemStatus(BaseModel):
    status: HealthStatus
    checked_at: datetime
    version: str
    environment: str
    started_at: datetime
    uptime_seconds: int
    runtime: RuntimeInfo
    server: ServerInfo
    data_directory: str
    components: list[ComponentDetail]


class PhaseOut(BaseModel):
    number: int
    title: str


class FeatureOut(BaseModel):
    key: str
    title: str
    group: str | None
    phase: int
    phase_title: str
    status: Literal["available", "partial", "planned"]
    summary: str
    capabilities: list[str]
    limitations: str | None

    @classmethod
    def from_feature(cls, feature: Feature) -> FeatureOut:
        return cls(
            key=feature.key,
            title=feature.title,
            group=feature.group,
            phase=feature.phase,
            phase_title=PHASES[feature.phase],
            status=feature.status.value,
            summary=feature.summary,
            capabilities=list(feature.capabilities),
            limitations=feature.limitations,
        )


class FeatureCounts(BaseModel):
    available: int
    partial: int
    planned: int


class FeatureList(BaseModel):
    current_phase: int
    phases: list[PhaseOut]
    counts: FeatureCounts
    features: list[FeatureOut]


# --------------------------------------------------------------------------- dashboard
class Metric(BaseModel):
    key: str
    label: str
    available: bool = Field(
        description="False when the module that produces this number does not exist yet. "
        "An unavailable metric has no value; it is never reported as zero."
    )
    value: int | None
    planned_phase: int | None
    phase_title: str | None


class DashboardComponent(BaseModel):
    name: str
    label: str
    status: HealthStatus
    required: bool
    detail: str | None = Field(description="Shown only to users with the system:read permission.")


class DashboardHealth(BaseModel):
    status: HealthStatus
    checked_at: datetime
    components: list[DashboardComponent]


class ProviderCounts(BaseModel):
    total: int
    available: int
    planned: int
    excluded: int


class ActivityItem(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    action: str
    outcome: str
    actor_label: str
    target_type: str | None
    target_id: str | None


class DashboardResponse(BaseModel):
    generated_at: datetime
    health: DashboardHealth
    metrics: list[Metric]
    modules: FeatureCounts
    providers: ProviderCounts
    recent_activity: list[ActivityItem]
    activity_scope: Literal["all", "own"] = Field(
        description="`all` for users who may read the audit trail, otherwise only their own."
    )


# --------------------------------------------------------------------------- providers
class ProviderOut(BaseModel):
    id: str
    name: str
    category: str
    category_label: str
    access: str
    access_label: str
    auth: str
    docs_url: str
    phase: int
    status: Literal["planned", "available", "excluded"]
    status_message: str
    modules: list[str]
    notes: str

    @classmethod
    def from_entry(cls, entry: ProviderEntry) -> ProviderOut:
        return cls(
            id=entry.id,
            name=entry.name,
            category=entry.category,
            category_label=entry.category_label,
            access=entry.access,
            access_label=entry.access_label,
            auth=entry.auth,
            docs_url=entry.docs_url,
            phase=entry.phase,
            status=entry.status,
            status_message=entry.status_message,
            modules=list(entry.modules),
            notes=entry.notes,
        )


class CategoryOut(BaseModel):
    key: str
    label: str
    count: int


class ProviderList(BaseModel):
    items: list[ProviderOut]
    counts: ProviderCounts
    categories: list[CategoryOut]
