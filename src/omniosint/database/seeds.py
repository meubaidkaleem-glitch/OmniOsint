"""Built-in reference data.

Idempotent: safe to run after every migration. Built-in roles and permissions
are brought in line with the code; anything an administrator created is left
alone.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.auth.permissions import BUILTIN_ROLES, PERMISSION_DESCRIPTIONS
from omniosint.auth.permissions import Permission as PermissionCode
from omniosint.core.timeutil import isoformat, utcnow
from omniosint.database.models import Permission, Role, SystemSetting, role_permissions

INSTANCE_KEY = "instance"


@dataclass(frozen=True, slots=True)
class SeedReport:
    permissions: int
    roles: int
    instance_id: str
    sources: int = 0
    providers: int = 0


async def seed_builtin(session: AsyncSession) -> SeedReport:
    """Synchronise built-in permissions, roles and the instance record."""
    # Permissions --------------------------------------------------------------
    codes = [code.value for code in PermissionCode]
    for code in PermissionCode:
        await session.execute(
            insert(Permission)
            .values(id=uuid.uuid4(), code=code.value, description=PERMISSION_DESCRIPTIONS[code])
            .on_conflict_do_update(
                index_elements=[Permission.code],
                set_={"description": PERMISSION_DESCRIPTIONS[code]},
            )
        )
    # A permission removed from the code no longer protects anything.
    await session.execute(delete(Permission).where(Permission.code.not_in(codes)))

    permission_rows = (await session.execute(select(Permission.code, Permission.id))).all()
    permission_ids: dict[str, uuid.UUID] = {row.code: row.id for row in permission_rows}

    # Roles --------------------------------------------------------------------
    for definition in BUILTIN_ROLES:
        await session.execute(
            insert(Role)
            .values(
                id=uuid.uuid4(),
                name=definition.name,
                description=definition.description,
                is_system=True,
            )
            .on_conflict_do_update(
                index_elements=[Role.name],
                set_={"description": definition.description, "is_system": True},
            )
        )
        role_id = (
            await session.execute(select(Role.id).where(Role.name == definition.name))
        ).scalar_one()
        await session.execute(delete(role_permissions).where(role_permissions.c.role_id == role_id))
        if definition.permissions:
            await session.execute(
                insert(role_permissions),
                [
                    {"role_id": role_id, "permission_id": permission_ids[permission.value]}
                    for permission in sorted(definition.permissions)
                ],
            )

    # Instance record ----------------------------------------------------------
    instance = await session.get(SystemSetting, INSTANCE_KEY)
    if instance is None:
        instance = SystemSetting(
            key=INSTANCE_KEY,
            value={"id": str(uuid.uuid4()), "created_at": isoformat(utcnow())},
        )
        session.add(instance)
    await session.flush()

    # Source registry and providers --------------------------------------------
    # Imported here: the provider registry imports the models of this package.
    from omniosint.evidence.sources import sync_sources
    from omniosint.providers.catalog import load_catalogue
    from omniosint.providers.registry import BUILTIN_ADAPTERS

    sync = await sync_sources(session, load_catalogue(), [cls() for cls in BUILTIN_ADAPTERS])
    await session.flush()

    return SeedReport(
        permissions=len(codes),
        roles=len(BUILTIN_ROLES),
        instance_id=str(instance.value["id"]),
        sources=sync.sources,
        providers=sync.providers,
    )
