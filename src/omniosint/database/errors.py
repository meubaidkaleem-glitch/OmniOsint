"""Classification of database failures into user-facing errors."""

from __future__ import annotations

import socket

from sqlalchemy import exc as sa_exc

from omniosint.core.errors import DatabaseUnavailable, OmniError, SchemaOutOfDate

_CONNECTION_ERROR_NAMES = frozenset(
    {
        "InvalidPasswordError",
        "InvalidAuthorizationSpecificationError",
        "InvalidCatalogNameError",
        "CannotConnectNowError",
        "ConnectionDoesNotExistError",
        "ConnectionFailureError",
        "TooManyConnectionsError",
        "InterfaceError",
        "PostgresConnectionError",
    }
)


def _chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        original = getattr(current, "orig", None)
        current = original if isinstance(original, BaseException) else current.__cause__
    return seen


def as_omni_error(exc: BaseException) -> OmniError | None:
    """Translate a database connectivity or schema failure, or return ``None``.

    Anything that is not clearly "the database is unreachable" or "the schema is
    missing" is left alone so that real bugs still surface as server errors.
    """
    for item in _chain(exc):
        name = type(item).__name__
        if name == "UndefinedTableError" or (
            isinstance(item, sa_exc.ProgrammingError) and "UndefinedTable" in repr(item.orig)
        ):
            return SchemaOutOfDate(
                "The database schema has not been created or is out of date.",
                hint="Run: omniosint db upgrade",
            )
        if (
            isinstance(
                item,
                ConnectionError
                | TimeoutError
                | socket.gaierror
                | sa_exc.TimeoutError
                | sa_exc.OperationalError
                | sa_exc.InterfaceError,
            )
            or name in _CONNECTION_ERROR_NAMES
        ):
            return DatabaseUnavailable()
    return None
