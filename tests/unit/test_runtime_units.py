"""Process control pieces that do not need a database."""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import time

import psutil
import pytest

from omniosint.api.middleware import host_without_port
from omniosint.core.paths import AppPaths, write_private_text
from omniosint.database.errors import as_omni_error
from omniosint.runtime import shutdown, supervisor
from omniosint.runtime.supervisor import ManagedProcess, RunState
from omniosint.system.health import describe_database_error


def test_run_state_round_trip(app_paths: AppPaths) -> None:
    state = RunState(
        run_id="abc",
        started_at="2026-01-01T00:00:00Z",
        version="0.1.0",
        url="http://127.0.0.1:8765",
        processes=[ManagedProcess("api", 1, 2.0, ["python"], "api.log")],
    )
    supervisor.write_state(app_paths, state)
    loaded = supervisor.read_state(app_paths)
    assert loaded == state
    supervisor.clear_state(app_paths)
    assert supervisor.read_state(app_paths) is None


def test_unreadable_state_is_treated_as_absent(app_paths: AppPaths) -> None:
    write_private_text(supervisor.state_path(app_paths), "{not json")
    assert supervisor.read_state(app_paths) is None


def test_is_alive_checks_creation_time() -> None:
    me = psutil.Process(os.getpid())
    alive = ManagedProcess("self", me.pid, me.create_time(), [], "")
    assert supervisor.is_alive(alive)
    recycled = ManagedProcess("self", me.pid, me.create_time() - 3600, [], "")
    assert not supervisor.is_alive(recycled), "a reused PID must not count as ours"
    gone = ManagedProcess("gone", 2**22 + 12345, time.time(), [], "")
    assert not supervisor.is_alive(gone)


def test_port_available_detects_a_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert not supervisor.port_available("127.0.0.1", port)
    assert supervisor.port_available("127.0.0.1", port)


def test_stop_without_state_is_a_no_op(app_paths: AppPaths, settings: object) -> None:
    result = supervisor.stop(settings, app_paths)  # type: ignore[arg-type]
    assert result.was_running is False


def test_shutdown_request_round_trip(app_paths: AppPaths) -> None:
    assert shutdown.read_request(app_paths.run_dir) is None
    shutdown.write_request(app_paths.run_dir, "run-1")
    assert shutdown.read_request(app_paths.run_dir) == "run-1"
    shutdown.clear_request(app_paths.run_dir)
    assert shutdown.read_request(app_paths.run_dir) is None


async def test_watcher_reacts_only_to_its_own_run(app_paths: AppPaths) -> None:
    fired: list[str] = []
    watcher = shutdown.ShutdownWatcher(
        app_paths.run_dir, "mine", lambda: fired.append("mine"), poll_seconds=0.02
    )
    watcher.start()
    shutdown.write_request(app_paths.run_dir, "someone-else")
    await asyncio.sleep(0.1)
    assert fired == []
    shutdown.write_request(app_paths.run_dir, "mine")
    for _ in range(50):
        if fired:
            break
        await asyncio.sleep(0.02)
    await watcher.stop()
    assert fired == ["mine"]


async def test_watcher_without_run_id_accepts_any_request(app_paths: AppPaths) -> None:
    fired: list[bool] = []
    watcher = shutdown.ShutdownWatcher(
        app_paths.run_dir, None, lambda: fired.append(True), poll_seconds=0.02
    )
    watcher.start()
    shutdown.write_request(app_paths.run_dir, "any")
    for _ in range(50):
        if fired:
            break
        await asyncio.sleep(0.02)
    await watcher.stop()
    assert fired == [True]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("127.0.0.1:8765", "127.0.0.1"),
        ("LOCALHOST:8765", "localhost"),
        ("[::1]:8765", "::1"),
        ("[::1]", "::1"),
        ("::1", "::1"),
        ("example.com", "example.com"),
    ],
)
def test_host_without_port(header: str, expected: str) -> None:
    assert host_without_port(header) == expected


@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        (ConnectionRefusedError(), "connection refused"),
        (TimeoutError(), "timed out"),
        (OSError("unreachable"), "could not be reached"),
        (RuntimeError("x"), "RuntimeError"),
    ],
)
def test_database_error_descriptions(error: BaseException, fragment: str) -> None:
    assert fragment in describe_database_error(error)


def test_connection_errors_become_service_unavailable() -> None:
    translated = as_omni_error(ConnectionRefusedError())
    assert translated is not None and translated.code == "database_unavailable"
    assert as_omni_error(ValueError("bug")) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_private_files_are_owner_only(app_paths: AppPaths) -> None:
    target = app_paths.run_dir / "private.txt"
    write_private_text(target, "x")
    assert target.stat().st_mode & 0o077 == 0
