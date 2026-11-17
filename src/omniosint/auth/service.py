"""Authentication: first-run setup, sign-in, sessions, password changes.

Every public method is one unit of work and commits its own transaction. That
includes the failure paths: a failed sign-in must persist its counter and its
audit event even though the caller receives an error.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.audit.service import ANONYMOUS_ACTOR, Actor, RequestInfo, record
from omniosint.auth.passwords import PasswordHasher, normalize_username, validate_password
from omniosint.auth.permissions import ADMINISTRATOR
from omniosint.auth.throttle import SlidingWindowLimiter
from omniosint.auth.tokens import (
    derive_csrf_token,
    generate_session_token,
    generate_setup_token,
    hash_token,
    tokens_equal,
)
from omniosint.core.config import AuthSettings
from omniosint.core.errors import (
    InvalidCredentials,
    NotFound,
    PermissionDenied,
    RateLimited,
    SessionExpired,
    SessionInvalid,
    SetupAlreadyCompleted,
    ValidationFailed,
)
from omniosint.core.paths import AppPaths, write_private_text
from omniosint.core.timeutil import isoformat, utcnow
from omniosint.database.models import Role, SystemSetting, User, UserSession, user_roles

SETUP_KEY = "setup"
_SETUP_LOCK_ID = 7_304_815_002
_LAST_SEEN_RESOLUTION = timedelta(seconds=60)


class SetupTokenInvalid(PermissionDenied):
    code = "setup_token_invalid"
    default_message = "The setup token is not valid."


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller of a request."""

    user_id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    roles: tuple[str, ...]
    permissions: frozenset[str]
    session_id: uuid.UUID
    auth_method: str
    must_change_password: bool
    session_expires_at: datetime

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def actor(self) -> Actor:
        return Actor(user_id=self.user_id, label=self.username)


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User
    session: UserSession
    token: str
    csrf_token: str


def principal_from(user: User, session_row: UserSession) -> Principal:
    return Principal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        roles=tuple(user.role_names),
        permissions=user.permission_codes,
        session_id=session_row.id,
        auth_method=session_row.auth_method,
        must_change_password=user.must_change_password,
        session_expires_at=session_row.expires_at,
    )


class AuthService:
    def __init__(
        self,
        settings: AuthSettings,
        hasher: PasswordHasher,
        *,
        login_throttle: SlidingWindowLimiter | None = None,
        setup_throttle: SlidingWindowLimiter | None = None,
    ) -> None:
        self._settings = settings
        self._hasher = hasher
        self._login_throttle = login_throttle or SlidingWindowLimiter(
            settings.login_rate_limit_per_minute
        )
        self._setup_throttle = setup_throttle or SlidingWindowLimiter(
            settings.login_rate_limit_per_minute
        )

    @property
    def hasher(self) -> PasswordHasher:
        return self._hasher

    # ------------------------------------------------------------------ setup
    @staticmethod
    async def user_count(session: AsyncSession) -> int:
        result = await session.execute(
            select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        )
        return int(result.scalar_one())

    async def setup_required(self, session: AsyncSession) -> bool:
        return await self.user_count(session) == 0

    async def ensure_setup_token(self, session: AsyncSession, paths: AppPaths) -> str | None:
        """Make sure a first-run setup token exists while no user does.

        Returns the token while setup is pending, ``None`` once a user exists.
        The plaintext lives only in a file the installing user can read; the
        database holds its hash. An existing valid token is reused so that a
        restart does not invalidate a token the user has already copied.
        """
        token_file = paths.setup_token_file
        if not await self.setup_required(session):
            token_file.unlink(missing_ok=True)
            return None

        setting = await session.get(SystemSetting, SETUP_KEY)
        stored_hash = None
        if setting is not None and isinstance(setting.value, dict):
            stored_hash = setting.value.get("token_hash")

        if stored_hash and token_file.is_file():
            try:
                existing = token_file.read_text(encoding="utf-8").strip()
            except OSError:
                existing = ""
            if existing and tokens_equal(hash_token(existing), str(stored_hash)):
                return existing

        token = generate_setup_token()
        value = {"token_hash": hash_token(token), "token_created_at": isoformat(utcnow())}
        if setting is None:
            session.add(SystemSetting(key=SETUP_KEY, value=value))
        else:
            setting.value = value
        await session.commit()
        write_private_text(token_file, token + "\n")
        return token

    async def complete_setup(
        self,
        session: AsyncSession,
        *,
        setup_token: str,
        username: str,
        display_name: str,
        email: str | None,
        password: str,
        paths: AppPaths,
        request: RequestInfo,
    ) -> User:
        """Create the first administrator. Works exactly once."""
        retry_after = self._setup_throttle.hit(request.ip_address or "local")
        if retry_after is not None:
            raise RateLimited(retry_after=math.ceil(retry_after))

        # Serialise concurrent setup attempts: only one can see "no users".
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": _SETUP_LOCK_ID}
        )
        if not await self.setup_required(session):
            await session.rollback()
            raise SetupAlreadyCompleted()

        setting = await session.get(SystemSetting, SETUP_KEY)
        stored_hash = setting.value.get("token_hash") if setting is not None else None
        if not stored_hash or not tokens_equal(hash_token(setup_token.strip()), str(stored_hash)):
            await session.rollback()
            record(
                session,
                action="auth.setup.failure",
                actor=ANONYMOUS_ACTOR,
                outcome="denied",
                details={"reason": "invalid_setup_token"},
                request=request,
            )
            await session.commit()
            raise SetupTokenInvalid()

        normalized = normalize_username(username)
        validate_password(
            password, username=normalized, min_length=self._settings.password_min_length
        )
        role_id = (
            await session.execute(select(Role.id).where(Role.name == ADMINISTRATOR))
        ).scalar_one_or_none()
        if role_id is None:
            await session.rollback()
            raise ValidationFailed(
                "Built-in roles are missing. Run `omniosint db upgrade` and try again."
            )

        now = utcnow()
        user = User(
            username=normalized,
            display_name=display_name.strip() or normalized,
            email=(email.strip().lower() or None) if email else None,
            password_hash=await self._hasher.hash_async(password),
            password_changed_at=now,
        )
        session.add(user)
        await session.flush()
        await session.execute(user_roles.insert().values(user_id=user.id, role_id=role_id))

        assert setting is not None
        setting.value = {"completed_at": isoformat(now), "completed_by": str(user.id)}
        record(
            session,
            action="auth.setup.completed",
            actor=Actor(user_id=user.id, label=user.username),
            target_type="user",
            target_id=user.id,
            request=request,
        )
        await session.commit()
        paths.setup_token_file.unlink(missing_ok=True)
        await session.refresh(user, attribute_names=["roles"])
        return user

    # ------------------------------------------------------------------ login
    async def login(
        self,
        session: AsyncSession,
        *,
        username: str,
        password: str,
        client_type: str = "web",
        auth_method: str = "cookie",
        request: RequestInfo,
    ) -> LoginResult:
        submitted = username.strip().lower()[:64]
        throttle_key = f"{request.ip_address or 'local'}|{submitted}"
        retry_after = self._login_throttle.hit(throttle_key)
        if retry_after is not None:
            record(
                session,
                action="auth.login.throttled",
                actor=ANONYMOUS_ACTOR,
                outcome="denied",
                details={"username": submitted},
                request=request,
            )
            await session.commit()
            raise RateLimited(retry_after=math.ceil(retry_after))

        user = (
            await session.execute(
                select(User)
                .where(User.username == submitted, User.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalar_one_or_none()
        now = utcnow()

        failure_reason: str | None = None
        if user is None:
            failure_reason = "unknown_user"
        elif not user.is_active:
            failure_reason = "inactive"
        elif user.locked_until is not None and user.locked_until > now:
            failure_reason = "locked"

        if failure_reason is not None:
            # Spend the same time as a real verification would.
            await self._hasher.verify_async(self._hasher.dummy_hash, password)
            await self._fail_login(session, user, submitted, failure_reason, request)

        assert user is not None
        if not await self._hasher.verify_async(user.password_hash, password):
            user.failed_login_count += 1
            if user.failed_login_count >= self._settings.max_failed_logins:
                user.failed_login_count = 0
                user.locked_until = now + timedelta(minutes=self._settings.lockout_minutes)
                record(
                    session,
                    action="user.locked",
                    actor=Actor(user_id=user.id, label=user.username),
                    outcome="failure",
                    target_type="user",
                    target_id=user.id,
                    details={
                        "reason": "too_many_failed_logins",
                        "locked_until": isoformat(user.locked_until),
                    },
                    request=request,
                )
            await self._fail_login(session, user, submitted, "bad_password", request)

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if self._hasher.needs_rehash(user.password_hash):
            user.password_hash = await self._hasher.hash_async(password)

        token = generate_session_token()
        session_row = UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            client_type=client_type,
            auth_method=auth_method,
            ip_address=request.ip_address,
            user_agent=(request.user_agent or "")[:255] or None,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=self._settings.session_ttl_hours),
        )
        session.add(session_row)
        await session.flush()
        record(
            session,
            action="auth.login.success",
            actor=Actor(user_id=user.id, label=user.username),
            target_type="session",
            target_id=session_row.id,
            details={"client_type": client_type, "auth_method": auth_method},
            request=request,
        )
        await session.commit()
        self._login_throttle.reset(throttle_key)
        return LoginResult(
            user=user, session=session_row, token=token, csrf_token=derive_csrf_token(token)
        )

    async def _fail_login(
        self,
        session: AsyncSession,
        user: User | None,
        submitted: str,
        reason: str,
        request: RequestInfo,
    ) -> None:
        """Record a failed sign-in, commit, and raise the one generic error."""
        details: dict[str, Any] = {"reason": reason}
        if user is None:
            details["username"] = submitted
        record(
            session,
            action="auth.login.failure",
            actor=Actor(user_id=user.id, label=user.username) if user else ANONYMOUS_ACTOR,
            outcome="failure",
            target_type="user" if user else None,
            target_id=user.id if user else None,
            details=details,
            request=request,
        )
        await session.commit()
        raise InvalidCredentials()

    # ------------------------------------------------------------- sessions
    async def authenticate(
        self, session: AsyncSession, token: str
    ) -> tuple[Principal, UserSession]:
        """Resolve a session token to a principal.

        Raises :class:`SessionInvalid` or :class:`SessionExpired`.
        """
        if not token or len(token) > 512:
            raise SessionInvalid()
        row = (
            await session.execute(
                select(UserSession).where(UserSession.token_hash == hash_token(token))
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            raise SessionInvalid()

        now = utcnow()
        if row.expires_at <= now:
            raise SessionExpired()
        idle_limit = timedelta(minutes=self._settings.session_idle_minutes)
        if now - row.last_seen_at > idle_limit:
            row.revoked_at = now
            row.revoke_reason = "idle_timeout"
            await session.commit()
            raise SessionExpired()

        user = row.user
        if user.deleted_at is not None or not user.is_active:
            raise SessionInvalid()

        if now - row.last_seen_at > _LAST_SEEN_RESOLUTION:
            row.last_seen_at = now
            await session.commit()
        return principal_from(user, row), row

    async def logout(
        self, session: AsyncSession, principal: Principal, request: RequestInfo
    ) -> None:
        await session.execute(
            update(UserSession)
            .where(UserSession.id == principal.session_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoke_reason="logout")
        )
        record(
            session,
            action="auth.logout",
            actor=principal.actor,
            target_type="session",
            target_id=principal.session_id,
            request=request,
        )
        await session.commit()

    async def list_sessions(self, session: AsyncSession, user_id: uuid.UUID) -> list[UserSession]:
        """Active sessions of a user, most recently used first."""
        now = utcnow()
        result = await session.execute(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.last_seen_at.desc())
        )
        return list(result.scalars())

    async def revoke_session(
        self,
        session: AsyncSession,
        principal: Principal,
        session_id: uuid.UUID,
        request: RequestInfo,
    ) -> None:
        """Revoke one of the caller's own sessions."""
        row = await session.get(UserSession, session_id)
        if row is None or row.user_id != principal.user_id or row.revoked_at is not None:
            raise NotFound("The session was not found.")
        row.revoked_at = utcnow()
        row.revoke_reason = "revoked_by_user"
        record(
            session,
            action="auth.session.revoked",
            actor=principal.actor,
            target_type="session",
            target_id=session_id,
            request=request,
        )
        await session.commit()

    # ------------------------------------------------------------ passwords
    async def change_password(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        current_password: str,
        new_password: str,
        request: RequestInfo,
    ) -> int:
        """Change the caller's password. Returns how many other sessions ended."""
        user = await session.get(User, principal.user_id, with_for_update=True)
        if user is None or user.deleted_at is not None:
            raise SessionInvalid()

        if not await self._hasher.verify_async(user.password_hash, current_password):
            record(
                session,
                action="auth.password.change_failed",
                actor=principal.actor,
                outcome="failure",
                target_type="user",
                target_id=user.id,
                details={"reason": "wrong_current_password"},
                request=request,
            )
            await session.commit()
            raise ValidationFailed(
                "The current password is incorrect.",
                details=[
                    {"field": "current_password", "message": "The current password is incorrect."}
                ],
            )

        validate_password(
            new_password,
            username=user.username,
            min_length=self._settings.password_min_length,
            field="new_password",
        )
        if new_password == current_password:
            raise ValidationFailed(
                "The new password must be different from the current one.",
                details=[
                    {
                        "field": "new_password",
                        "message": "Choose a password you are not using now.",
                    }
                ],
            )

        now = utcnow()
        user.password_hash = await self._hasher.hash_async(new_password)
        user.password_changed_at = now
        user.must_change_password = False
        revoked = await session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user.id,
                UserSession.id != principal.session_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason="password_changed")
        )
        ended = int(getattr(revoked, "rowcount", 0) or 0)
        record(
            session,
            action="auth.password.changed",
            actor=principal.actor,
            target_type="user",
            target_id=user.id,
            details={"other_sessions_ended": ended},
            request=request,
        )
        await session.commit()
        return ended
