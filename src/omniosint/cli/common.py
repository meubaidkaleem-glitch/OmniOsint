"""Shared plumbing for CLI commands."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass
from typing import Any, NoReturn

import typer
from rich.console import Console

from omniosint.core.config import Settings, load_settings
from omniosint.core.errors import (
    ConfigurationError,
    NotImplementedYet,
    OmniError,
    ServiceUnavailable,
)
from omniosint.core.features import PHASES
from omniosint.core.logging import configure_logging
from omniosint.core.paths import AppPaths
from omniosint.database.engine import Database
from omniosint.database.errors import as_omni_error

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_CONFIGURATION = 3
EXIT_UNAVAILABLE = 4

console = Console(highlight=False, soft_wrap=True)
error_console = Console(stderr=True, highlight=False, soft_wrap=True)


class _State:
    """Per-invocation flags that the top-level error handler needs."""

    json_output: bool = False


state = _State()


@dataclass(frozen=True, slots=True)
class Runtime:
    settings: Settings
    paths: AppPaths


def load_runtime() -> Runtime:
    """Resolve paths, load settings and send CLI logs to a file (not the terminal)."""
    paths = AppPaths.resolve()
    paths.ensure()
    settings = load_settings(paths)
    configure_logging(settings.logging, service="cli", logs_dir=paths.logs_dir, console=False)
    return Runtime(settings=settings, paths=paths)


def emit_json(data: Any) -> None:
    sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")
    sys.stdout.flush()


def use_json(enabled: bool) -> None:
    state.json_output = enabled


def exit_code_for(error: OmniError) -> int:
    if isinstance(error, ConfigurationError):
        return EXIT_CONFIGURATION
    if isinstance(error, ServiceUnavailable):
        return EXIT_UNAVAILABLE
    if isinstance(error, NotImplementedYet):
        return EXIT_USAGE
    return EXIT_FAILURE


def report_error(error: OmniError) -> None:
    if state.json_output:
        emit_json({"ok": False, "error": error.to_dict()})
        return
    error_console.print(f"[bold red]Error:[/bold red] {escape(error.message)}")
    for detail in error.details:
        message = detail.get("message")
        if message:
            field = detail.get("field") or detail.get("setting")
            prefix = f"{field}: " if field else ""
            error_console.print(f"  - {escape(prefix + str(message))}")
    if error.hint:
        error_console.print(f"[dim]{escape(error.hint)}[/dim]")


def escape(text: str) -> str:
    """Neutralise Rich markup in text that did not come from this program."""
    return text.replace("[", "\\[")


def fail(message: str, *, hint: str | None = None, code: int = EXIT_FAILURE) -> NoReturn:
    error_console.print(f"[bold red]Error:[/bold red] {escape(message)}")
    if hint:
        error_console.print(f"[dim]{escape(hint)}[/dim]")
    raise typer.Exit(code)


def planned(feature: str, phase: int) -> NoReturn:
    """Exit with the standard message for a command whose feature is not built."""
    error = NotImplementedYet(feature, phase=phase)
    if state.json_output:
        emit_json({"ok": False, "error": error.to_dict(), "phase": phase})
    else:
        console.print(f"[yellow]{escape(error.message)}[/yellow]")
        console.print(f"[dim]Phase {phase}: {PHASES[phase]}. See docs/ROADMAP.md.[/dim]")
    raise typer.Exit(EXIT_USAGE)


def run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine, translating database failures into user-facing errors."""
    try:
        return asyncio.run(coroutine)
    except OmniError:
        raise
    except Exception as exc:
        translated = as_omni_error(exc)
        if translated is None:
            raise
        raise translated from exc


@contextlib.asynccontextmanager
async def open_database(runtime: Runtime, name: str = "omniosint-cli") -> AsyncIterator[Database]:
    database = Database.from_settings(runtime.settings, runtime.paths, application_name=name)
    try:
        yield database
    finally:
        await database.dispose()


def read_secret_from_stdin() -> str:
    """One line from standard input, for passing secrets without a prompt."""
    value = sys.stdin.readline().rstrip("\r\n")
    if not value:
        fail("No value was supplied on standard input.", code=EXIT_USAGE)
    return value


def prompt_new_secret(label: str) -> str:
    return str(typer.prompt(label, hide_input=True, confirmation_prompt=True))
