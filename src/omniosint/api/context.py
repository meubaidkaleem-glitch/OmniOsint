"""Application context: the long-lived objects an API process owns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from omniosint.auth.passwords import PasswordHasher
from omniosint.auth.service import AuthService
from omniosint.core.config import Settings
from omniosint.core.paths import AppPaths
from omniosint.core.timeutil import utcnow
from omniosint.database.engine import Database
from omniosint.system.registry import ServiceHeartbeat
from omniosint.users.service import UserService


@dataclass(slots=True)
class AppContext:
    settings: Settings
    paths: AppPaths
    db: Database
    auth: AuthService
    users: UserService
    started_at: datetime
    heartbeat: ServiceHeartbeat | None = None

    @classmethod
    def build(cls, settings: Settings, paths: AppPaths) -> AppContext:
        hasher = PasswordHasher(settings.auth)
        return cls(
            settings=settings,
            paths=paths,
            db=Database.from_settings(settings, paths, application_name="omniosint-api"),
            auth=AuthService(settings.auth, hasher),
            users=UserService(settings.auth, hasher),
            started_at=utcnow(),
        )
