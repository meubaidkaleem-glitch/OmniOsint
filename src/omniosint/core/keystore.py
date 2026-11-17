"""Master key storage.

The master key encrypts everything in the secret store. How the key itself is
protected depends on the platform:

* **Windows** - wrapped with DPAPI for the current user. Another Windows
  account, or the same account on another machine, cannot unwrap it.
* **Elsewhere** - stored in a file readable only by its owner. This is weaker
  (anything running as the user can read it) and ``omniosint doctor`` says so.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any, Protocol

from omniosint.core.crypto import KEY_BYTES, generate_key
from omniosint.core.paths import is_owner_only, write_private_text
from omniosint.core.timeutil import isoformat, utcnow

_DPAPI_ENTROPY = b"OmniOSINT/master-key/v1"


class KeyProtectionError(Exception):
    """The master key could not be protected or recovered."""


class KeyProtector(Protocol):
    name: str
    description: str

    def protect(self, data: bytes) -> bytes: ...

    def unprotect(self, blob: bytes) -> bytes: ...


class FilePermissionProtector:
    """Stores the key as-is and relies on owner-only file permissions."""

    name = "file-permissions"
    description = "Owner-only file permissions (no operating-system key protection)"

    def protect(self, data: bytes) -> bytes:
        return data

    def unprotect(self, blob: bytes) -> bytes:
        return blob


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    _CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def _to_blob(data: bytes) -> tuple[_DataBlob, Any]:
        buffer = ctypes.create_string_buffer(data, len(data))
        blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer  # keep ``buffer`` alive for as long as ``blob`` is used

    def _dpapi_call(function_name: str, data: bytes) -> bytes:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = getattr(crypt32, function_name)
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        function.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        blob_in, _keep_in = _to_blob(data)
        blob_entropy, _keep_entropy = _to_blob(_DPAPI_ENTROPY)
        blob_out = _DataBlob()
        succeeded = function(
            ctypes.byref(blob_in),
            None,
            ctypes.byref(blob_entropy),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
        if not succeeded:
            error = ctypes.get_last_error()
            raise KeyProtectionError(f"{function_name} failed with Windows error {error}")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))

    class DpapiProtector:
        """Wraps data with the Windows Data Protection API (current-user scope)."""

        name = "dpapi"
        description = "Windows DPAPI (current user)"

        def protect(self, data: bytes) -> bytes:
            return _dpapi_call("CryptProtectData", data)

        def unprotect(self, blob: bytes) -> bytes:
            return _dpapi_call("CryptUnprotectData", blob)


def default_protector() -> KeyProtector:
    if sys.platform == "win32":
        return DpapiProtector()
    return FilePermissionProtector()


class MasterKeyStore:
    """Creates, persists and loads the master key."""

    def __init__(self, directory: Path, protector: KeyProtector | None = None) -> None:
        self._path = directory / "master.key"
        self._protector = protector or default_protector()
        self._cached: bytes | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def protector(self) -> KeyProtector:
        return self._protector

    def exists(self) -> bool:
        return self._path.is_file()

    def load_or_create(self) -> bytes:
        if self._cached is None:
            self._cached = self._load() if self.exists() else self._create()
        return self._cached

    def _create(self) -> bytes:
        key = generate_key()
        try:
            wrapped = self._protector.protect(key)
        except OSError as exc:
            raise KeyProtectionError(f"Could not protect the master key: {exc}") from exc
        document = {
            "version": 1,
            "protector": self._protector.name,
            "key": base64.b64encode(wrapped).decode("ascii"),
            "created_at": isoformat(utcnow()),
        }
        write_private_text(self._path, json.dumps(document, indent=2) + "\n")
        return key

    def _load(self) -> bytes:
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
            stored_protector = document["protector"]
            wrapped = base64.b64decode(document["key"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise KeyProtectionError(
                f"The master key file {self._path} is unreadable or corrupt."
            ) from exc
        if stored_protector != self._protector.name:
            raise KeyProtectionError(
                f"The master key was protected with {stored_protector!r}, but this system "
                f"uses {self._protector.name!r}. Secrets stored on another machine or "
                "account cannot be read here and must be entered again."
            )
        try:
            key = self._protector.unprotect(wrapped)
        except (KeyProtectionError, OSError) as exc:
            raise KeyProtectionError(
                "The master key could not be unlocked. It can only be read by the "
                "account that created it, on the same machine."
            ) from exc
        if len(key) != KEY_BYTES:
            raise KeyProtectionError("The master key has an unexpected length.")
        return key

    def describe(self) -> dict[str, Any]:
        return {
            "path": str(self._path),
            "exists": self.exists(),
            "protector": self._protector.name,
            "protector_description": self._protector.description,
            "owner_only": is_owner_only(self._path) if self.exists() else None,
        }
