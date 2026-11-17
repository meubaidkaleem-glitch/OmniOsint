"""User administration.

Every public method that changes data is one unit of work: it validates, writes
its audit event and commits. One invariant is enforced throughout: the system
always keeps at least one active administrator.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.audit.service import Actor, RequestInfo, record
from omniosint.auth.passwords import PasswordHasher, normalize_username, validate_password
from omniosint.auth.permissions import ADMINISTRATOR
from omniosint.core.config import AuthSettings
from omniosint.core.errors import Conflict, LastAdministrator, NotFound, ValidationFailed
from omniosint.core.pagination import Page, clamp_limit, decode_cursor, encode_cursor
from omniosint.core.timeutil import utcnow
from omniosint.database.models import Role, User, UserSession, user_roles

_ADMIN_LOCK_ID = 7_304_815_003


class _Unset:
    """Marks an argument that was not supplied (distinct from ``None``)."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()


@dataclass(frozen=True, slots=True)
class UserChanges:
    """What an update actually changed, for the audit trail."""

    fields: dict[str, Any]


class UserService:
    def __init__(self, settings: AuthSettings, hasher: PasswordHasher) -> None:
        self._settings = settings
        self._hasher = hasher

    # ------------------------------------------------------------- queries
    async def get_user(self, session: AsyncSession, user_id: uuid.UUID) -> User:
        user = await session.get(User, user_id)
        if user is None or user.deleted_at is not None:
            raise NotFound("The user was not found.")
        return user

    async def get_by_username(self, session: AsyncSession, username: str) -> User | None:
        result = await session.execute(
            select(User).where(User.username == username.strip().lower(), User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_users(
        self,
        session: AsyncSession,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        search: str | None = None,
    ) -> Page[User]:
        """Users ordered by username, keyset-paginated."""
        page_size = clamp_limit(limit)
        filters = [User.deleted_at.is_(None)]
        if search and search.strip():
            # The pattern is a bound parameter; % and _ are escaped so that the
            # search term is always treated literally.
            term = search.strip().lower()
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    User.username.like(pattern, escape="\\"),
                    func.lower(User.display_name).like(pattern, escape="\\"),
                    func.lower(func.coalesce(User.email, "")).like(pattern, escape="\\"),
                )
            )

        total = int(
            (await session.execute(select(func.count()).select_from(User).where(*filters)))
            .scalar_one()
        )

        query = select(User).where(*filters)
        if cursor:
            (after,) = decode_cursor(cursor, parts=1)
            query = query.where(User.username > str(after))
        query = query.order_by(User.username).limit(page_size + 1)
        rows = list((await session.execute(query)).scalars())
        items = rows[:page_size]
        next_cursor = encode_cursor([items[-1].username]) if len(rows) > page_size else None
        return Page(items=items, next_cursor=next_cursor, total=total)

    async def list_roles(self, session: AsyncSession) -> list[Role]:
        return list((await session.execute(select(Role).order_by(Role.name))).scalars())

    async def role_member_counts(self, session: AsyncSession) -> dict[uuid.UUID, int]:
        result = await session.execute(
            select(user_roles.c.role_id, func.count())
            .join(User, User.id == user_roles.c.user_id)
            .where(User.deleted_at.is_(None))
            .group_by(user_roles.c.role_id)
        )
        return {role_id: int(count) for role_id, count in result}

    # ------------------------------------------------------------- helpers
    async def _resolve_roles(self, session: AsyncSession, names: Sequence[str]) -> list[Role]:
        wanted = sorted({name.strip().lower() for name in names if name.strip()})
        if not wanted:
            raise ValidationFailed(
                "Assign at least one role.",
                details=[{"field": "roles", "message": "Assign at least one role."}],
            )
        roles = list((await session.execute(select(Role).where(Role.name.in_(wanted)))).scalars())
        missing = sorted(set(wanted) - {role.name for role in roles})
        if missing:
            raise ValidationFailed(
                "Unknown role.",
                details=[
                    {"field": "roles", "message": f"Unknown role: {name}."} for name in missing
                ],
            )
        return roles

    @staticmethod
    def _clean_email(email: str | None) -> str | None:
        if email is None:
            return None
        cleaned = email.strip().lower()
        return cleaned or None

    @staticmethod
    def _clean_display_name(display_name: str, fallback: str) -> str:
        cleaned = " ".join(display_name.split())
        return cleaned[:128] or fallback

    async def _lock_administrators(self, session: AsyncSession) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": _ADMIN_LOCK_ID}
        )

    async def _other_active_administrators(
        self, session: AsyncSession, excluding: uuid.UUID
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(User)
            .join(user_roles, user_roles.c.user_id == User.id)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(
                Role.name == ADMINISTRATOR,
                User.deleted_at.is_(None),
                User.is_active.is_(True),
                User.id != excluding,
            )
        )
        return int(result.scalar_one())

    async def _revoke_sessions(self, session: AsyncSession, user_id: uuid.UUID, reason: str) -> int:
        result = await session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoke_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    def _conflict_from(exc: IntegrityError) -> Conflict:
        message = str(getattr(exc, "orig", exc))
        if "uq_users_email_lower" in message:
            return Conflict(
                "That email address is already used by another account.",
                details=[{"field": "email", "message": "Already in use."}],
            )
        return Conflict(
            "That username is already in use.",
            details=[{"field": "username", "message": "Already in use."}],
        )

    # ------------------------------------------------------------ mutations
    async def create_user(
        self,
        session: AsyncSession,
        *,
        actor: Actor,
        username: str,
        display_name: str,
        email: str | None,
        password: str,
        roles: Sequence[str],
        must_change_password: bool = True,
        request: RequestInfo | None = None,
    ) -> User:
        normalized = normalize_username(username)
        validate_password(
            password, username=normalized, min_length=self._settings.password_min_length
        )
        role_rows = await self._resolve_roles(session, roles)

        # Deleted users keep their username so that old audit entries stay
        # unambiguous; the name cannot be reused.
        existing = await session.execute(select(User.id).where(User.username == normalized))
        if existing.first() is not None:
            raise Conflict(
                "That username is already in use.",
                details=[{"field": "username", "message": "Already in use."}],
            )

        now = utcnow()
        user = User(
            username=normalized,
            display_name=self._clean_display_name(display_name, normalized),
            email=self._clean_email(email),
            password_hash=await self._hasher.hash_async(password),
            password_changed_at=now,
            must_change_password=must_change_password,
        )
        session.add(user)
        try:
            await session.flush()
            await session.execute(
                user_roles.insert(),
                [
                    {"user_id": user.id, "role_id": role.id, "granted_by": actor.user_id}
                    for role in role_rows
                ],
            )
            record(
                session,
                action="user.created",
                actor=actor,
                target_type="user",
                target_id=user.id,
                details={
                    "username": user.username,
                    "roles": sorted(role.name for role in role_rows),
                    "must_change_password": must_change_password,
                },
                request=request,
            )
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise self._conflict_from(exc) from exc
        await session.refresh(user, attribute_names=["roles"])
        return user

    async def update_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        *,
        actor: Actor,
        display_name: str | Any = UNSET,
        email: str | None | Any = UNSET,
        is_active: bool | Any = UNSET,
        roles: Sequence[str] | Any = UNSET,
        request: RequestInfo | None = None,
    ) -> User:
        await self._lock_administrators(session)
        user = await session.get(User, user_id, with_for_update=True)
        if user is None or user.deleted_at is not None:
            await session.rollback()
            raise NotFound("The user was not found.")

        changes: dict[str, Any] = {}
        was_admin = ADMINISTRATOR in user.role_names

        if display_name is not UNSET:
            cleaned = self._clean_display_name(display_name, user.username)
            if cleaned != user.display_name:
                user.display_name = cleaned
                changes["display_name"] = cleaned

        if email is not UNSET:
            cleaned_email = self._clean_email(email)
            if cleaned_email != user.email:
                user.email = cleaned_email
                changes["email"] = "changed" if cleaned_email else "removed"

        new_role_rows: list[Role] | None = None
        if roles is not UNSET:
            new_role_rows = await self._resolve_roles(session, roles)
            new_names = sorted(role.name for role in new_role_rows)
            if new_names != sorted(user.role_names):
                changes["roles"] = new_names
            else:
                new_role_rows = None

        deactivating = is_active is not UNSET and is_active is False and user.is_active
        if is_active is not UNSET and bool(is_active) != user.is_active:
            changes["is_active"] = bool(is_active)

        losing_admin = (
            was_admin
            and new_role_rows is not None
            and ADMINISTRATOR not in {role.name for role in new_role_rows}
        )
        if (
            was_admin
            and user.is_active
            and (deactivating or losing_admin)
            and await self._other_active_administrators(session, user.id) == 0
        ):
            await session.rollback()
            raise LastAdministrator()

        if "is_active" in changes:
            user.is_active = bool(is_active)
            if not user.is_active:
                await self._revoke_sessions(session, user.id, "account_deactivated")

        if new_role_rows is not None:
            await session.execute(user_roles.delete().where(user_roles.c.user_id == user.id))
            await session.execute(
                user_roles.insert(),
                [
                    {"user_id": user.id, "role_id": role.id, "granted_by": actor.user_id}
                    for role in new_role_rows
                ],
            )

        if not changes:
            await session.rollback()
            return await self.get_user(session, user_id)

        record(
            session,
            action="user.updated",
            actor=actor,
            target_type="user",
            target_id=user.id,
            details={"username": user.username, "changes": changes},
            request=request,
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise self._conflict_from(exc) from exc
        await session.refresh(user, attribute_names=["roles"])
        return user

    async def reset_password(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        *,
        actor: Actor,
        new_password: str,
        must_change_password: bool = True,
        request: RequestInfo | None = None,
    ) -> User:
        """Set a new password on behalf of a user and end all their sessions."""
        user = await session.get(User, user_id, with_for_update=True)
        if user is None or user.deleted_at is not None:
            await session.rollback()
            raise NotFound("The user was not found.")
        validate_password(
            new_password,
            username=user.username,
            min_length=self._settings.password_min_length,
            field="new_password",
        )
        user.password_hash = await self._hasher.hash_async(new_password)
        user.password_changed_at = utcnow()
        user.must_change_password = must_change_password
        user.failed_login_count = 0
        user.locked_until = None
        ended = await self._revoke_sessions(session, user.id, "password_reset")
        record(
            session,
            action="user.password.reset",
            actor=actor,
            target_type="user",
            target_id=user.id,
            details={"username": user.username, "sessions_ended": ended},
            request=request,
        )
        await session.commit()
        return user

    async def unlock_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        *,
        actor: Actor,
        request: RequestInfo | None = None,
    ) -> User:
        user = await session.get(User, user_id, with_for_update=True)
        if user is None or user.deleted_at is not None:
            await session.rollback()
            raise NotFound("The user was not found.")
        user.failed_login_count = 0
        user.locked_until = None
        record(
            session,
            action="user.unlocked",
            actor=actor,
            target_type="user",
            target_id=user.id,
            details={"username": user.username},
            request=request,
        )
        await session.commit()
        return user

    async def delete_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        *,
        actor: Actor,
        request: RequestInfo | None = None,
    ) -> None:
        """Soft-delete a user. The account can no longer sign in."""
        await self._lock_administrators(session)
        user = await session.get(User, user_id, with_for_update=True)
        if user is None or user.deleted_at is not None:
            await session.rollback()
            raise NotFound("The user was not found.")
        if actor.user_id is not None and actor.user_id == user.id:
            await session.rollback()
            raise Conflict("You cannot delete your own account.")
        if (
            ADMINISTRATOR in user.role_names
            and user.is_active
            and await self._other_active_administrators(session, user.id) == 0
        ):
            await session.rollback()
            raise LastAdministrator()

        user.deleted_at = utcnow()
        user.is_active = False
        await self._revoke_sessions(session, user.id, "account_deleted")
        record(
            session,
            action="user.deleted",
            actor=actor,
            target_type="user",
            target_id=user.id,
            details={"username": user.username},
            request=request,
        )
        await session.commit()
