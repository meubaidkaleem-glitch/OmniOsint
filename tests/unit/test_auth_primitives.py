from __future__ import annotations

import pytest

from omniosint.auth.passwords import (
    PasswordHasher,
    normalize_username,
    password_problems,
    validate_password,
)
from omniosint.auth.permissions import BUILTIN_ROLES, PERMISSION_DESCRIPTIONS, Permission
from omniosint.auth.throttle import SlidingWindowLimiter
from omniosint.auth.tokens import (
    derive_csrf_token,
    generate_session_token,
    hash_token,
    tokens_equal,
)
from omniosint.core.config import AuthSettings
from omniosint.core.errors import ValidationFailed

FAST = AuthSettings(argon2_time_cost=1, argon2_memory_kib=8192, argon2_parallelism=1)


@pytest.mark.parametrize(
    ("password", "expected_fragment"),
    [
        ("short", "at least 12"),
        ("x" * 129, "at most 128"),
        ("alice-likes-long-words", "username"),
        ("my omniosint password", "product name"),
        ("aaaaaaaaaaaaaaaa", "different characters"),
    ],
)
def test_password_problems(password: str, expected_fragment: str) -> None:
    problems = password_problems(password, username="alice", min_length=12)
    assert any(expected_fragment in problem for problem in problems), problems


def test_good_password_has_no_problems() -> None:
    assert password_problems("correct horse battery", username="alice", min_length=12) == []


def test_validate_password_lists_every_problem() -> None:
    with pytest.raises(ValidationFailed) as caught:
        validate_password("aaa", username="alice", min_length=12, field="new_password")
    fields = {detail["field"] for detail in caught.value.details}
    assert fields == {"new_password"}
    assert len(caught.value.details) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Alice", "alice"), ("  bob.smith  ", "bob.smith"), ("a_b-c", "a_b-c"), ("x99", "x99")],
)
def test_normalize_username(raw: str, expected: str) -> None:
    assert normalize_username(raw) == expected


@pytest.mark.parametrize("raw", ["ab", "-leading", "has space", "ünicode", "a" * 65, "semi;colon"])
def test_invalid_usernames(raw: str) -> None:
    with pytest.raises(ValidationFailed):
        normalize_username(raw)


def test_hasher_round_trip_and_rehash_detection() -> None:
    hasher = PasswordHasher(FAST)
    encoded = hasher.hash("correct horse battery")
    assert encoded.startswith("$argon2id$")
    assert hasher.verify(encoded, "correct horse battery")
    assert not hasher.verify(encoded, "wrong password value")
    assert not hasher.verify("not-a-hash", "anything")
    assert not hasher.needs_rehash(encoded)
    stronger = PasswordHasher(
        AuthSettings(argon2_time_cost=2, argon2_memory_kib=8192, argon2_parallelism=1)
    )
    assert stronger.needs_rehash(encoded)
    assert stronger.needs_rehash("garbage")


def test_production_hashing_parameters_are_strong() -> None:
    defaults = AuthSettings()
    assert defaults.argon2_memory_kib >= 65536
    assert defaults.argon2_time_cost >= 3
    assert defaults.password_min_length >= 12


def test_session_tokens_are_random_and_hashed() -> None:
    first, second = generate_session_token(), generate_session_token()
    assert first != second
    assert len(first) >= 43
    assert hash_token(first) != first
    assert len(hash_token(first)) == 64


def test_csrf_token_is_bound_to_the_session() -> None:
    session_a, session_b = generate_session_token(), generate_session_token()
    assert derive_csrf_token(session_a) == derive_csrf_token(session_a)
    assert derive_csrf_token(session_a) != derive_csrf_token(session_b)
    assert session_a not in derive_csrf_token(session_a)
    assert tokens_equal("abc", "abc")
    assert not tokens_equal("abc", "abd")


def test_sliding_window_limiter() -> None:
    now = [1000.0]
    limiter = SlidingWindowLimiter(3, window_seconds=60, clock=lambda: now[0])
    assert [limiter.hit("k") for _ in range(3)] == [None, None, None]
    retry = limiter.hit("k")
    assert retry is not None and 59 <= retry <= 60
    assert limiter.hit("other") is None  # keys are independent
    now[0] += 61
    assert limiter.hit("k") is None
    limiter.reset("k")
    assert [limiter.hit("k") for _ in range(3)] == [None, None, None]


def test_limiter_evicts_oldest_keys() -> None:
    limiter = SlidingWindowLimiter(1, max_keys=2, clock=lambda: 0.0)
    limiter.hit("a")
    limiter.hit("b")
    limiter.hit("c")  # evicts "a"
    assert limiter.hit("a") is None
    with pytest.raises(ValueError, match="at least 1"):
        SlidingWindowLimiter(0)


def test_every_permission_is_described_and_roles_are_consistent() -> None:
    assert set(PERMISSION_DESCRIPTIONS) == set(Permission)
    names = [role.name for role in BUILTIN_ROLES]
    assert len(names) == len(set(names))
    administrator = next(role for role in BUILTIN_ROLES if role.name == "administrator")
    assert administrator.permissions == frozenset(Permission)
    auditor = next(role for role in BUILTIN_ROLES if role.name == "auditor")
    assert Permission.USERS_MANAGE not in auditor.permissions
    assert Permission.AUDIT_READ in auditor.permissions
