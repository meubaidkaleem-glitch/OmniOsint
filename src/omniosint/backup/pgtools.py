"""Locating and running the PostgreSQL client tools (pg_dump, pg_restore, psql).

The tools are not bundled. They come with a PostgreSQL installation (on
Windows, the installer's "Command Line Tools" component is enough).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy import URL

from omniosint.core.config import DatabaseSettings
from omniosint.core.errors import ExternalToolError

_VERSION_PATTERN = re.compile(r"\(PostgreSQL\)\s+(\d+)(?:\.(\d+))?")
_TOOL_TIMEOUT_SECONDS = 3600


def _version_key(path: Path) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", path.parent.parent.name)
    return tuple(int(number) for number in numbers) or (0,)


def _well_known_directories() -> list[Path]:
    """Installation directories to search when the tool is not on PATH."""
    roots: list[Path] = []
    if sys.platform == "win32":
        for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            base = os.environ.get(variable)
            if base:
                roots.append(Path(base) / "PostgreSQL")
    else:
        roots += [Path("/usr/lib/postgresql"), Path("/usr/pgsql"), Path("/opt/homebrew/opt")]
        roots.append(Path("/usr/local/pgsql"))

    directories: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            candidates = [entry / "bin" for entry in root.iterdir() if (entry / "bin").is_dir()]
        except OSError:
            continue
        directories.extend(sorted(candidates, key=_version_key, reverse=True))
        if (root / "bin").is_dir():
            directories.append(root / "bin")
    return directories


def find_tool(name: str, settings: DatabaseSettings | None = None) -> Path | None:
    """Find a PostgreSQL client tool: configured directory, PATH, then known locations."""
    executable = f"{name}.exe" if sys.platform == "win32" else name
    if settings is not None and settings.pg_bin_dir is not None:
        configured = settings.pg_bin_dir / executable
        if configured.is_file():
            return configured
    on_path = shutil.which(name)
    if on_path:
        return Path(on_path)
    for directory in _well_known_directories():
        candidate = directory / executable
        if candidate.is_file():
            return candidate
    return None


def require_tool(name: str, settings: DatabaseSettings | None = None) -> Path:
    tool = find_tool(name, settings)
    if tool is None:
        raise ExternalToolError(
            f"The PostgreSQL client tool `{name}` was not found.",
            hint=(
                "Install the PostgreSQL command line tools, add their folder to PATH, or "
                "set database.pg_bin_dir to the folder that contains them."
            ),
        )
    return tool


def tool_version(tool: Path) -> tuple[int, str]:
    """Return ``(major version, full version line)`` of a client tool."""
    try:
        completed = subprocess.run(  # noqa: S603 - executable located by find_tool
            [str(tool), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExternalToolError(f"`{tool.name}` could not be run: {exc}") from exc
    line = (completed.stdout or completed.stderr).strip().splitlines()[0:1]
    text = line[0] if line else ""
    match = _VERSION_PATTERN.search(text)
    if completed.returncode != 0 or match is None:
        raise ExternalToolError(f"`{tool.name}` did not report a usable version: {text!r}")
    return int(match.group(1)), text


def connection_environment(url: URL, ssl_mode: str) -> dict[str, str]:
    """Environment for a client tool.

    The password is passed through ``PGPASSWORD`` so that it never appears on a
    command line, where other local users could read it.
    """
    environment = dict(os.environ)
    environment["PGHOST"] = url.host or "127.0.0.1"
    environment["PGPORT"] = str(url.port or 5432)
    environment["PGUSER"] = url.username or ""
    environment["PGDATABASE"] = url.database or ""
    environment["PGSSLMODE"] = ssl_mode
    environment["PGCONNECT_TIMEOUT"] = "15"
    if url.password:
        environment["PGPASSWORD"] = str(url.password)
    else:
        environment.pop("PGPASSWORD", None)
    return environment


def run_tool(
    tool: Path, arguments: list[str], *, environment: dict[str, str], action: str
) -> None:
    """Run a client tool; raise :class:`ExternalToolError` with its message on failure."""
    try:
        completed = subprocess.run(  # noqa: S603 - executable located by find_tool
            [str(tool), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            timeout=_TOOL_TIMEOUT_SECONDS,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExternalToolError(f"{action} timed out.") from exc
    except OSError as exc:
        raise ExternalToolError(f"{action} failed: `{tool.name}` could not be run ({exc}).") from exc
    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout or "").strip().splitlines()
        reason = output[-1] if output else f"exit code {completed.returncode}"
        raise ExternalToolError(f"{action} failed: {reason}")
