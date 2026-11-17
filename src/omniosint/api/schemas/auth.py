"""Authentication and account schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from omniosint.api.schemas.common import ApiModel
from omniosint.database.models import User, UserSession


class UserOut(ApiModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    is_active: bool
    must_change_password: bool
    roles: list[str]
    locked_until: datetime | None
    last_login_at: datetime | None
    password_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            is_active=user.is_active,
            must_change_password=user.must_change_password,
            roles=user.role_names,
            locked_until=user.locked_until,
            last_login_at=user.last_login_at,
            password_changed_at=user.password_changed_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class SetupStatus(BaseModel):
    setup_required: bool
    token_file: str | None = Field(
        default=None,
        description="Where the one-time setup token is stored on this machine.",
    )


class SetupRequest(BaseModel):
    setup_token: str = Field(min_length=8, max_length=256)
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(default="", max_length=128)
    email: EmailStr | None = None
    password: str = Field(min_length=1, max_length=256)


class SetupResponse(BaseModel):
    user: UserOut


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    session_type: Literal["cookie", "bearer"] = Field(
        default="cookie",
        description=(
            "`cookie` for browsers (HttpOnly cookie, CSRF token required on changes); "
            "`bearer` for the CLI, desktop shell and scripts (token returned once)."
        ),
    )
    client: Literal["web", "cli", "desktop", "api"] = "web"


class SessionInfo(BaseModel):
    id: uuid.UUID
    auth_method: str
    expires_at: datetime


class AuthState(BaseModel):
    user: UserOut
    permissions: list[str]
    session: SessionInfo
    csrf_token: str | None = Field(
        default=None,
        description="Send as the X-CSRF-Token header on changes. Null for bearer sessions.",
    )


class LoginResponse(AuthState):
    access_token: str | None = Field(
        default=None, description="Present only for `bearer` sessions. Shown once."
    )
    token_type: Literal["bearer"] | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ChangePasswordResponse(BaseModel):
    other_sessions_ended: int


class SessionOut(BaseModel):
    id: uuid.UUID
    client_type: str
    auth_method: str
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool

    @classmethod
    def from_row(cls, row: UserSession, *, current_id: uuid.UUID) -> SessionOut:
        return cls(
            id=row.id,
            client_type=row.client_type,
            auth_method=row.auth_method,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            current=row.id == current_id,
        )


class SessionList(BaseModel):
    items: list[SessionOut]
