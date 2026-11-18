"""Schemas shared by every router."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for response models: built from ORM objects and dataclasses."""

    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = []
    hint: str | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# Reusable OpenAPI response declarations.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in, or the session has ended."},
    403: {"model": ErrorResponse, "description": "Not permitted."},
    422: {"model": ErrorResponse, "description": "The request contains invalid values."},
    404: {"model": ErrorResponse, "description": "Not found."},
    409: {"model": ErrorResponse, "description": "The change conflicts with the current state."},
    503: {"model": ErrorResponse, "description": "A required service is unavailable."},
}
