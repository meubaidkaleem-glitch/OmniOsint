"""Administration: users, roles and the audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status

from omniosint.api.deps import ContextDep, RequestInfoDep, SessionDep, permission_doc, require
from omniosint.api.schemas.admin import (
    AuditEventList,
    AuditEventOut,
    PasswordReset,
    PermissionOut,
    RoleList,
    RoleOut,
    UserCreate,
    UserList,
    UserUpdate,
)
from omniosint.api.schemas.auth import UserOut
from omniosint.api.schemas.common import ERROR_RESPONSES, ErrorResponse
from omniosint.audit import service as audit
from omniosint.auth.permissions import Permission
from omniosint.auth.service import Principal
from omniosint.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from omniosint.users.service import UNSET

router = APIRouter(prefix="/admin", tags=["admin"])

CanReadUsers = Annotated[Principal, Depends(require(Permission.USERS_READ))]
CanManageUsers = Annotated[Principal, Depends(require(Permission.USERS_MANAGE))]
CanReadRoles = Annotated[Principal, Depends(require(Permission.ROLES_READ))]
CanReadAudit = Annotated[Principal, Depends(require(Permission.AUDIT_READ))]

LimitQuery = Annotated[
    int, Query(ge=1, le=MAX_LIMIT, description="Maximum number of items to return.")
]
CursorQuery = Annotated[
    str | None,
    Query(max_length=512, description="Opaque cursor from a previous page's `next_cursor`."),
]

_AUTH_ERRORS: dict[int | str, dict[str, Any]] = {
    401: ERROR_RESPONSES[401],
    403: ERROR_RESPONSES[403],
}
_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such user."}
}
_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorResponse, "description": "The change conflicts with the current state."}
}


# --------------------------------------------------------------------------- users
@router.get(
    "/users",
    response_model=UserList,
    summary="List users",
    openapi_extra=permission_doc(Permission.USERS_READ),
    responses=_AUTH_ERRORS,
)
async def list_users(
    _principal: CanReadUsers,
    context: ContextDep,
    session: SessionDep,
    limit: LimitQuery = DEFAULT_LIMIT,
    cursor: CursorQuery = None,
    search: Annotated[
        str | None,
        Query(max_length=128, description="Matches username, display name or email."),
    ] = None,
) -> UserList:
    page = await context.users.list_users(session, limit=limit, cursor=cursor, search=search)
    return UserList(
        items=[UserOut.from_user(user) for user in page.items],
        next_cursor=page.next_cursor,
        total=page.total or 0,
    )


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    openapi_extra=permission_doc(Permission.USERS_MANAGE),
    responses={**_AUTH_ERRORS, **_CONFLICT},
)
async def create_user(
    payload: UserCreate,
    principal: CanManageUsers,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> UserOut:
    user = await context.users.create_user(
        session,
        actor=principal.actor,
        username=payload.username,
        display_name=payload.display_name,
        email=payload.email,
        password=payload.password,
        roles=payload.roles,
        must_change_password=payload.must_change_password,
        request=info,
    )
    return UserOut.from_user(user)


@router.get(
    "/users/{user_id}",
    response_model=UserOut,
    summary="Get a user",
    openapi_extra=permission_doc(Permission.USERS_READ),
    responses={**_AUTH_ERRORS, **_NOT_FOUND},
)
async def get_user(
    user_id: uuid.UUID, _principal: CanReadUsers, context: ContextDep, session: SessionDep
) -> UserOut:
    return UserOut.from_user(await context.users.get_user(session, user_id))


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    summary="Change a user",
    description=(
        "Only the fields sent are changed. A change that would leave no active "
        "administrator is refused."
    ),
    openapi_extra=permission_doc(Permission.USERS_MANAGE),
    responses={**_AUTH_ERRORS, **_NOT_FOUND, **_CONFLICT},
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    principal: CanManageUsers,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> UserOut:
    sent = payload.model_fields_set
    user = await context.users.update_user(
        session,
        user_id,
        actor=principal.actor,
        display_name=payload.display_name
        if "display_name" in sent and payload.display_name is not None
        else UNSET,
        email=payload.email if "email" in sent else UNSET,
        is_active=payload.is_active
        if "is_active" in sent and payload.is_active is not None
        else UNSET,
        roles=payload.roles if "roles" in sent and payload.roles is not None else UNSET,
        request=info,
    )
    return UserOut.from_user(user)


@router.post(
    "/users/{user_id}/reset-password",
    response_model=UserOut,
    summary="Set a new password for a user",
    description="Ends all of the user's sessions and clears any lockout.",
    openapi_extra=permission_doc(Permission.USERS_MANAGE),
    responses={**_AUTH_ERRORS, **_NOT_FOUND},
)
async def reset_password(
    user_id: uuid.UUID,
    payload: PasswordReset,
    principal: CanManageUsers,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> UserOut:
    user = await context.users.reset_password(
        session,
        user_id,
        actor=principal.actor,
        new_password=payload.new_password,
        must_change_password=payload.must_change_password,
        request=info,
    )
    return UserOut.from_user(user)


@router.post(
    "/users/{user_id}/unlock",
    response_model=UserOut,
    summary="Clear a sign-in lockout",
    openapi_extra=permission_doc(Permission.USERS_MANAGE),
    responses={**_AUTH_ERRORS, **_NOT_FOUND},
)
async def unlock_user(
    user_id: uuid.UUID,
    principal: CanManageUsers,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> UserOut:
    user = await context.users.unlock_user(session, user_id, actor=principal.actor, request=info)
    return UserOut.from_user(user)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
    description=(
        "The account is deactivated and can no longer sign in. Its username stays "
        "reserved so that earlier audit entries remain unambiguous."
    ),
    openapi_extra=permission_doc(Permission.USERS_MANAGE),
    responses={**_AUTH_ERRORS, **_NOT_FOUND, **_CONFLICT},
)
async def delete_user(
    user_id: uuid.UUID,
    principal: CanManageUsers,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> None:
    await context.users.delete_user(session, user_id, actor=principal.actor, request=info)


# --------------------------------------------------------------------------- roles
@router.get(
    "/roles",
    response_model=RoleList,
    summary="List roles and their permissions",
    openapi_extra=permission_doc(Permission.ROLES_READ),
    responses=_AUTH_ERRORS,
)
async def list_roles(
    _principal: CanReadRoles, context: ContextDep, session: SessionDep
) -> RoleList:
    roles = await context.users.list_roles(session)
    counts = await context.users.role_member_counts(session)
    return RoleList(
        items=[
            RoleOut(
                id=role.id,
                name=role.name,
                description=role.description,
                is_system=role.is_system,
                permissions=[
                    PermissionOut(code=permission.code, description=permission.description)
                    for permission in role.permissions
                ],
                member_count=counts.get(role.id, 0),
            )
            for role in roles
        ]
    )


# --------------------------------------------------------------------------- audit
@router.get(
    "/audit-events",
    response_model=AuditEventList,
    summary="Read the audit trail",
    description="Newest first.",
    openapi_extra=permission_doc(Permission.AUDIT_READ),
    responses=_AUTH_ERRORS,
)
async def list_audit_events(
    _principal: CanReadAudit,
    session: SessionDep,
    limit: LimitQuery = DEFAULT_LIMIT,
    cursor: CursorQuery = None,
    category: Annotated[str | None, Query(max_length=32)] = None,
    action: Annotated[str | None, Query(max_length=96)] = None,
    outcome: Annotated[Literal["success", "failure", "denied"] | None, Query()] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query()] = None,
    since: Annotated[datetime | None, Query(description="Inclusive lower bound.")] = None,
    until: Annotated[datetime | None, Query(description="Exclusive upper bound.")] = None,
) -> AuditEventList:
    page = await audit.list_events(
        session,
        limit=limit,
        cursor=cursor,
        category=category,
        action=action,
        outcome=outcome,
        actor_user_id=actor_user_id,
        since=since,
        until=until,
    )
    return AuditEventList(
        items=[AuditEventOut.from_event(event) for event in page.items],
        next_cursor=page.next_cursor,
    )
