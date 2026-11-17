"""Permissions and built-in roles.

Permissions are ``resource:action`` strings. Built-in roles are defined here
and synchronised to the database on every upgrade (``omniosint db upgrade``),
so the code is the source of truth for what a built-in role may do.

New permissions are added by the phase that introduces the resource they
protect; none exist for features that are not built yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Permission(StrEnum):
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    ROLES_READ = "roles:read"
    AUDIT_READ = "audit:read"
    SYSTEM_READ = "system:read"
    SYSTEM_MANAGE = "system:manage"


PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    Permission.USERS_READ: "View user accounts.",
    Permission.USERS_MANAGE: "Create, change, lock, unlock and remove user accounts.",
    Permission.ROLES_READ: "View roles and the permissions they grant.",
    Permission.AUDIT_READ: "View the audit trail.",
    Permission.SYSTEM_READ: "View detailed system and service status.",
    Permission.SYSTEM_MANAGE: "Change system settings and run maintenance operations.",
}


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    name: str
    description: str
    permissions: frozenset[Permission]


ADMINISTRATOR = "administrator"
ANALYST = "analyst"
AUDITOR = "auditor"
VIEWER = "viewer"

BUILTIN_ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        name=ADMINISTRATOR,
        description="Full access, including user management and system settings.",
        permissions=frozenset(Permission),
    ),
    RoleDefinition(
        name=ANALYST,
        description=(
            "Investigation work. Receives permissions as intelligence modules are added."
        ),
        permissions=frozenset(),
    ),
    RoleDefinition(
        name=AUDITOR,
        description="Read-only access, including the audit trail and system status.",
        permissions=frozenset(
            {
                Permission.USERS_READ,
                Permission.ROLES_READ,
                Permission.AUDIT_READ,
                Permission.SYSTEM_READ,
            }
        ),
    ),
    RoleDefinition(
        name=VIEWER,
        description="Read-only access to what they are assigned.",
        permissions=frozenset(),
    ),
)

BUILTIN_ROLE_NAMES: frozenset[str] = frozenset(role.name for role in BUILTIN_ROLES)
