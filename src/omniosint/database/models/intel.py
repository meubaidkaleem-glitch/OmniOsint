"""Entities, evidence, the source registry and stored raw responses."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from omniosint.core.ids import uuid7
from omniosint.database.base import Base
from omniosint.indicators.types import EntityType

ENTITY_TYPE_CHECK = "type IN (" + ", ".join(f"'{item.value}'" for item in EntityType) + ")"
SOURCE_KINDS = ("api", "dataset", "tool", "local", "analyst", "upload", "simulated")
RELIABILITY = ("unassessed", "high", "medium", "low")
VERIFICATION_STATUSES = ("unverified", "corroborated", "verified", "disputed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


class EvidenceSource(Base):
    """The source registry: where evidence can come from.

    ``upstream_source_ids`` records lineage, so that two providers reselling
    one dataset are not counted as independent corroboration (Phase 7).
    """

    __tablename__ = "evidence_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    homepage_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reliability: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'unassessed'")
    )
    upstream_source_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    terms_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(_in("kind", SOURCE_KINDS), name="kind_valid"),
        CheckConstraint(_in("reliability", RELIABILITY), name="reliability_valid"),
        CheckConstraint("jsonb_typeof(upstream_source_ids) = 'array'", name="upstream_is_array"),
    )


class Entity(Base):
    """One real-world thing, shared by every investigation and module.

    ``is_simulated`` stays true only while every observation of the entity
    came from the simulated provider.
    """

    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    display_name: Mapped[str] = mapped_column(String(2048), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    first_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("type", "canonical_key", name="uq_entities_type_canonical_key"),
        CheckConstraint(ENTITY_TYPE_CHECK, name="type_valid"),
        CheckConstraint("length(canonical_key) > 0", name="canonical_key_not_empty"),
        Index("ix_entities_last_observed_at", "last_observed_at"),
    )


class RawObject(Base):
    """A stored raw response, addressed by the SHA-256 of its content.

    The bytes live encrypted in the object store under the data directory.
    When ``retain_until`` passes, housekeeping deletes the bytes and this row;
    results and evidence keep the hash, so integrity can still be stated.
    """

    __tablename__ = "raw_objects"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    encryption: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint("size >= 0", name="size_not_negative"),
        Index("ix_raw_objects_retain_until", "retain_until"),
    )


class Evidence(Base):
    """One attributable observation. Append-only.

    Triggers created by migration 0002 reject updates, and reject deletes and
    truncation unless the retention job has set ``omniosint.evidence_purge``.
    A correction is a new row that names the one it supersedes.
    """

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="RESTRICT"), nullable=False
    )
    relationship_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("evidence_sources.id", ondelete="RESTRICT"), nullable=False
    )
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("collection_jobs.id", ondelete="RESTRICT"), nullable=True
    )
    collection_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("collection_results.id", ondelete="RESTRICT"), nullable=True
    )
    observation_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    provider_object_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_pointer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'unverified'")
    )
    is_redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    transformation_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("evidence.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            _in("verification_status", VERIFICATION_STATUSES), name="verification_valid"
        ),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_hex"),
        CheckConstraint("raw_sha256 IS NULL OR raw_sha256 ~ '^[0-9a-f]{64}$'", name="raw_hex"),
        CheckConstraint("jsonb_typeof(transformation_history) = 'array'", name="history_is_array"),
        Index("ix_evidence_entity_id_collected_at", "entity_id", "collected_at"),
        Index("ix_evidence_job_id", "job_id"),
        Index("ix_evidence_collection_result_id", "collection_result_id"),
        Index("ix_evidence_source_id", "source_id"),
    )
