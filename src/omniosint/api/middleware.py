"""HTTP middleware (plain ASGI, no per-request task overhead).

Order, outermost first::

    RequestContext -> HostValidation -> SecurityHeaders -> BodySizeLimit -> OriginGuard -> app
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from typing import Any

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from omniosint.api.errors import error_response
from omniosint.core.ids import uuid7
from omniosint.core.logging import get_logger

log = get_logger("omniosint.access")

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)

PERMISSIONS_POLICY = ", ".join(
    f"{feature}=()"
    for feature in (
        "accelerometer",
        "camera",
        "geolocation",
        "gyroscope",
        "magnetometer",
        "microphone",
        "payment",
        "usb",
    )
)


def host_without_port(value: str) -> str:
    """``Host`` header value without its port; IPv6 literals lose their brackets."""
    host = value.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


class RequestContextMiddleware:
    """Assigns a request id, binds it to the log context and writes the access log."""

    def __init__(self, app: ASGIApp, *, access_log: bool = True) -> None:
        self.app = app
        self._access_log = access_log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = Headers(scope=scope).get("x-request-id", "")
        request_id = supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid7())
        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            if self._access_log:
                path = scope.get("path", "")
                duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
                principal = state.get("principal")
                fields = {
                    "method": scope.get("method"),
                    "path": path,
                    "status": status_code,
                    "duration_ms": duration_ms,
                    "user": getattr(principal, "username", None),
                }
                # Static assets and liveness probes are noise at INFO level.
                quiet = not path.startswith("/api/") or path.endswith("/health/live")
                if status_code >= 500:
                    log.error("request", **fields)
                elif quiet:
                    log.debug("request", **fields)
                else:
                    log.info("request", **fields)
            structlog.contextvars.unbind_contextvars("request_id", "user")


class HostValidationMiddleware:
    """Rejects requests whose ``Host`` header is not on the allow-list.

    This is the defence against DNS rebinding: a hostile web page can point its
    own domain at 127.0.0.1, but the browser will still send that domain in the
    ``Host`` header.
    """

    def __init__(self, app: ASGIApp, *, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self._allowed = frozenset(host_without_port(host) for host in allowed_hosts)
        self._allow_any = "*" in self._allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._allow_any:
            await self.app(scope, receive, send)
            return
        host = host_without_port(Headers(scope=scope).get("host", ""))
        if host not in self._allowed:
            response = error_response(
                400,
                "host_not_allowed",
                "The Host header of this request is not accepted.",
                request_id=scope.get("state", {}).get("request_id"),
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, csp_exempt_prefixes: tuple[str, ...] = ()) -> None:
        self.app = app
        self._csp_exempt = csp_exempt_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
                if not (self._csp_exempt and path.startswith(self._csp_exempt)):
                    headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
                if path.startswith("/api/"):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Caps request bodies, whether or not ``Content-Length`` was sent."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = scope.get("state", {}).get("request_id")
        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            try:
                too_large = int(declared) > self._max
            except ValueError:
                too_large = True
            if too_large:
                response = error_response(
                    413,
                    "payload_too_large",
                    "The request body is too large.",
                    request_id=request_id,
                )
                await response(scope, receive, send)
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                raise
            response = error_response(
                413, "payload_too_large", "The request body is too large.", request_id=request_id
            )
            await response(scope, receive, send)


class OriginGuardMiddleware:
    """Refuses state-changing API requests that come from another site.

    Three independent checks, all cheap:

    * a request body must be JSON, which a cross-site HTML form cannot send;
    * an ``Origin`` header, when present, must be this server or an explicitly
      allowed origin;
    * ``Sec-Fetch-Site``, when present, must not report another site.

    Clients that are not browsers send none of these headers and pass through;
    they authenticate with a bearer token, which is not sent automatically.
    """

    def __init__(self, app: ASGIApp, *, allowed_origins: Iterable[str] = ()) -> None:
        self.app = app
        self._allowed = frozenset(origin.rstrip("/").lower() for origin in allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in _UNSAFE_METHODS
            or not str(scope.get("path", "")).startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = scope.get("state", {}).get("request_id")

        has_body = headers.get("content-length") not in (None, "0") or bool(
            headers.get("transfer-encoding")
        )
        if has_body:
            media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                response = error_response(
                    415,
                    "unsupported_media_type",
                    "Request bodies must be sent as application/json.",
                    request_id=request_id,
                )
                await response(scope, receive, send)
                return

        origin = headers.get("origin")
        if origin is not None:
            own_origin = f"{scope.get('scheme', 'http')}://{headers.get('host', '')}".lower()
            candidate = origin.rstrip("/").lower()
            if candidate != own_origin and candidate not in self._allowed:
                await self._refuse(scope, receive, send, request_id)
                return
        elif headers.get("sec-fetch-site", "same-origin").lower() not in ("same-origin", "none"):
            await self._refuse(scope, receive, send, request_id)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send, request_id: str | None) -> None:
        response = error_response(
            403,
            "origin_not_allowed",
            "Requests from this origin are not accepted.",
            request_id=request_id,
        )
        await response(scope, receive, send)
