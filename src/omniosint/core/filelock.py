"""A cross-process lock based on exclusive file creation (Windows and POSIX)."""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from pathlib import Path


class LockTimeout(TimeoutError):
    pass


@contextlib.contextmanager
def exclusive_lock(
    path: Path, *, timeout: float = 10.0, stale_after: float = 120.0
) -> Iterator[None]:
    """Hold ``path`` as a lock file. A lock older than ``stale_after`` seconds is
    assumed to belong to a process that died and is taken over."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > stale_after:
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() > deadline:
                raise LockTimeout(f"Timed out waiting for the lock {path}.") from None
            time.sleep(0.02)
            continue
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
        finally:
            os.close(descriptor)
        break
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
