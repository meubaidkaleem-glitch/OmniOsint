"""Installation diagnostics (`omniosint doctor`).

Every check reports what it actually found. Optional components that are
missing are reported as information, not as failures.
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import struct
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata

import psutil

from omniosint import __version__
from omniosint.backup import pgtools
from omniosint.core.config import Settings, config_files, is_loopback_host
from omniosint.core.errors import OmniError
from omniosint.core.keystore import MasterKeyStore
from omniosint.core.paths import AppPaths, is_owner_only
from omniosint.database.engine import Database
from omniosint.runtime import supervisor
from omniosint.system.health import (
    RECOMMENDED_POSTGRES_VERSION,
    ComponentState,
    check_database,
    check_redis,
    check_storage,
    check_web_interface,
)

MIN_PYTHON = (3, 12)
TESTED_PYTHON_MAX = (3, 14)
MIN_NODE = (20, 19)
MIN_MEMORY_BYTES = 4 * 1024**3


class CheckStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: CheckStatus
    message: str
    hint: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "hint": self.hint,
        }


def tool_version_line(executable: str, *arguments: str) -> str | None:
    """First line of ``<executable> --version``, or ``None`` if it is not installed."""
    path = shutil.which(executable)
    if path is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - resolved by shutil.which
            [path, *(arguments or ("--version",))],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return "installed (version could not be read)"
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    return output[0].strip() if output else "installed"


def _parse_version(text: str) -> tuple[int, ...]:
    digits = "".join(char if char.isdigit() or char == "." else " " for char in text).split()
    for candidate in digits:
        parts = [part for part in candidate.split(".") if part]
        if parts:
            return tuple(int(part) for part in parts[:3])
    return ()


def check_platform() -> Check:
    system = platform.system()
    bits = struct.calcsize("P") * 8
    if system == "Windows":
        version = sys.getwindowsversion() if hasattr(sys, "getwindowsversion") else None
        major = version.major if version else 0
        build = version.build if version else 0
        label = f"Windows {'11' if build >= 22000 else major} (build {build}), {bits}-bit"
        if major < 10 or bits != 64:
            return Check(
                "Operating system",
                CheckStatus.FAIL,
                label,
                "OmniOSINT supports 64-bit Windows 10 and Windows 11.",
            )
        return Check("Operating system", CheckStatus.OK, label)
    release = platform.release()
    if system == "Linux":
        wsl = " under WSL" if "microsoft" in release.lower() else ""
        return Check(
            "Operating system",
            CheckStatus.OK,
            f"Linux {release}{wsl}, {bits}-bit (secondary platform)",
        )
    return Check(
        "Operating system",
        CheckStatus.WARN,
        f"{system} {release}",
        "This platform is not tested. Windows 10/11 and Linux are supported.",
    )


def check_python() -> Check:
    version = sys.version_info
    label = f"Python {version.major}.{version.minor}.{version.micro}"
    in_venv = sys.prefix != sys.base_prefix
    if (version.major, version.minor) < MIN_PYTHON:
        return Check(
            "Python",
            CheckStatus.FAIL,
            label,
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or later is required.",
        )
    if (version.major, version.minor) > TESTED_PYTHON_MAX:
        return Check(
            "Python",
            CheckStatus.WARN,
            f"{label} (newer than the tested range)",
            f"Tested with Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} to "
            f"{TESTED_PYTHON_MAX[0]}.{TESTED_PYTHON_MAX[1]}.",
        )
    if not in_venv:
        return Check(
            "Python",
            CheckStatus.WARN,
            f"{label}, not in a virtual environment",
            "Run the installer so that dependencies are isolated in .venv.",
        )
    return Check("Python", CheckStatus.OK, f"{label}, virtual environment active")


def check_packages() -> Check:
    names = ("fastapi", "uvicorn", "sqlalchemy", "asyncpg", "alembic", "pydantic")
    found = []
    missing = []
    for name in names:
        try:
            found.append(f"{name} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        return Check(
            "Python packages",
            CheckStatus.FAIL,
            f"Missing: {', '.join(missing)}",
            "Run the installer again to install the dependencies.",
        )
    return Check("Python packages", CheckStatus.OK, f"OmniOSINT {__version__}; " + ", ".join(found))


def check_configuration(paths: AppPaths, error: OmniError | None) -> Check:
    if error is not None:
        return Check("Configuration", CheckStatus.FAIL, error.message, error.hint)
    used = [f"{label} ({path})" for label, path, exists in config_files(paths) if exists]
    return Check("Configuration", CheckStatus.OK, "Valid. Read: " + "; ".join(used))


def check_data_directory(paths: AppPaths) -> Check:
    result = check_storage(paths)
    if result.status is ComponentState.UNAVAILABLE:
        return Check("Data directory", CheckStatus.FAIL, result.detail)
    private = is_owner_only(paths.home)
    if private is False:
        return Check(
            "Data directory",
            CheckStatus.WARN,
            f"{paths.home}: readable by other users",
            "Restrict it to your account (chmod 700).",
        )
    status = CheckStatus.WARN if result.status is ComponentState.DEGRADED else CheckStatus.OK
    return Check("Data directory", status, f"{paths.home}: {result.detail}")


def check_memory() -> Check:
    total = psutil.virtual_memory().total
    label = f"{total / 1024**3:.1f} GiB installed"
    if total < MIN_MEMORY_BYTES:
        return Check("Memory", CheckStatus.WARN, label, "At least 4 GiB is recommended.")
    return Check("Memory", CheckStatus.OK, label)


def check_secret_storage(paths: AppPaths) -> Check:
    store = MasterKeyStore(paths.secrets_dir)
    description = store.protector.description
    if store.protector.name == "dpapi":
        return Check("Secret storage", CheckStatus.OK, description)
    private = is_owner_only(store.path) if store.exists() else True
    if private is False:
        return Check(
            "Secret storage",
            CheckStatus.FAIL,
            f"{store.path} is readable by other users",
            "Restrict it to your account (chmod 600).",
        )
    return Check(
        "Secret storage",
        CheckStatus.WARN,
        description,
        "Weaker than Windows DPAPI: anything running as your user can read the key.",
    )


def check_exposure(settings: Settings) -> Check:
    host = settings.server.host
    if is_loopback_host(host):
        return Check("Network exposure", CheckStatus.OK, f"Listens on {host} only (this machine).")
    return Check(
        "Network exposure",
        CheckStatus.WARN,
        f"Listens on {host}: reachable from other machines.",
        "OmniOSINT has no TLS of its own. Use 127.0.0.1 unless you run it behind a "
        "reverse proxy you control.",
    )


def check_port(settings: Settings, paths: AppPaths) -> Check:
    server = settings.server
    state = supervisor.read_state(paths)
    if state is not None and any(supervisor.is_alive(item) for item in state.processes):
        return Check("Port", CheckStatus.OK, f"{server.port} is in use by OmniOSINT (running).")
    if supervisor.port_available(server.host, server.port):
        return Check("Port", CheckStatus.OK, f"{server.port} is free.")
    return Check(
        "Port",
        CheckStatus.FAIL,
        f"{server.port} is in use by another program.",
        "Stop that program or set server.port to a free port.",
    )


async def _service_checks(settings: Settings, paths: AppPaths) -> list[Check]:
    db = Database.from_settings(settings, paths, application_name="omniosint-doctor")
    try:
        database = await check_database(db)
    except OmniError as exc:
        database = None
        database_error: OmniError | None = exc
    else:
        database_error = None
    finally:
        await db.dispose()
    redis = await check_redis(settings)

    checks: list[Check] = []
    if database is None:
        assert database_error is not None
        checks.append(
            Check("Database", CheckStatus.FAIL, database_error.message, database_error.hint)
        )
    elif database.status is ComponentState.OK:
        version_text = str(database.data.get("server_version", ""))
        major = _parse_version(version_text)[:1]
        if major and major[0] * 10000 < RECOMMENDED_POSTGRES_VERSION:
            checks.append(
                Check(
                    "Database",
                    CheckStatus.WARN,
                    database.detail,
                    "PostgreSQL 15 or later is recommended; this version is past its end of life.",
                )
            )
        else:
            checks.append(Check("Database", CheckStatus.OK, database.detail))
    else:
        hint = (
            "Run: omniosint db upgrade"
            if "db upgrade" in database.detail
            else "Check that PostgreSQL is running and the connection settings are correct."
        )
        checks.append(Check("Database", CheckStatus.FAIL, database.detail, hint))

    if redis.status is ComponentState.OK:
        checks.append(Check("Redis", CheckStatus.OK, redis.detail))
    elif redis.status is ComponentState.NOT_CONFIGURED:
        checks.append(Check("Redis", CheckStatus.INFO, redis.detail))
    else:
        checks.append(
            Check("Redis", CheckStatus.WARN, redis.detail, "Check redis.url or unset it.")
        )
    return checks


def check_frontend(settings: Settings) -> list[Check]:
    result = check_web_interface(settings)
    node = tool_version_line("node")
    checks: list[Check] = []
    if result.status is ComponentState.OK:
        checks.append(Check("Web interface", CheckStatus.OK, result.detail))
    elif result.status is ComponentState.NOT_CONFIGURED:
        checks.append(Check("Web interface", CheckStatus.INFO, result.detail))
    else:
        checks.append(Check("Web interface", CheckStatus.WARN, result.detail))

    if node is None:
        status = CheckStatus.INFO if result.status is ComponentState.OK else CheckStatus.WARN
        checks.append(
            Check(
                "Node.js",
                status,
                "Not found (needed only to build the web interface).",
                None if status is CheckStatus.INFO else "Install Node.js 20.19 or later.",
            )
        )
    else:
        version = _parse_version(node)
        if version and version[:2] < MIN_NODE:
            checks.append(
                Check(
                    "Node.js",
                    CheckStatus.WARN,
                    f"{node} is older than required",
                    f"Node.js {MIN_NODE[0]}.{MIN_NODE[1]} or later is needed to build.",
                )
            )
        else:
            checks.append(Check("Node.js", CheckStatus.OK, node))
    return checks


def check_backup_tools(settings: Settings) -> Check:
    found = []
    missing = []
    for name in ("pg_dump", "pg_restore", "psql"):
        tool = pgtools.find_tool(name, settings.database)
        if tool is None:
            missing.append(name)
            continue
        try:
            found.append(pgtools.tool_version(tool)[1])
        except OmniError:
            found.append(f"{name} (version unreadable)")
    if missing:
        return Check(
            "Backup tools",
            CheckStatus.WARN,
            f"Not found: {', '.join(missing)}. Backup and restore are unavailable.",
            "Install the PostgreSQL command line tools or set database.pg_bin_dir.",
        )
    return Check("Backup tools", CheckStatus.OK, "; ".join(found))


def check_optional_tools() -> list[Check]:
    """Tools that later phases or optional features use. Missing ones are fine."""
    catalogue: list[tuple[str, str, tuple[str, ...], str]] = [
        ("Git", "git", ("--version",), "used by update.bat to fetch updates"),
        ("Docker", "docker", ("--version",), "optional way to run PostgreSQL and Redis"),
        ("Rust (cargo)", "cargo", ("--version",), "needed only to build the desktop shell"),
        ("Nmap", "nmap", ("--version",), "authorised network discovery, from Phase 8"),
    ]
    if sys.platform == "win32":
        catalogue.append(("WSL", "wsl", ("--status",), "optional Linux environment"))
    checks = []
    for label, executable, arguments, purpose in catalogue:
        line = tool_version_line(executable, *arguments)
        if line is None:
            checks.append(Check(label, CheckStatus.INFO, f"Not found (optional: {purpose})."))
        else:
            checks.append(Check(label, CheckStatus.INFO, f"{line} ({purpose})"))
    return checks


def check_application(settings: Settings, paths: AppPaths) -> Check:
    report = supervisor.status(settings, paths)
    if not report.processes:
        return Check("Application", CheckStatus.INFO, "Not running.")
    if report.healthy:
        state = report.health.get("status") if report.health else "unknown"
        return Check("Application", CheckStatus.OK, f"Running at {report.url} (status: {state}).")
    stopped = [item.name for item in report.processes if not item.running]
    detail = f"stopped processes: {', '.join(stopped)}" if stopped else "not responding"
    return Check(
        "Application",
        CheckStatus.WARN,
        f"Started but unhealthy ({detail}).",
        "Run `omniosint restart`, and see the logs if it persists.",
    )


def run_doctor(
    settings: Settings | None, paths: AppPaths, config_error: OmniError | None = None
) -> list[Check]:
    """Run every check. ``settings`` is ``None`` when the configuration is invalid."""
    checks: list[Check] = [
        check_platform(),
        check_python(),
        check_packages(),
        check_configuration(paths, config_error),
        check_data_directory(paths),
        check_memory(),
        check_secret_storage(paths),
    ]
    if settings is None:
        return checks

    simple: list[Callable[[], Check]] = [
        lambda: check_exposure(settings),
        lambda: check_port(settings, paths),
    ]
    checks.extend(check() for check in simple)
    checks.extend(asyncio.run(_service_checks(settings, paths)))
    checks.extend(check_frontend(settings))
    checks.append(check_backup_tools(settings))
    checks.append(check_application(settings, paths))
    checks.extend(check_optional_tools())
    return checks


def summarize(checks: list[Check]) -> dict[str, int]:
    summary = {status.value: 0 for status in CheckStatus}
    for check in checks:
        summary[check.status.value] += 1
    return summary
