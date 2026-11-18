"""Encrypted, content-addressed storage for raw responses (ADR-013).

An object is identified by the SHA-256 of its content, so identical responses
are stored once and integrity can always be checked. On disk each object is
compressed, then encrypted with AES-256-GCM under the installation's object
key, which lives in the protected secret store. The associated data binds each
file to its hash, so files cannot be swapped. File names are an HMAC of the
hash, so the directory listing does not reveal which content is stored.

Losing the object key (for example by moving the data folder to another
Windows account, where DPAPI cannot open the secret store) makes the stored
objects unreadable. Backups therefore export objects decrypted inside the
archive and the restore encrypts them again under the local key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import zlib
from dataclasses import dataclass
from pathlib import Path

from omniosint.core.crypto import DecryptionError, SecretBox, generate_key
from omniosint.core.paths import restrict_to_owner
from omniosint.core.secrets import OBJECT_STORE_KEY, SecretStore

ENCRYPTION = "aes-256-gcm"
_COMPRESSED = b"z"
_PLAIN = b"r"


class ObjectStoreError(Exception):
    pass


class ObjectMissing(ObjectStoreError):
    pass


class ObjectCorrupted(ObjectStoreError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    sha256: str
    size: int
    created: bool


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def object_key(secrets: SecretStore) -> bytes:
    encoded = secrets.get_or_create(
        OBJECT_STORE_KEY, lambda: base64.urlsafe_b64encode(generate_key()).decode("ascii")
    )
    return base64.urlsafe_b64decode(encoded)


class ObjectStore:
    def __init__(self, root: Path, key: bytes) -> None:
        self._root = root
        self._box = SecretBox(key)
        self._name_key = hmac.new(key, b"omniosint-object-names", hashlib.sha256).digest()

    @classmethod
    def open(cls, root: Path, secrets: SecretStore) -> ObjectStore:
        return cls(root, object_key(secrets))

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, sha256: str) -> Path:
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            raise ValueError("not a SHA-256 hex digest")
        name = hmac.new(self._name_key, sha256.encode("ascii"), hashlib.sha256).hexdigest()
        return self._root / name[:2] / name[2:4] / name

    def exists(self, sha256: str) -> bool:
        return self._path(sha256).is_file()

    def put(self, content: bytes) -> StoredObject:
        digest = sha256_hex(content)
        path = self._path(digest)
        if path.is_file():
            return StoredObject(digest, len(content), created=False)
        compressed = zlib.compress(content, level=6)
        body = _COMPRESSED + compressed if len(compressed) < len(content) else _PLAIN + content
        token = self._box.encrypt(body, aad=f"omniosint-object:{digest}".encode("ascii"))
        path.parent.mkdir(parents=True, exist_ok=True)
        restrict_to_owner(path.parent)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(token)
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return StoredObject(digest, len(content), created=True)

    def get(self, sha256: str) -> bytes:
        path = self._path(sha256)
        try:
            token = path.read_bytes()
        except FileNotFoundError as error:
            raise ObjectMissing(f"Object {sha256} is not in the store.") from error
        try:
            body = self._box.decrypt(token, aad=f"omniosint-object:{sha256}".encode("ascii"))
        except DecryptionError as error:
            raise ObjectCorrupted(
                f"Object {sha256} could not be decrypted: "
                "it was altered, or the object key changed."
            ) from error
        marker, payload = body[:1], body[1:]
        try:
            content = zlib.decompress(payload) if marker == _COMPRESSED else payload
        except zlib.error as error:
            raise ObjectCorrupted(f"Object {sha256} is damaged.") from error
        if sha256_hex(content) != sha256:
            raise ObjectCorrupted(f"Object {sha256} does not match its hash.")
        return content

    def delete(self, sha256: str) -> bool:
        path = self._path(sha256)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True
