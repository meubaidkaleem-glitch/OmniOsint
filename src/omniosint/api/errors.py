"""Turns every failure into the one JSON error envelope."""

from __future__ import annotations

import socket
from typing import Any

import asyncpg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from omniosint.core.errors import AuthenticationRequired, OmniError
from omniosint.core.logging import get_logger
from omniosint.database.errors import as_omni_error

log = get_logger(__name__)

_HTTP_CODES: dict[int, tuple[str, str]] = {
    400: ("bad_request", "The request could not be understood."),
    401: ("authentication_required", "Sign in to continue."),
    403: ("permission_denied", "You do not have permission to perform this action."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "That method is not allowed for this resource."),
    406: ("not_acceptable", "The requested format is not available."),
    413: ("payload_too_large", "The request body is too large."),
    415: ("unsupported_media_type", "Request bodies must be sent as application/json."),
    429: ("rate_limited", "Too many requests. Wait a moment and try again."),
}


def request_id_of(scope_or_request: Any) -> str | None:
    scope = getattr(scope_or_request, "scope", scope_or_request)
    state = scope.get("state") if isinstance(scope, dict) else None
    if isinstance(state, dict):
        value = state.get("request_id")
        return str(value) if value else None
    return None


def error_body(
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    hint: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "details": details or [],
        "request_id": request_id,
    }
    if hint:
        error["hint"] = hint
    return {"error": error}


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    hint: str | None = None,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    all_headers = {"Cache-Control": "no-store", **(headers or {})}
    if request_id:
        all_headers["X-Request-ID"] = request_id
    return JSONResponse(
        error_body(code, message, details=details, hint=hint, request_id=request_id),
        status_code=status_code,
        headers=all_headers,
    )


def _session_cookie_name(request: Request) -> str | None:
    context = getattr(request.app.state, "ctx", None)
    return context.settings.auth.session_cookie_name if context is not None else None


async def _handle_omni_error(request: Request, exc: OmniError) -> JSONResponse:
    response = error_response(
        exc.status_code,
        exc.code,
        exc.message,
        details=exc.details,
        hint=exc.hint,
        request_id=request_id_of(request),
        headers=exc.headers,
    )
    if isinstance(exc, AuthenticationRequired):
        # The cookie no longer identifies a session; make the browser drop it.
        cookie_name = _session_cookie_name(request)
        if cookie_name and cookie_name in request.cookies:
            response.delete_cookie(cookie_name, path="/")
    return response


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ())]
        if location and location[0] in ("body", "query", "path", "header", "cookie"):
            source, location = location[0], location[1:]
        else:
            source = "body"
        # Submitted values are deliberately left out: they may be secrets.
        details.append(
            {
                "field": ".".join(location) or None,
                "in": source,
                "message": str(error.get("msg", "Invalid value.")).removeprefix("Value error, "),
                "type": error.get("type"),
            }
        )
    return error_response(
        422,
        "validation_failed",
        "The request contains invalid values.",
        details=details,
        request_id=request_id_of(request),
    )


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = _HTTP_CODES.get(exc.status_code, ("http_error", "The request failed."))
    return error_response(
        exc.status_code,
        code,
        message,
        request_id=request_id_of(request),
        headers=dict(exc.headers) if exc.headers else None,
    )


# Exception types that may mean "the database cannot be used right now".
_INFRASTRUCTURE_ERRORS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    socket.gaierror,
    SQLAlchemyError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


async def _handle_infrastructure_error(request: Request, exc: Exception) -> JSONResponse:
    """Answer database outages with a clean 503 instead of a server error.

    Anything that is not clearly a connectivity or schema problem is re-raised
    and handled as an unexpected error, so real bugs are still reported.
    """
    translated = as_omni_error(exc)
    if translated is None:
        raise exc
    log.warning(
        "request.database_unavailable",
        method=request.method,
        path=request.url.path,
        code=translated.code,
        error=type(exc).__name__,
    )
    return await _handle_omni_error(request, translated)


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    translated = as_omni_error(exc)
    if translated is not None:
        log.error(
            "request.database_error",
            method=request.method,
            path=request.url.path,
            code=translated.code,
            error=type(exc).__name__,
        )
        return await _handle_omni_error(request, translated)
    log.error(
        "request.unhandled_error",
        method=request.method,
        path=request.url.path,
        error=type(exc).__name__,
        exc_info=exc,
    )
    return error_response(
        500,
        "internal_error",
        "An unexpected error occurred. Quote the request id when reporting it.",
        request_id=request_id_of(request),
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OmniError, _handle_omni_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    for error_type in _INFRASTRUCTURE_ERRORS:
        app.add_exception_handler(error_type, _handle_infrastructure_error)
    app.add_exception_handler(Exception, _handle_unexpected)
