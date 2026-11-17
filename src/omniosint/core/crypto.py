"""Authenticated encryption for data at rest.

One format is used everywhere a secret is stored (the local secret store now,
provider credentials and stored evidence in later phases)::

    version (1 byte) || nonce (12 bytes) || AES-256-GCM ciphertext and tag

The associated data binds a ciphertext to its purpose, so a value encrypted for
one name cannot be moved to another.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12
_VERSION = 1


class DecryptionError(Exception):
    """The ciphertext is malformed, was tampered with, or the key is wrong."""


def generate_key() -> bytes:
    return os.urandom(KEY_BYTES)


class SecretBox:
    """AES-256-GCM with a random nonce per message."""

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError(f"key must be {KEY_BYTES} bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, *, aad: bytes = b"") -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._aead.encrypt(nonce, plaintext, aad or None)
        return bytes([_VERSION]) + nonce + ciphertext

    def decrypt(self, token: bytes, *, aad: bytes = b"") -> bytes:
        if len(token) < 1 + NONCE_BYTES + 16:
            raise DecryptionError("ciphertext is too short")
        if token[0] != _VERSION:
            raise DecryptionError(f"unsupported ciphertext version {token[0]}")
        nonce = token[1 : 1 + NONCE_BYTES]
        ciphertext = token[1 + NONCE_BYTES :]
        try:
            return self._aead.decrypt(nonce, ciphertext, aad or None)
        except InvalidTag as exc:
            raise DecryptionError("ciphertext failed authentication") from exc

    def encrypt_text(self, plaintext: str, *, aad: str = "") -> str:
        token = self.encrypt(plaintext.encode("utf-8"), aad=aad.encode("utf-8"))
        return base64.urlsafe_b64encode(token).decode("ascii")

    def decrypt_text(self, token: str, *, aad: str = "") -> str:
        try:
            raw = base64.urlsafe_b64decode(token.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise DecryptionError("ciphertext is not valid base64") from exc
        return self.decrypt(raw, aad=aad.encode("utf-8")).decode("utf-8")
