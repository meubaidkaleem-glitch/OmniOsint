"""Why a provider operation failed.

Every failure has a stable code, a message that is safe to show, and whether
trying again later can help. Job history records them as they are; a failure
is a normal result, never hidden or replaced with data.
"""

from __future__ import annotations

from typing import Any

from omniosint.core.errors import NOT_CONFIGURED_MESSAGE


class ProviderError(Exception):
    code = "provider_error"
    retryable = False
    default_message = "The provider operation failed."

    def __init__(
        self,
        message: str | None = None,
        *,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.retry_after = retry_after
        self.details = details or {}
        super().__init__(self.message)

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.retry_after is not None:
            result["retry_after"] = self.retry_after
        if self.details:
            result["details"] = self.details
        return result


class ProviderTimeout(ProviderError):
    code = "provider_timeout"
    retryable = True
    default_message = "The provider did not answer in time."


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"
    retryable = True
    default_message = "The provider is unavailable."


class ProviderRateLimited(ProviderError):
    code = "provider_rate_limited"
    retryable = True
    default_message = "The provider's rate limit was reached."


class CircuitOpen(ProviderError):
    code = "provider_circuit_open"
    retryable = True
    default_message = "The provider failed repeatedly and is paused before being tried again."


class ProviderQuotaExceeded(ProviderError):
    code = "provider_quota_exceeded"
    default_message = "The provider's quota for this account is used up."


class ProviderAuthFailed(ProviderError):
    code = "provider_auth_failed"
    default_message = "The provider refused the configured credentials."


class ProviderNotConfigured(ProviderError):
    code = "provider_not_configured"
    default_message = NOT_CONFIGURED_MESSAGE


class ProviderNotAvailable(ProviderError):
    """The adapter is not installed or not enabled."""

    code = "provider_not_available"
    default_message = "This provider is not available in this installation."


class ProviderRejectedInput(ProviderError):
    code = "provider_rejected_input"
    default_message = "The provider does not accept this indicator."


class ProviderMalformedResponse(ProviderError):
    code = "provider_malformed_response"
    default_message = "The provider's response could not be understood."


class ResponseTooLarge(ProviderError):
    code = "response_too_large"
    default_message = "The response was larger than the configured limit."


class DestinationBlocked(ProviderError):
    """The outbound request was refused by the destination policy (SSRF defence)."""

    code = "destination_blocked"
    default_message = "The destination is not a public Internet address."


class AdapterFailed(ProviderError):
    """The adapter raised something it should not have: a bug, logged in full."""

    code = "adapter_failed"
    default_message = "The adapter failed unexpectedly; the details are in the log."


class WorkerLost(ProviderError):
    """The worker running a job stopped renewing its lease (it crashed or was killed)."""

    code = "worker_lost"
    retryable = True
    default_message = "The worker running this job stopped before finishing."


class ScopeDenied(ProviderError):
    """An active operation was refused by the scope manager just before running."""

    code = "scope_denied"
    default_message = "The scope does not permit this operation."


class InternalCollectionError(ProviderError):
    code = "internal_error"
    default_message = "The job failed because of an internal error; the details are in the log."
