"""Keyset (cursor) pagination helpers.

List endpoints page by an opaque cursor rather than an offset: results stay
stable while rows are inserted, and cost does not grow with page number.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from omniosint.core.errors import ValidationFailed

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None
    total: int | None = None


def encode_cursor(values: Sequence[Any]) -> str:
    raw = json.dumps(list(values), separators=(",", ":"), default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, *, parts: int) -> list[Any]:
    """Decode a cursor produced by :func:`encode_cursor`.

    A cursor is client-supplied input: anything malformed is a validation error,
    never a server error.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise ValidationFailed(
            "The cursor is not valid.", details=[{"field": "cursor", "message": "Invalid cursor."}]
        ) from exc
    if not isinstance(values, list) or len(values) != parts:
        raise ValidationFailed(
            "The cursor is not valid.", details=[{"field": "cursor", "message": "Invalid cursor."}]
        )
    return values


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, limit))
