"""Application error types.

Every error the platform raises on purpose derives from :class:`OmniError` and
carries a stable machine-readable ``code``. The API turns these into one JSON
envelope; the CLI turns them into a message and an exit code. Messages are for
people and must never contain secrets or internal details.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# Exact status texts required by the brief (section 26.5).
PLANNED_MESSAGE = "Planned \u2014 integration not yet implemented."
NOT_CONFIGURED_MESSAGE = "Not configured \u2014 API credentials required."


class OmniError(Exception):
    """Base class for expected, user-facing failures."""

    code: str = "error"
    status_code: int = 500
    default_message: str = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Sequence[dict[str, Any]] | None = None,
        hint: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details: list[dict[str, Any]] = list(details or [])
        self.hint = hint
        self.headers = headers or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }
        if self.hint:
            body["hint"] = self.hint
        return body


class ConfigurationError(OmniError):
    code = "configuration_invalid"
    status_code = 500
    default_message = "The configuration is invalid."


class ValidationFailed(OmniError):
    code = "validation_failed"
    status_code = 422
    default_message = "The request contains invalid values."


class AuthenticationRequired(OmniError):
    code = "authentication_required"
    status_code = 401
    default_message = "Sign in to continue."


class SessionInvalid(AuthenticationRequired):
    code = "session_invalid"
    default_message = "Your session is no longer valid. Sign in again."


class SessionExpired(AuthenticationRequired):
    code = "session_expired"
    default_message = "Your session has expired. Sign in again."


class InvalidCredentials(OmniError):
    code = "invalid_credentials"
    status_code = 401
    default_message = (
        "The username or password is incorrect, or the account is temporarily locked."
    )


class CsrfFailed(OmniError):
    code = "csrf_failed"
    status_code = 403
    default_message = "The request could not be verified. Reload the page and try again."


class OriginNotAllowed(OmniError):
    code = "origin_not_allowed"
    status_code = 403
    default_message = "Requests from this origin are not accepted."


class PermissionDenied(OmniError):
    code = "permission_denied"
    status_code = 403
    default_message = "You do not have permission to perform this action."


class PasswordChangeRequired(OmniError):
    code = "password_change_required"
    status_code = 403
    default_message = "You must change your password before continuing."


class NotFound(OmniError):
    code = "not_found"
    status_code = 404
    default_message = "The requested resource was not found."


class Conflict(OmniError):
    code = "conflict"
    status_code = 409
    default_message = "The request conflicts with the current state."


class SetupAlreadyCompleted(Conflict):
    code = "setup_already_completed"
    default_message = "Initial setup has already been completed."


class LastAdministrator(Conflict):
    code = "last_administrator"
    default_message = "This change would leave the system without an active administrator."


class PayloadTooLarge(OmniError):
    code = "payload_too_large"
    status_code = 413
    default_message = "The request body is too large."


class UnsupportedMediaType(OmniError):
    code = "unsupported_media_type"
    status_code = 415
    default_message = "Request bodies must be sent as application/json."


class RateLimited(OmniError):
    code = "rate_limited"
    status_code = 429
    default_message = "Too many attempts. Wait a moment and try again."

    def __init__(self, message: str | None = None, *, retry_after: int = 60) -> None:
        super().__init__(message, headers={"Retry-After": str(max(1, retry_after))})
        self.retry_after = retry_after


class NotImplementedYet(OmniError):
    """A capability that is on the roadmap but has no implementation."""

    code = "planned_not_implemented"
    status_code = 501
    default_message = PLANNED_MESSAGE

    def __init__(self, feature: str, *, phase: int | None = None) -> None:
        suffix = f" Scheduled for Phase {phase}." if phase is not None else ""
        super().__init__(f"{feature}: {PLANNED_MESSAGE}{suffix}")
        self.feature = feature
        self.phase = phase


class ServiceUnavailable(OmniError):
    code = "service_unavailable"
    status_code = 503
    default_message = "A required service is unavailable."


class DatabaseUnavailable(ServiceUnavailable):
    code = "database_unavailable"
    default_message = "The database is not reachable."


class SchemaOutOfDate(ServiceUnavailable):
    code = "schema_out_of_date"
    default_message = "The database schema is not up to date."


class ExternalToolError(OmniError):
    code = "external_tool_failed"
    status_code = 500
    default_message = "A required external tool failed or is not installed."
