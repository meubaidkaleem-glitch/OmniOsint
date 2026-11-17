"""Structured logging.

Every process (API, worker, CLI) writes JSON lines to its own rotating file and
human-readable lines to the console when attached to a terminal. Values of
keys that look like credentials are masked before anything is written.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import structlog

from omniosint.core.config import LoggingSettings

REDACTED = "***"

_SENSITIVE_EXACT = frozenset(
    {"authorization", "cookie", "set-cookie", "dsn", "csrf", "x-csrf-token", "session"}
)
_SENSITIVE_SUFFIXES = (
    "password",
    "passphrase",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "credentials",
    "private_key",
)
_MAX_REDACT_DEPTH = 6


def is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return lowered in _SENSITIVE_EXACT or lowered.endswith(_SENSITIVE_SUFFIXES)


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return ``value`` with the values of sensitive keys masked."""
    if _depth >= _MAX_REDACT_DEPTH:
        return value
    if isinstance(value, Mapping):
        return {
            key: (REDACTED if is_sensitive_key(key) else redact(item, _depth=_depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(redact(item, _depth=_depth + 1) for item in value)
    return value


def _redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key in ("event", "level", "timestamp", "logger"):
            continue
        if is_sensitive_key(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = redact(event_dict[key])
    return event_dict


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _redact_processor,
    ]


def _formatter(*, as_json: bool, colors: bool) -> logging.Formatter:
    processors: list[Any] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if as_json:
        processors += [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        # Plain tracebacks on purpose: the "rich" formatter prints local
        # variables, which can include passwords and tokens.
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=colors, exception_formatter=structlog.dev.plain_traceback
            )
        )
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=processors,
    )


def configure_logging(
    settings: LoggingSettings,
    *,
    service: str,
    logs_dir: Path | None = None,
    console: bool = True,
) -> None:
    """Configure logging for the current process.

    ``service`` names the log file (``<logs_dir>/<service>.log``) and is bound to
    every record.
    """
    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handlers: list[logging.Handler] = []
    if console:
        stream = sys.stderr
        is_tty = bool(getattr(stream, "isatty", lambda: False)())
        as_json = settings.console_format == "json" or (
            settings.console_format == "auto" and not is_tty
        )
        console_handler = logging.StreamHandler(stream)
        console_handler.setFormatter(_formatter(as_json=as_json, colors=is_tty))
        handlers.append(console_handler)

    if settings.file_enabled and logs_dir is not None:
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                logs_dir / f"{service}.log",
                maxBytes=settings.file_max_bytes,
                backupCount=settings.file_backup_count,
                encoding="utf-8",
                delay=True,
            )
        except OSError as exc:  # logging must never stop the application
            sys.stderr.write(f"warning: file logging disabled ({exc})\n")
        else:
            file_handler.setFormatter(_formatter(as_json=True, colors=False))
            handlers.append(file_handler)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
        existing.close()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(settings.level)

    # Route third-party loggers through the same handlers.
    for name in ("uvicorn", "uvicorn.error"):
        third_party = logging.getLogger(name)
        third_party.handlers.clear()
        third_party.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False  # the request middleware writes the access log
    access.disabled = True

    for name, level in (
        ("sqlalchemy.engine", logging.WARNING),
        ("alembic", logging.INFO),
        ("httpx", logging.WARNING),
        ("httpcore", logging.WARNING),
        ("asyncio", logging.WARNING),
    ):
        logging.getLogger(name).setLevel(level)

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
