"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from omniosint.database.models.audit import AuditEvent
from omniosint.database.models.collection import (
    CollectionJob,
    CollectionJobEvent,
    CollectionRequest,
    CollectionResult,
    Provider,
    ProviderUsage,
)
from omniosint.database.models.identity import (
    Permission,
    Role,
    User,
    UserSession,
    role_permissions,
    user_roles,
)
from omniosint.database.models.intel import Entity, Evidence, EvidenceSource, RawObject
from omniosint.database.models.scope import Scope, ScopeRule
from omniosint.database.models.search import SavedSearch, SearchHistoryEntry
from omniosint.database.models.system import ServiceInstance, SystemSetting

__all__ = [
    "AuditEvent",
    "CollectionJob",
    "CollectionJobEvent",
    "CollectionRequest",
    "CollectionResult",
    "Entity",
    "Evidence",
    "EvidenceSource",
    "Permission",
    "Provider",
    "ProviderUsage",
    "RawObject",
    "Role",
    "SavedSearch",
    "Scope",
    "ScopeRule",
    "SearchHistoryEntry",
    "ServiceInstance",
    "SystemSetting",
    "User",
    "UserSession",
    "role_permissions",
    "user_roles",
]
