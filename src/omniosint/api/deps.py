"""FastAPI dependencies: context, database session, caller identity, permissions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.api.context import AppContext
from omniosint.audit.service import RequestInfo, record
from omniosint.auth.permissions import Permission
from omniosint.auth.service import Principal
from omniosint.auth.tokens import derive_csrf_token, tokens_equal
from omniosint.collection.runtime import IntelRuntime
from omniosint.core.errors import (
    AuthenticationRequired,
    CsrfFailed,
    PasswordChangeRequired,
    PermissionDenied,
    ServiceUnavailable,
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-csrf-token"


def get_context(request: Request) -> AppContext:
    context: AppContext = request.app.state.ctx
    return context


ContextDep = Annotated[AppContext, Depends(get_context)]


def get_intel(context: ContextDep) -> IntelRuntime:
    if context.intel is None:
        raise ServiceUnavailable("Collection is not available: the service is still starting.")
    return context.intel


IntelDep = Annotated[IntelRuntime, Depends(get_intel)]


async def get_session(context: ContextDep) -> AsyncIterator[AsyncSession]:
    """One database session per request.

    Services own their transactions and commit themselves; this dependency only
    guarantees that an abandoned transaction is rolled back and the connection
    is returned to the pool.
    """
    session = context.db.session()
    try:
        yield session
    finally:
        await session.close()


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_request_info(request: Request) -> RequestInfo:
    client = request.client
    return RequestInfo(
        ip_address=client.host if client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


RequestInfoDep = Annotated[RequestInfo, Depends(get_request_info)]


def extract_token(request: Request, cookie_name: str) -> tuple[str | None, str]:
    """Return ``(token, method)`` where method is ``bearer`` or ``cookie``."""
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip(), "bearer"
    cookie = request.cookies.get(cookie_name)
    if cookie:
        return cookie, "cookie"
    return None, ""


async def get_principal(request: Request, context: ContextDep, session: SessionDep) -> Principal:
    """Authenticate the caller. Cookie sessions must also pass the CSRF check."""
    token, method = extract_token(request, context.settings.auth.session_cookie_name)
    if token is None:
        raise AuthenticationRequired()
    principal, _session_row = await context.auth.authenticate(session, token)

    if method == "cookie" and request.method not in _SAFE_METHODS:
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not tokens_equal(supplied, derive_csrf_token(token)):
            raise CsrfFailed()

    request.state.principal = principal
    request.state.session_token = token
    request.state.token_method = method
    structlog.contextvars.bind_contextvars(user=principal.username)
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def get_active_principal(principal: PrincipalDep) -> Principal:
    """A signed-in caller who is not required to change their password first."""
    if principal.must_change_password:
        raise PasswordChangeRequired()
    return principal


ActivePrincipalDep = Annotated[Principal, Depends(get_active_principal)]


def require(permission: Permission) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: the caller must hold ``permission``. Denials are audited."""

    async def checker(
        request: Request,
        principal: ActivePrincipalDep,
        session: SessionDep,
        info: RequestInfoDep,
    ) -> Principal:
        if not principal.has(permission.value):
            record(
                session,
                action="authz.denied",
                actor=principal.actor,
                outcome="denied",
                details={
                    "permission": permission.value,
                    "method": request.method,
                    "path": request.url.path,
                },
                request=info,
            )
            await session.commit()
            raise PermissionDenied()
        return principal

    return checker


def permission_doc(permission: Permission) -> dict[str, str]:
    """OpenAPI extension recording which permission an operation needs."""
    return {"x-permission": permission.value}


PUBLIC_DOC: dict[str, str] = {"x-access": "public"}
