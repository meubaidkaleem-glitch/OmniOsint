"""The entity registry: one canonical entity per normalised identifier.

Entities are global (ADR in ARCHITECTURE section 5): an IP address is one
entity however many investigations touch it. Values from providers are
normalised the same way as user input before they become entities.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.core.errors import NotFound, ValidationFailed
from omniosint.core.pagination import Page, clamp_limit, decode_cursor, encode_cursor
from omniosint.database.models import Entity
from omniosint.indicators.types import EntityType
from omniosint.indicators.web import normalize_hostname, split_url

MAX_KEY_LENGTH = 2048


def canonical_value(entity_type: EntityType, value: str) -> tuple[str, str]:
    """The registry key and display form of ``value``. Raises ``ValueError``."""
    text = value.strip()
    if not text or len(text) > MAX_KEY_LENGTH:
        raise ValueError("empty or oversized value")
    if entity_type is EntityType.IP_ADDRESS:
        address = ipaddress.ip_address(text)
        return address.compressed, address.compressed
    if entity_type is EntityType.NETWORK_PREFIX:
        network = ipaddress.ip_network(text, strict=False)
        return network.with_prefixlen, network.with_prefixlen
    if entity_type in (EntityType.DOMAIN, EntityType.SUBDOMAIN):
        normalized = normalize_hostname(text)
        if normalized is None:
            raise ValueError("not a host name")
        return normalized
    if entity_type is EntityType.EMAIL:
        local, _, domain = text.rpartition("@")
        host = normalize_hostname(domain) if local else None
        if host is None:
            raise ValueError("not an email address")
        return f"{local.lower()}@{host[0]}", text
    if entity_type is EntityType.URL:
        parsed = split_url(text)
        if parsed is None:
            raise ValueError("not a URL")
        return parsed.canonical, text
    if entity_type is EntityType.ASN:
        number = text.upper().removeprefix("ASN").removeprefix("AS")
        if not number.isdigit():
            raise ValueError("not an AS number")
        return f"AS{int(number)}", f"AS{int(number)}"
    if entity_type in (EntityType.FILE_HASH, EntityType.CERTIFICATE):
        return text.lower(), text.lower()
    if entity_type is EntityType.VULNERABILITY:
        return text.upper(), text.upper()
    if entity_type in (EntityType.USERNAME, EntityType.ORGANIZATION):
        return text.casefold(), text
    return text, text


async def upsert_entity(
    session: AsyncSession,
    entity_type: EntityType,
    key: str,
    display: str,
    *,
    observed_at: datetime | None,
    simulated: bool,
    attributes: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Create the entity or record a new observation of it. Returns its id.

    ``is_simulated`` stays true only while every observation is simulated:
    one real observation clears it for good.
    """
    values = insert(Entity).values(
        type=entity_type.value,
        canonical_key=key,
        display_name=display[:MAX_KEY_LENGTH],
        attributes=attributes or {},
        first_observed_at=observed_at,
        last_observed_at=observed_at,
        is_simulated=simulated,
    )
    excluded = values.excluded
    statement = values.on_conflict_do_update(
        constraint="uq_entities_type_canonical_key",
        set_={
            "first_observed_at": func.least(Entity.first_observed_at, excluded.first_observed_at),
            "last_observed_at": func.greatest(Entity.last_observed_at, excluded.last_observed_at),
            "is_simulated": Entity.is_simulated & excluded.is_simulated,
            "updated_at": func.now(),
        },
    ).returning(Entity.id)
    result = await session.execute(statement)
    entity_id: uuid.UUID = result.scalar_one()
    return entity_id


async def get_entity(session: AsyncSession, entity_id: uuid.UUID) -> Entity:
    entity = await session.get(Entity, entity_id)
    if entity is None or entity.deleted_at is not None:
        raise NotFound("The entity was not found.")
    return entity


async def find_entity(session: AsyncSession, entity_type: EntityType, key: str) -> Entity | None:
    result = await session.execute(
        select(Entity).where(
            Entity.type == entity_type.value,
            Entity.canonical_key == key,
            Entity.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_entities(
    session: AsyncSession,
    *,
    entity_type: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Entity]:
    """Newest first, keyset-paginated."""
    size = clamp_limit(limit)
    query = select(Entity).where(Entity.deleted_at.is_(None))
    if entity_type:
        query = query.where(Entity.type == entity_type)
    if search and search.strip():
        term = search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(func.lower(Entity.canonical_key).like(f"%{term}%", escape="\\"))
    if cursor:
        (position,) = decode_cursor(cursor, parts=1)
        query = query.where(Entity.id < _uuid(position))
    query = query.order_by(Entity.id.desc()).limit(size + 1)
    rows = list((await session.execute(query)).scalars())
    next_cursor = encode_cursor([str(rows[size - 1].id)]) if len(rows) > size else None
    return Page(items=rows[:size], next_cursor=next_cursor)


def _uuid(value: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as error:
        raise ValidationFailed("The cursor is not valid.") from error
