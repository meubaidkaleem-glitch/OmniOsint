"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from omniosint.database.models.audit import AuditEvent
from omniosint.database.models.identity import (
    Permission,
    Role,
    User,
    UserSession,
    role_permissions,
    user_roles,
)
from omniosint.database.models.system import ServiceInstance, SystemSetting

__all__ = [
    "AuditEvent",
    "Permission",
    "Role",
    "ServiceInstance",
    "SystemSetting",
    "User",
    "UserSession",
    "role_permissions",
    "user_roles",
]
