"""Cross-platform graceful shutdown requests.

Windows has no dependable equivalent of SIGTERM for a detached process without
a console. Instead of signals, ``omniosint stop`` writes a small request file
into the run directory; every OmniOSINT process watches for it and shuts down
cleanly. The same mechanism is used on Linux so there is one code path to test.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from pathlib import Path

from omniosint.core.paths import write_private_text
from omniosint.core.timeutil import isoformat, utcnow

REQUEST_FILE = "shutdown.request"
RUN_ID_ENV = "OMNIOSINT_RUN_ID"
_POLL_SECONDS = 0.5


def request_path(run_dir: Path) -> Path:
    return run_dir / REQUEST_FILE


def write_request(run_dir: Path, run_id: str) -> Path:
    """Ask every process belonging to ``run_id`` to stop."""
    path = request_path(run_dir)
    write_private_text(path, json.dumps({"run_id": run_id, "requested_at": isoformat(utcnow())}))
    return path


def clear_request(run_dir: Path) -> None:
    request_path(run_dir).unlink(missing_ok=True)


def read_request(run_dir: Path) -> str | None:
    """Run id named by a pending shutdown request, if there is one."""
    path = request_path(run_dir)
    try:
        return str(json.loads(path.read_text(encoding="utf-8"))["run_id"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


class ShutdownWatcher:
    """Calls ``on_request`` once a shutdown request for this run appears.

    A process started outside the supervisor has no run id and reacts to any
    request. A request for a different run is ignored, so a stale file left by
    an earlier run cannot stop a new one.
    """

    def __init__(
        self,
        run_dir: Path,
        run_id: str | None,
        on_request: Callable[[], None],
        *,
        poll_seconds: float = _POLL_SECONDS,
    ) -> None:
        self._run_dir = run_dir
        self._run_id = run_id
        self._on_request = on_request
        self._poll = poll_seconds
        self._task: asyncio.Task[None] | None = None

    def _requested(self) -> bool:
        requested_for = read_request(self._run_dir)
        if requested_for is None:
            return False
        return self._run_id is None or requested_for == self._run_id

    async def _run(self) -> None:
        while True:
            if self._requested():
                self._on_request()
                return
            await asyncio.sleep(self._poll)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="shutdown-watcher")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
