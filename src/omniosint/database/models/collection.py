"""Providers, collection requests, the job queue and what jobs returned."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from omniosint.core.ids import uuid7
from omniosint.database.base import Base
from omniosint.indicators.types import IndicatorType

INDICATOR_TYPE_CHECK = (
    "indicator_type IN (" + ", ".join(f"'{item.value}'" for item in IndicatorType) + ")"
)
REQUEST_STATUSES = (
    "pending",
    "awaiting_approval",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
)
JOB_STATUSES = (
    "queued",
    "awaiting_approval",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "skipped",
)
FINISHED_JOB_STATUSES = ("succeeded", "failed", "cancelled", "skipped")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


class Provider(Base):
    """An adapter known to this installation, kept in step with the code."""

    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_health: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProviderUsage(Base):
    """Calls made to a provider, per day and capability."""

    __tablename__ = "provider_usage"

    provider_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("providers.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    capability: Mapped[str] = mapped_column(String(96), nullable=False)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    credits: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, server_default=text("0")
    )

    __table_args__ = (PrimaryKeyConstraint("provider_id", "day", "capability"),)


class CollectionRequest(Base):
    """One submitted collection plan: an indicator and the jobs run for it."""

    __tablename__ = "collection_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    indicator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_value: Mapped[str] = mapped_column(String(2048), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="RESTRICT"), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True
    )
    options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(INDICATOR_TYPE_CHECK, name="indicator_type_valid"),
        CheckConstraint(_in("mode", ("passive", "active")), name="mode_valid"),
        CheckConstraint(_in("status", REQUEST_STATUSES), name="status_valid"),
        Index("ix_collection_requests_created_at_id", "created_at", "id"),
        Index("ix_collection_requests_created_by", "created_by"),
        Index("ix_collection_requests_entity_id", "entity_id"),
    )


class CollectionJob(Base):
    """One provider call to make, and its history. Leased by workers with
    ``SELECT ... FOR UPDATE SKIP LOCKED`` (ADR-004)."""

    __tablename__ = "collection_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("collection_requests.id", ondelete="CASCADE"), nullable=False
    )
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="RESTRICT"), nullable=True
    )
    indicator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_value: Mapped[str] = mapped_column(String(2048), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(96), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("scopes.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    progress: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    cost: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    cache_key: Mapped[str] = mapped_column(String(512), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(INDICATOR_TYPE_CHECK, name="indicator_type_valid"),
        CheckConstraint(_in("status", JOB_STATUSES), name="status_valid"),
        CheckConstraint("attempt >= 0 AND max_attempts >= 1", name="attempts_valid"),
        CheckConstraint("NOT is_active OR scope_id IS NOT NULL", name="active_jobs_have_a_scope"),
        Index(
            "ix_collection_jobs_queue",
            "priority",
            "scheduled_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "ix_collection_jobs_leases",
            "lease_expires_at",
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_collection_jobs_request_id", "request_id"),
        Index("ix_collection_jobs_created_at_id", "created_at", "id"),
        Index("ix_collection_jobs_status", "status"),
    )


class CollectionJobEvent(Base):
    """What happened to a job: queued, leased, retried, failed, and why."""

    __tablename__ = "collection_job_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("collection_jobs.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(1024), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        Index("ix_collection_job_events_job_id_occurred_at", "job_id", "occurred_at"),
    )


class CollectionResult(Base):
    """One response a job received (one per page), and its normalised form.

    ``raw_sha256`` is kept when the raw bytes are purged after their retention
    period, so the integrity of the evidence derived from it can still be shown.
    """

    __tablename__ = "collection_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("collection_jobs.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(96), nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    normalization_error: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    from_cache: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    reused_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("collection_results.id", ondelete="SET NULL"), nullable=True
    )
    cache_key: Mapped[str] = mapped_column(String(512), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("raw_sha256 ~ '^[0-9a-f]{64}$'", name="raw_hex"),
        CheckConstraint("item_count >= 0 AND page >= 1", name="counts_valid"),
        Index("ix_collection_results_job_id", "job_id"),
        Index("ix_collection_results_cache_key_expires_at", "cache_key", "expires_at"),
    )
