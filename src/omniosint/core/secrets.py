"""Local protected secret store.

Named secrets (the database password now, provider API keys from Phase 5) are
encrypted with the master key and kept in one JSON file in the data directory.
Values are never written to logs, settings files or API responses.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omniosint.core.crypto import DecryptionError, SecretBox
from omniosint.core.filelock import exclusive_lock
from omniosint.core.keystore import KeyProtectionError, MasterKeyStore
from omniosint.core.paths import AppPaths, write_private_text
from omniosint.core.timeutil import isoformat, utcnow

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

DATABASE_PASSWORD = "database.password"  # noqa: S105 - the name of a secret, not a secret
OBJECT_STORE_KEY = "storage.object-key"


class SecretStoreError(Exception):
    """The secret store could not be read or written."""


def validate_secret_name(name: str) -> str:
    if not _NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Secret names use lower-case letters, digits, dots, underscores and hyphens "
            "(for example: database.password)."
        )
    return name


class SecretStore:
    def __init__(self, paths: AppPaths, key_store: MasterKeyStore | None = None) -> None:
        self._file = paths.secrets_dir / "secrets.json"
        self._lock = paths.secrets_dir / ".secrets.lock"
        self._keys = key_store or MasterKeyStore(paths.secrets_dir)

    @property
    def path(self) -> Path:
        return self._file

    @property
    def key_store(self) -> MasterKeyStore:
        return self._keys

    # -- persistence ---------------------------------------------------------
    def _read(self) -> dict[str, dict[str, Any]]:
        if not self._file.is_file():
            return {}
        try:
            document = json.loads(self._file.read_text(encoding="utf-8"))
            secrets = document["secrets"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SecretStoreError(f"The secret store {self._file} is unreadable.") from exc
        if not isinstance(secrets, dict):
            raise SecretStoreError(f"The secret store {self._file} is malformed.")
        return secrets

    def _write(self, secrets: dict[str, dict[str, Any]]) -> None:
        document = {"version": 1, "secrets": dict(sorted(secrets.items()))}
        write_private_text(self._file, json.dumps(document, indent=2) + "\n")

    def _box(self) -> SecretBox:
        try:
            return SecretBox(self._keys.load_or_create())
        except KeyProtectionError as exc:
            raise SecretStoreError(str(exc)) from exc

    # -- public API ----------------------------------------------------------
    def names(self) -> list[str]:
        return sorted(self._read())

    def describe(self) -> list[dict[str, Any]]:
        """Names and timestamps only; never values."""
        return [
            {"name": name, "updated_at": entry.get("updated_at")}
            for name, entry in sorted(self._read().items())
        ]

    def get(self, name: str) -> str | None:
        validate_secret_name(name)
        entry = self._read().get(name)
        if entry is None:
            return None
        try:
            return self._box().decrypt_text(str(entry["value"]), aad=name)
        except (DecryptionError, KeyError) as exc:
            raise SecretStoreError(
                f"The stored secret {name!r} could not be decrypted. Enter it again with "
                f"`omniosint secrets set {name}`."
            ) from exc

    def set(self, name: str, value: str) -> None:
        validate_secret_name(name)
        if not value:
            raise ValueError("A secret value must not be empty.")
        # The API, the worker and the CLI may write at once; the lock keeps
        # one writer from undoing another's change.
        with exclusive_lock(self._lock):
            secrets = self._read()
            secrets[name] = {
                "value": self._box().encrypt_text(value, aad=name),
                "updated_at": isoformat(utcnow()),
            }
            self._write(secrets)

    def get_or_create(self, name: str, factory: Callable[[], str]) -> str:
        """The secret ``name``, created with ``factory`` if it does not exist yet.
        Safe when several processes ask at the same time: all get the same value."""
        existing = self.get(name)
        if existing is not None:
            return existing
        with exclusive_lock(self._lock):
            existing = self.get(name)
            if existing is not None:
                return existing
            value = factory()
            if not value:
                raise ValueError("A secret value must not be empty.")
            secrets = self._read()
            secrets[name] = {
                "value": self._box().encrypt_text(value, aad=name),
                "updated_at": isoformat(utcnow()),
            }
            self._write(secrets)
            return value

    def delete(self, name: str) -> bool:
        validate_secret_name(name)
        with exclusive_lock(self._lock):
            secrets = self._read()
            if name not in secrets:
                return False
            del secrets[name]
            self._write(secrets)
            return True
