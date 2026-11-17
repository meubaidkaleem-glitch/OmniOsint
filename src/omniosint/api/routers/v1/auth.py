"""Authentication and the caller's own account."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status

from omniosint.api.context import AppContext
from omniosint.api.deps import PUBLIC_DOC, ContextDep, PrincipalDep, RequestInfoDep, SessionDep
from omniosint.api.schemas.auth import (
    AuthState,
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    LoginResponse,
    SessionInfo,
    SessionList,
    SessionOut,
    SetupRequest,
    SetupResponse,
    SetupStatus,
    UserOut,
)
from omniosint.api.schemas.common import ERROR_RESPONSES, ErrorResponse
from omniosint.auth.service import principal_from
from omniosint.auth.tokens import derive_csrf_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, context: AppContext, token: str) -> None:
    auth = context.settings.auth
    response.set_cookie(
        key=auth.session_cookie_name,
        value=token,
        max_age=auth.session_ttl_hours * 3600,
        path="/",
        httponly=True,
        secure=auth.cookie_secure,
        samesite="strict",
    )


def _clear_session_cookie(response: Response, context: AppContext) -> None:
    response.delete_cookie(context.settings.auth.session_cookie_name, path="/")


@router.get(
    "/setup-status",
    response_model=SetupStatus,
    summary="Whether first-run setup is still needed",
    openapi_extra=PUBLIC_DOC,
)
async def setup_status(context: ContextDep, session: SessionDep) -> SetupStatus:
    required = await context.auth.setup_required(session)
    if required:
        await context.auth.ensure_setup_token(session, context.paths)
    return SetupStatus(
        setup_required=required,
        token_file=str(context.paths.setup_token_file) if required else None,
    )


@router.post(
    "/setup",
    response_model=SetupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the first administrator",
    description=(
        "Works exactly once, while no user exists, and only with the setup token that "
        "OmniOSINT wrote to a file readable by the installing user."
    ),
    openapi_extra=PUBLIC_DOC,
    responses={
        403: {"model": ErrorResponse, "description": "The setup token is not valid."},
        409: {"model": ErrorResponse, "description": "Setup has already been completed."},
        429: {"model": ErrorResponse, "description": "Too many attempts."},
    },
)
async def complete_setup(
    payload: SetupRequest, context: ContextDep, session: SessionDep, info: RequestInfoDep
) -> SetupResponse:
    user = await context.auth.complete_setup(
        session,
        setup_token=payload.setup_token,
        username=payload.username,
        display_name=payload.display_name,
        email=payload.email,
        password=payload.password,
        paths=context.paths,
        request=info,
    )
    return SetupResponse(user=UserOut.from_user(user))


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Sign in",
    openapi_extra=PUBLIC_DOC,
    responses={
        401: {"model": ErrorResponse, "description": "Wrong credentials or locked account."},
        429: {"model": ErrorResponse, "description": "Too many attempts."},
    },
)
async def login(
    payload: LoginRequest,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> LoginResponse:
    result = await context.auth.login(
        session,
        username=payload.username,
        password=payload.password,
        client_type=payload.client,
        auth_method=payload.session_type,
        request=info,
    )
    principal = principal_from(result.user, result.session)
    is_cookie = payload.session_type == "cookie"
    if is_cookie:
        _set_session_cookie(response, context, result.token)
    return LoginResponse(
        user=UserOut.from_user(result.user),
        permissions=sorted(principal.permissions),
        session=SessionInfo(
            id=result.session.id,
            auth_method=result.session.auth_method,
            expires_at=result.session.expires_at,
        ),
        csrf_token=result.csrf_token if is_cookie else None,
        access_token=None if is_cookie else result.token,
        token_type=None if is_cookie else "bearer",
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    responses={401: ERROR_RESPONSES[401]},
)
async def logout(
    response: Response,
    principal: PrincipalDep,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> None:
    await context.auth.logout(session, principal, info)
    _clear_session_cookie(response, context)


@router.get(
    "/me",
    response_model=AuthState,
    summary="The signed-in user, their permissions and CSRF token",
    responses={401: ERROR_RESPONSES[401]},
)
async def me(
    request: Request, principal: PrincipalDep, context: ContextDep, session: SessionDep
) -> AuthState:
    user = await context.users.get_user(session, principal.user_id)
    is_cookie = request.state.token_method == "cookie"
    return AuthState(
        user=UserOut.from_user(user),
        permissions=sorted(principal.permissions),
        session=SessionInfo(
            id=principal.session_id,
            auth_method=principal.auth_method,
            expires_at=principal.session_expires_at,
        ),
        csrf_token=derive_csrf_token(request.state.session_token) if is_cookie else None,
    )


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    summary="Change your password",
    description="Ends every other session of the same user.",
    responses={401: ERROR_RESPONSES[401], 422: ERROR_RESPONSES[422]},
)
async def change_password(
    payload: ChangePasswordRequest,
    principal: PrincipalDep,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> ChangePasswordResponse:
    ended = await context.auth.change_password(
        session,
        principal,
        current_password=payload.current_password,
        new_password=payload.new_password,
        request=info,
    )
    return ChangePasswordResponse(other_sessions_ended=ended)


@router.get(
    "/sessions",
    response_model=SessionList,
    summary="Your active sessions",
    responses={401: ERROR_RESPONSES[401]},
)
async def list_sessions(
    principal: PrincipalDep, context: ContextDep, session: SessionDep
) -> SessionList:
    rows = await context.auth.list_sessions(session, principal.user_id)
    return SessionList(
        items=[SessionOut.from_row(row, current_id=principal.session_id) for row in rows]
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End one of your sessions",
    responses={401: ERROR_RESPONSES[401], 404: {"model": ErrorResponse}},
)
async def revoke_session(
    session_id: uuid.UUID,
    response: Response,
    principal: PrincipalDep,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> None:
    await context.auth.revoke_session(session, principal, session_id, info)
    if session_id == principal.session_id:
        _clear_session_cookie(response, context)
