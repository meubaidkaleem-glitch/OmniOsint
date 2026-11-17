"""Creates the application role and database on a PostgreSQL server.

Used by the installer when the user has administrative access to a local
PostgreSQL server and has not created the database by hand.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

import asyncpg

from omniosint.core.errors import ValidationFailed

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SCRAM_ITERATIONS = 4096


def validate_identifier(value: str, what: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValidationFailed(
            f"The {what} name {value!r} is not valid. Use lower-case letters, digits and "
            "underscores, starting with a letter or underscore."
        )
    return value


def scram_verifier(password: str, *, salt: bytes | None = None) -> str | None:
    """SCRAM-SHA-256 verifier for ``password``.

    Sending the verifier instead of the password keeps the plaintext out of the
    server's statement log. Returns ``None`` for passwords that would need
    SASLprep normalisation (non-ASCII), which are sent as-is instead.
    """
    if not password.isascii() or any(ord(char) < 0x20 or ord(char) == 0x7F for char in password):
        return None
    salt = salt or os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("ascii"), salt, _SCRAM_ITERATIONS)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()

    def encode(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    keys = f"{encode(stored_key)}:{encode(server_key)}"
    return f"SCRAM-SHA-256${_SCRAM_ITERATIONS}:{encode(salt)}${keys}"


async def _create_owned_database(
    connection: asyncpg.Connection, *, database: str, role: str
) -> None:
    """``CREATE DATABASE ... OWNER role``, also for administrators that are not superusers.

    PostgreSQL only lets the creator hand a database to a role it can switch
    to (``SET ROLE``). A superuser always can. An administrator that merely
    holds CREATEROLE is granted membership of the role for the duration of the
    statement and has it removed afterwards.
    """
    is_superuser = await connection.fetchval(
        "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
    )
    temporarily_granted = False
    if not is_superuser:
        version = int(await connection.fetchval("SHOW server_version_num"))
        privilege = "SET" if version >= 160000 else "MEMBER"
        can_switch = await connection.fetchval(
            "SELECT pg_has_role(current_user, $1::text, $2::text)", role, privilege
        )
        if not can_switch:
            grant = await connection.fetchval(
                "SELECT format('GRANT %I TO CURRENT_USER', $1::text)", role
            )
            try:
                await connection.execute(grant)
            except asyncpg.InsufficientPrivilegeError as exc:
                raise ValidationFailed(
                    f"This PostgreSQL account cannot create a database owned by {role!r}.",
                    hint="Run the bootstrap as a superuser (such as postgres), or create the "
                    "database by hand and give OmniOSINT its connection details.",
                ) from exc
            temporarily_granted = True

    statement = await connection.fetchval(
        "SELECT format('CREATE DATABASE %I OWNER %I', $1::text, $2::text)", database, role
    )
    try:
        await connection.execute(statement)
    finally:
        if temporarily_granted:
            revoke = await connection.fetchval(
                "SELECT format('REVOKE %I FROM CURRENT_USER', $1::text)", role
            )
            await connection.execute(revoke)


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    role_created: bool
    role_password_set: bool
    database_created: bool


async def bootstrap_database(
    *,
    host: str,
    port: int,
    admin_user: str,
    admin_password: str | None,
    admin_database: str,
    role: str,
    role_password: str,
    database: str,
    reset_password: bool = False,
    ssl_mode: str = "prefer",
    connect_timeout: float = 10.0,
) -> BootstrapResult:
    """Create ``role`` and ``database`` if they do not exist.

    An existing role is left untouched unless ``reset_password`` is set, so that
    another installation using the same role is never broken by accident.
    Identifiers and the password are quoted by the server (``format`` with
    ``%I`` and ``%L``), never by string concatenation.
    """
    validate_identifier(role, "role")
    validate_identifier(database, "database")
    connection = await asyncpg.connect(
        host=host,
        port=port,
        user=admin_user,
        password=admin_password,
        database=admin_database,
        ssl=ssl_mode,
        timeout=connect_timeout,
    )
    try:
        secret = scram_verifier(role_password) or role_password
        role_exists = await connection.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        role_created = False
        password_set = False
        if not role_exists:
            statement = await connection.fetchval(
                "SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', $1::text, $2::text)",
                role,
                secret,
            )
            await connection.execute(statement)
            role_created = password_set = True
        elif reset_password:
            statement = await connection.fetchval(
                "SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', $1::text, $2::text)",
                role,
                secret,
            )
            await connection.execute(statement)
            password_set = True

        database_exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", database
        )
        database_created = False
        if not database_exists:
            await _create_owned_database(connection, database=database, role=role)
            database_created = True
    finally:
        await connection.close()
    return BootstrapResult(
        role_created=role_created,
        role_password_set=password_set,
        database_created=database_created,
    )
