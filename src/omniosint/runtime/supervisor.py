"""Process supervisor: start, stop and inspect the OmniOSINT processes.

This is the only implementation of lifecycle control. The Windows scripts, the
Linux scripts and the desktop shell all call the CLI commands built on it.

Design notes:

* Children are started detached and keep running after the command returns.
* What was started is recorded in ``<run dir>/state.json`` with each process's
  creation time, so a recycled PID is never mistaken for one of ours.
* A graceful stop is requested through a file (see ``runtime.shutdown``), which
  behaves the same on Windows and Linux. Termination is only a fallback.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psutil

from omniosint import __version__
from omniosint.core.config import Settings
from omniosint.core.errors import Conflict, DatabaseUnavailable, OmniError, SchemaOutOfDate
from omniosint.core.paths import AppPaths, project_root, write_private_text
from omniosint.core.timeutil import isoformat, utcnow
from omniosint.database.engine import Database
from omniosint.runtime import shutdown
from omniosint.runtime.shutdown import RUN_ID_ENV
from omniosint.system.health import ComponentState, check_database

STATE_FILE = "state.json"
READY_PATH = "/api/v1/system/health/ready"
_CREATE_TIME_TOLERANCE = 2.0
_FORCE_WAIT_SECONDS = 5.0


class PortInUse(Conflict):
    code = "port_in_use"
    default_message = "The configured port is already in use by another program."


class StartFailed(OmniError):
    code = "start_failed"
    status_code = 500
    default_message = "OmniOSINT did not start."


@dataclass(slots=True)
class ManagedProcess:
    name: str
    pid: int
    create_time: float
    command: list[str]
    log_file: str


@dataclass(slots=True)
class RunState:
    run_id: str
    started_at: str
    version: str
    url: str
    processes: list[ManagedProcess] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> RunState:
        data = json.loads(text)
        return cls(
            run_id=str(data["run_id"]),
            started_at=str(data["started_at"]),
            version=str(data.get("version", "")),
            url=str(data["url"]),
            processes=[ManagedProcess(**item) for item in data.get("processes", [])],
        )


@dataclass(slots=True)
class ProcessStatus:
    name: str
    pid: int
    running: bool
    log_file: str


@dataclass(slots=True)
class StatusReport:
    running: bool
    url: str
    run_id: str | None
    started_at: str | None
    processes: list[ProcessStatus]
    health: dict[str, Any] | None
    health_error: str | None = None

    @property
    def healthy(self) -> bool:
        return (
            self.running
            and self.health is not None
            and self.health.get("status") in ("ok", "degraded")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "healthy": self.healthy,
            "url": self.url,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "processes": [asdict(item) for item in self.processes],
            "health": self.health,
            "health_error": self.health_error,
        }


@dataclass(slots=True)
class StartResult:
    already_running: bool
    state: RunState
    status: StatusReport


@dataclass(slots=True)
class StopResult:
    was_running: bool
    stopped: list[str] = field(default_factory=list)
    forced: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- state file
def state_path(paths: AppPaths) -> Path:
    return paths.run_dir / STATE_FILE


def read_state(paths: AppPaths) -> RunState | None:
    try:
        return RunState.from_json(state_path(paths).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_state(paths: AppPaths, state: RunState) -> None:
    write_private_text(state_path(paths), state.to_json() + "\n")


def clear_state(paths: AppPaths) -> None:
    state_path(paths).unlink(missing_ok=True)


# --------------------------------------------------------------------------- processes
def is_alive(process: ManagedProcess) -> bool:
    """True if the recorded process is still running (and is the same process)."""
    try:
        handle = psutil.Process(process.pid)
        if abs(handle.create_time() - process.create_time) > _CREATE_TIME_TOLERANCE:
            return False
        return handle.is_running() and handle.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False


def _child_environment(paths: AppPaths, run_id: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment[RUN_ID_ENV] = run_id
    environment["OMNIOSINT_HOME"] = str(paths.home)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def spawn_detached(command: list[str], *, log_path: Path, env: dict[str, str]) -> ManagedProcess:
    """Start ``command`` so that it outlives this process and its console."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        # A new process group and a hidden console of its own: closing the
        # launching terminal does not reach it, and console programs it starts
        # later do not open windows.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True

    working_directory = project_root() or Path(env.get("OMNIOSINT_HOME") or Path.cwd())
    with open(log_path, "ab") as log_handle:
        process = subprocess.Popen(  # noqa: S603 - fixed command line built by this module
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(working_directory),
            close_fds=True,
            **kwargs,
        )
    try:
        create_time = psutil.Process(process.pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        create_time = time.time()
    return ManagedProcess(
        name="",
        pid=process.pid,
        create_time=create_time,
        command=command,
        log_file=str(log_path),
    )


def log_tail(path: str | Path, lines: int = 15) -> str:
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        if sys.platform != "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def _terminate(process: ManagedProcess, wait_seconds: float) -> bool:
    """Forcefully end a process we started. Returns whether it is gone."""
    try:
        handle = psutil.Process(process.pid)
        if abs(handle.create_time() - process.create_time) > _CREATE_TIME_TOLERANCE:
            return True
        handle.terminate()
        try:
            handle.wait(timeout=wait_seconds)
        except psutil.TimeoutExpired:
            handle.kill()
            handle.wait(timeout=wait_seconds)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired, OSError):
        pass
    return not is_alive(process)


# --------------------------------------------------------------------------- health
def fetch_health(url: str, timeout: float = 3.0) -> tuple[dict[str, Any] | None, str | None]:
    """Query the readiness endpoint. Returns ``(body, error)``.

    ``trust_env=False`` keeps a system-wide HTTP proxy from intercepting a
    request that must go to this machine.
    """
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.get(url + READY_PATH)
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return None, type(exc).__name__
    if not isinstance(body, dict) or "status" not in body:
        return None, f"unexpected response (HTTP {response.status_code})"
    return body, None


def status(settings: Settings, paths: AppPaths) -> StatusReport:
    state = read_state(paths)
    url = settings.server.base_url
    if state is None:
        return StatusReport(
            running=False, url=url, run_id=None, started_at=None, processes=[], health=None
        )
    processes = [
        ProcessStatus(name=item.name, pid=item.pid, running=is_alive(item), log_file=item.log_file)
        for item in state.processes
    ]
    running = bool(processes) and all(item.running for item in processes)
    health, error = fetch_health(state.url) if any(p.running for p in processes) else (None, None)
    return StatusReport(
        running=running,
        url=state.url,
        run_id=state.run_id,
        started_at=state.started_at,
        processes=processes,
        health=health,
        health_error=error,
    )


# --------------------------------------------------------------------------- start / stop
def _preflight_database(settings: Settings, paths: AppPaths) -> None:
    async def check() -> None:
        db = Database.from_settings(settings, paths, application_name="omniosint-preflight")
        try:
            result = await check_database(db)
        finally:
            await db.dispose()
        if result.status is ComponentState.OK:
            return
        if result.data.get("schema_head") and result.data.get("schema_revision") != result.data.get(
            "schema_head"
        ):
            raise SchemaOutOfDate(result.detail, hint="Run: omniosint db upgrade")
        raise DatabaseUnavailable(
            result.detail,
            hint="Check that PostgreSQL is running and that the connection settings are "
            "correct (omniosint doctor).",
        )

    asyncio.run(check())


def _wait_until_ready(
    state: RunState, timeout: float
) -> tuple[dict[str, Any] | None, str | None, ManagedProcess | None]:
    """Poll until the API reports ready. Returns ``(health, error, dead process)``."""
    deadline = time.monotonic() + timeout
    health: dict[str, Any] | None = None
    error: str | None = "no response yet"
    while time.monotonic() < deadline:
        for process in state.processes:
            if not is_alive(process):
                return health, f"the {process.name} process exited", process
        health, error = fetch_health(state.url, timeout=2.0)
        if health is not None and health.get("status") in ("ok", "degraded"):
            worker = next(
                (c for c in health.get("components", []) if c.get("name") == "worker"), None
            )
            # Give the worker a moment to register before settling for "degraded".
            if worker is None or worker.get("status") == "ok" or time.monotonic() > deadline - 5:
                return health, None, None
        time.sleep(0.4)
    return health, error or "timed out", None


def start(settings: Settings, paths: AppPaths, *, wait: bool = True) -> StartResult:
    """Start the API and the worker. Idempotent when already running."""
    paths.ensure()
    existing = read_state(paths)
    if existing is not None:
        alive = [item for item in existing.processes if is_alive(item)]
        if alive and len(alive) == len(existing.processes):
            return StartResult(
                already_running=True, state=existing, status=status(settings, paths)
            )
        if alive:
            stop(settings, paths)  # half-running: clean up before starting again
        clear_state(paths)
    shutdown.clear_request(paths.run_dir)

    server = settings.server
    if not port_available(server.host, server.port):
        raise PortInUse(
            f"Port {server.port} on {server.host} is already in use by another program.",
            hint="Stop the other program, or set server.port to a free port.",
        )
    _preflight_database(settings, paths)

    run_id = uuid.uuid4().hex
    environment = _child_environment(paths, run_id)
    state = RunState(
        run_id=run_id,
        started_at=isoformat(utcnow()) or "",
        version=__version__,
        url=server.base_url,
    )
    for name in ("api", "worker"):
        command = [sys.executable, "-m", "omniosint", "serve" if name == "api" else "worker"]
        process = spawn_detached(
            command, log_path=paths.logs_dir / f"{name}.out.log", env=environment
        )
        process.name = name
        state.processes.append(process)
        write_state(paths, state)

    if not wait:
        return StartResult(already_running=False, state=state, status=status(settings, paths))

    health, error, dead = _wait_until_ready(state, settings.runtime.startup_timeout_seconds)
    if error is not None:
        tail = log_tail(dead.log_file) if dead is not None else ""
        failed_state = state
        stop(settings, paths)
        message = f"OmniOSINT did not become ready: {error}."
        if tail:
            message += f"\nLast lines of {Path(dead.log_file).name if dead else 'the log'}:\n{tail}"
        raise StartFailed(
            message,
            hint=f"See the logs in {paths.logs_dir}.",
            details=[{"run_id": failed_state.run_id, "health": health}],
        )
    return StartResult(already_running=False, state=state, status=status(settings, paths))


def stop(settings: Settings, paths: AppPaths, *, timeout: float | None = None) -> StopResult:
    """Stop everything `start` launched. Safe to call when nothing is running."""
    state = read_state(paths)
    if state is None:
        shutdown.clear_request(paths.run_dir)
        return StopResult(was_running=False)

    alive = [item for item in state.processes if is_alive(item)]
    result = StopResult(was_running=bool(alive))
    if alive:
        shutdown.write_request(paths.run_dir, state.run_id)
        deadline = time.monotonic() + (
            timeout if timeout is not None else settings.runtime.shutdown_timeout_seconds
        )
        while time.monotonic() < deadline and any(is_alive(item) for item in alive):
            time.sleep(0.2)
        for item in alive:
            if is_alive(item):
                _terminate(item, _FORCE_WAIT_SECONDS)
                result.forced.append(item.name)
            result.stopped.append(item.name)

    shutdown.clear_request(paths.run_dir)
    clear_state(paths)
    return result
