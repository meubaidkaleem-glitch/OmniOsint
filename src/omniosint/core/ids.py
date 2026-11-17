"""Identifier helpers."""

from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """Return a time-ordered UUID (RFC 9562, version 7).

    Rows keyed this way are inserted in roughly ascending order, which keeps
    B-tree indexes on large append-only tables (audit events, evidence,
    observations) compact. Values created in the same millisecond by one
    process are strictly increasing thanks to a 12-bit counter in ``rand_a``.
    """
    global _last_ms, _counter
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms > _last_ms:
            _last_ms = now_ms
            _counter = int.from_bytes(os.urandom(2), "big") & 0x07FF
        else:
            _counter += 1
            if _counter > 0x0FFF:
                # Counter exhausted for this millisecond: move the clock forward.
                _last_ms += 1
                _counter = int.from_bytes(os.urandom(2), "big") & 0x07FF
        timestamp_ms = _last_ms
        rand_a = _counter

    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFF_FFFF_FFFF_FFFF
    value = (timestamp_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)


def uuid7_timestamp_ms(value: uuid.UUID) -> int:
    """Extract the millisecond timestamp from a version 7 UUID."""
    if value.version != 7:
        raise ValueError("not a version 7 UUID")
    return value.int >> 80
