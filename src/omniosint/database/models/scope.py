"""Scopes: written authorisation for active operations.

Investigations arrive in Phase 3; until then a scope stands on its own, and
the Phase 3 migration links scopes to cases.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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

SCOPE_MODES = ("passive", "authorized_discovery", "active_assessment")
RULE_KINDS = ("domain", "wildcard", "ip", "cidr", "url_prefix")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


class Scope(Base):
    __tablename__ = "scopes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    authorized_by: Mapped[str] = mapped_column(String(256), nullable=False)
    authorization_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    authorization_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(_in("mode", SCOPE_MODES), name="mode_valid"),
        CheckConstraint("valid_until > valid_from", name="validity_ordered"),
        CheckConstraint("length(trim(authorized_by)) > 0", name="authorized_by_given"),
        Index("ix_scopes_valid_until", "valid_until"),
    )


class ScopeRule(Base):
    """A target the scope covers, or an exclusion. Exclusions always win."""

    __tablename__ = "scope_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    scope_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scopes.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_exclusion: Mapped[bool] = mapped_column(Boolean, nullable=False)
    restrictions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(_in("kind", RULE_KINDS), name="kind_valid"),
        UniqueConstraint(
            "scope_id", "kind", "value", "is_exclusion", name="uq_scope_rules_scope_id_kind_value"
        ),
    )
