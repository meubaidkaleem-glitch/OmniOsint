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
    COLLECTION_READ = "collection:read"
    COLLECTION_RUN = "collection:run"
    COLLECTION_APPROVE = "collection:approve"
    EVIDENCE_READ = "evidence:read"
    EVIDENCE_READ_RAW = "evidence:read_raw"
    SCOPES_READ = "scopes:read"
    SCOPES_MANAGE = "scopes:manage"


PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    Permission.USERS_READ: "View user accounts.",
    Permission.USERS_MANAGE: "Create, change, lock, unlock and remove user accounts.",
    Permission.ROLES_READ: "View roles and the permissions they grant.",
    Permission.AUDIT_READ: "View the audit trail.",
    Permission.SYSTEM_READ: "View detailed system and service status.",
    Permission.SYSTEM_MANAGE: "Change system settings and run maintenance operations.",
    Permission.COLLECTION_READ: (
        "Classify indicators, preview collection plans, and view collection requests and jobs."
    ),
    Permission.COLLECTION_RUN: "Submit collection plans, and cancel or retry jobs.",
    Permission.COLLECTION_APPROVE: (
        "Approve jobs that wait for approval: active operations and paid calls."
    ),
    Permission.EVIDENCE_READ: (
        "View evidence, entities and sources, and raw responses with credentials masked."
    ),
    Permission.EVIDENCE_READ_RAW: "View raw responses unmasked (each view is audited).",
    Permission.SCOPES_READ: "View scopes and check targets against them.",
    Permission.SCOPES_MANAGE: (
        "Record scopes of written authorisation, change their rules and revoke them."
    ),
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
            "Investigation work: classification, collection and evidence. Approving active "
            "operations and recording scopes stay with administrators."
        ),
        permissions=frozenset(
            {
                Permission.COLLECTION_READ,
                Permission.COLLECTION_RUN,
                Permission.EVIDENCE_READ,
                Permission.SCOPES_READ,
            }
        ),
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
                Permission.COLLECTION_READ,
                Permission.EVIDENCE_READ,
                Permission.SCOPES_READ,
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
