"""Session, CSRF and setup tokens.

Tokens are random and opaque. Only a SHA-256 hash of a session token is stored,
so a copy of the database does not contain usable sessions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_CSRF_CONTEXT = b"omniosint/csrf/v1"


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_setup_token() -> str:
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def derive_csrf_token(session_token: str) -> str:
    """CSRF token bound to a session.

    Derived from the session token, so nothing extra is stored. A page on
    another origin can make the browser send the cookie but cannot read this
    value, which the web interface sends back in the ``X-CSRF-Token`` header.
    """
    digest = hmac.new(session_token.encode("utf-8"), _CSRF_CONTEXT, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def tokens_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
