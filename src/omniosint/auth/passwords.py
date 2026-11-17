"""Password hashing (Argon2id) and password rules."""

from __future__ import annotations

import asyncio
import re
import secrets
from functools import cached_property

from argon2 import PasswordHasher as _Argon2Hasher
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from omniosint.core.config import AuthSettings
from omniosint.core.errors import ValidationFailed

MAX_PASSWORD_LENGTH = 128
_MIN_DISTINCT_CHARACTERS = 5
_PRODUCT_NAME = "omniosint"

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class PasswordHasher:
    """Argon2id hashing. Hashing is CPU- and memory-heavy by design, so the
    ``*_async`` variants run it in a worker thread to keep the event loop free."""

    def __init__(self, settings: AuthSettings) -> None:
        self._hasher = _Argon2Hasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
            type=Type.ID,
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        try:
            return bool(self._hasher.verify(encoded, password))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, encoded: str) -> bool:
        try:
            return bool(self._hasher.check_needs_rehash(encoded))
        except InvalidHashError:
            return True

    @cached_property
    def dummy_hash(self) -> str:
        """Hash of a random value, verified when no user matches so that a
        failed sign-in takes the same time whether or not the account exists."""
        return self.hash(secrets.token_urlsafe(24))

    async def hash_async(self, password: str) -> str:
        return await asyncio.to_thread(self.hash, password)

    async def verify_async(self, encoded: str, password: str) -> bool:
        return await asyncio.to_thread(self.verify, encoded, password)


def password_problems(password: str, *, username: str, min_length: int) -> list[str]:
    """Return every reason ``password`` is unacceptable (empty when it is fine).

    Follows current guidance: length matters most, no forced character classes,
    no periodic expiry; reject passwords built from obvious context.
    """
    problems: list[str] = []
    if len(password) < min_length:
        problems.append(f"Use at least {min_length} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    lowered = password.lower()
    if username and len(username) >= 3 and username.lower() in lowered:
        problems.append("Do not include your username.")
    if _PRODUCT_NAME in lowered:
        problems.append("Do not include the product name.")
    if len(set(password)) < _MIN_DISTINCT_CHARACTERS:
        problems.append(f"Use at least {_MIN_DISTINCT_CHARACTERS} different characters.")
    return problems


def validate_password(
    password: str, *, username: str, min_length: int, field: str = "password"
) -> None:
    problems = password_problems(password, username=username, min_length=min_length)
    if problems:
        raise ValidationFailed(
            "The password does not meet the requirements.",
            details=[{"field": field, "message": problem} for problem in problems],
        )


def normalize_username(value: str) -> str:
    """Lower-case and validate a username."""
    candidate = value.strip().lower()
    if not USERNAME_PATTERN.fullmatch(candidate):
        raise ValidationFailed(
            "The username is not valid.",
            details=[
                {
                    "field": "username",
                    "message": (
                        "Use 3 to 64 characters: letters, digits, dot, underscore or "
                        "hyphen, starting with a letter or digit."
                    ),
                }
            ],
        )
    return candidate
