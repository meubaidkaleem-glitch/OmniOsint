"""Administration schemas: users, roles, audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from omniosint.api.schemas.auth import UserOut
from omniosint.database.models import AuditEvent


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(default="", max_length=128)
    email: EmailStr | None = None
    password: str = Field(min_length=1, max_length=256)
    roles: list[str] = Field(min_length=1, max_length=16)
    must_change_password: bool = Field(
        default=True, description="Require a new password at first sign-in."
    )


class UserUpdate(BaseModel):
    """Only the fields that are sent are changed. Send `email: null` to remove it."""

    display_name: str | None = Field(default=None, max_length=128)
    email: EmailStr | None = None
    is_active: bool | None = None
    roles: list[str] | None = Field(default=None, min_length=1, max_length=16)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)
    must_change_password: bool = True


class UserList(BaseModel):
    items: list[UserOut]
    next_cursor: str | None
    total: int


class PermissionOut(BaseModel):
    code: str
    description: str


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    is_system: bool
    permissions: list[PermissionOut]
    member_count: int


class RoleList(BaseModel):
    items: list[RoleOut]


class AuditEventOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    category: str
    action: str
    outcome: str
    actor_user_id: uuid.UUID | None
    actor_label: str
    target_type: str | None
    target_id: str | None
    ip_address: str | None
    user_agent: str | None
    request_id: str | None
    details: dict[str, Any]

    @classmethod
    def from_event(cls, event: AuditEvent) -> AuditEventOut:
        return cls(
            id=event.id,
            occurred_at=event.occurred_at,
            category=event.category,
            action=event.action,
            outcome=event.outcome,
            actor_user_id=event.actor_user_id,
            actor_label=event.actor_label,
            target_type=event.target_type,
            target_id=event.target_id,
            ip_address=event.ip_address,
            user_agent=event.user_agent,
            request_id=event.request_id,
            details=event.details,
        )


class AuditEventList(BaseModel):
    items: list[AuditEventOut]
    next_cursor: str | None
