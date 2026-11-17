from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

import pytest

from omniosint.core.config import LoggingSettings
from omniosint.core.errors import (
    PLANNED_MESSAGE,
    InvalidCredentials,
    NotImplementedYet,
    RateLimited,
    ValidationFailed,
)
from omniosint.core.ids import uuid7, uuid7_timestamp_ms
from omniosint.core.logging import REDACTED, configure_logging, get_logger, is_sensitive_key, redact
from omniosint.core.pagination import (
    MAX_LIMIT,
    clamp_limit,
    decode_cursor,
    encode_cursor,
)
from omniosint.core.timeutil import ensure_utc, isoformat, utcnow


def test_uuid7_layout_and_order() -> None:
    values = [uuid7() for _ in range(2000)]
    assert all(value.version == 7 for value in values)
    assert all(value.variant == uuid.RFC_4122 for value in values)
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    assert abs(uuid7_timestamp_ms(values[0]) - time.time() * 1000) < 5000
    with pytest.raises(ValueError, match="version 7"):
        uuid7_timestamp_ms(uuid.uuid4())


def test_cursor_round_trip() -> None:
    cursor = encode_cursor(["2026-01-01T00:00:00Z", "id-1"])
    assert decode_cursor(cursor, parts=2) == ["2026-01-01T00:00:00Z", "id-1"]


@pytest.mark.parametrize("cursor", ["%%%", "bm90IGpzb24", encode_cursor(["one"]), "e30"])
def test_invalid_cursors_are_validation_errors(cursor: str) -> None:
    with pytest.raises(ValidationFailed):
        decode_cursor(cursor, parts=2)


def test_clamp_limit() -> None:
    assert clamp_limit(None) == 50
    assert clamp_limit(0) == 1
    assert clamp_limit(10_000) == MAX_LIMIT


def test_time_helpers() -> None:
    now = utcnow()
    assert now.tzinfo is not None
    naive = now.replace(tzinfo=None)
    assert ensure_utc(naive) == now
    assert isoformat(now) is not None and isoformat(now).endswith("Z")  # type: ignore[union-attr]
    assert isoformat(None) is None


@pytest.mark.parametrize(
    "key",
    ["password", "new_password", "Authorization", "api_key", "session", "x-csrf-token", "TOKEN"],
)
def test_sensitive_keys(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", ["username", "path", "status", "token_count_label", 5])
def test_non_sensitive_keys(key: object) -> None:
    assert not is_sensitive_key(key)


def test_redact_nested_structures() -> None:
    data = {
        "user": "alice",
        "password": "p",
        "nested": {"api_key": "k", "items": [{"token": "t", "ok": 1}]},
    }
    assert redact(data) == {
        "user": "alice",
        "password": REDACTED,
        "nested": {"api_key": REDACTED, "items": [{"token": REDACTED, "ok": 1}]},
    }


def test_flags_and_empty_values_are_not_masked() -> None:
    data = {"must_change_password": True, "password": None, "token": "", "api_key": 0}
    assert redact(data) == {
        "must_change_password": True,
        "password": None,
        "token": REDACTED,
        "api_key": REDACTED,
    }


def test_log_file_is_json_and_redacted(tmp_path: Path) -> None:
    configure_logging(
        LoggingSettings(file_enabled=True, console_format="json"),
        service="unit-test",
        logs_dir=tmp_path,
        console=False,
    )
    get_logger("test").warning(
        "something.happened", password="hunter2-canary", detail={"token": "tok-canary"}, user="bob"
    )
    for handler in logging.getLogger().handlers:
        handler.flush()
    line = (tmp_path / "unit-test.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "something.happened"
    assert record["service"] == "unit-test"
    assert record["user"] == "bob"
    assert "hunter2-canary" not in line and "tok-canary" not in line


def test_error_envelopes() -> None:
    assert InvalidCredentials().to_dict()["code"] == "invalid_credentials"
    limited = RateLimited(retry_after=7)
    assert limited.headers == {"Retry-After": "7"}
    planned = NotImplementedYet("Graph export", phase=7)
    assert PLANNED_MESSAGE in planned.message and "Phase 7" in planned.message
    assert planned.status_code == 501
