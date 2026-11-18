"""The evidence manager.

Every observation a provider returns becomes one immutable evidence row,
linked to its entity, its source, the job and result that produced it, and
the stored raw response. Its ``content_hash`` covers the normalised content
and the raw response's hash, so its integrity can be checked later.

The flag ``is_simulated`` is set from the provider's metadata by this module,
not by the adapter: simulated data can never be recorded as real.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.core.errors import NotFound, ValidationFailed
from omniosint.core.logging import redact
from omniosint.core.pagination import Page, clamp_limit, decode_cursor, encode_cursor
from omniosint.core.timeutil import isoformat
from omniosint.database.models import Evidence, RawObject
from omniosint.evidence.entities import canonical_value, upsert_entity
from omniosint.evidence.objectstore import ObjectMissing, ObjectStore, ObjectStoreError
from omniosint.providers.base import Observation

log = structlog.get_logger(__name__)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def content_hash(fields: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(fields)).hexdigest()


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a batch of observations came from."""

    source_id: str
    provider_id: str
    adapter_version: str
    capability: str
    job_id: uuid.UUID | None
    result_id: uuid.UUID | None
    raw_sha256: str | None
    collected_at: datetime
    simulated: bool


async def record_observation(
    session: AsyncSession, observation: Observation, provenance: Provenance
) -> Evidence:
    """Store ``observation`` as evidence, registering the entities it names."""
    subject_key, subject_display = canonical_value(
        observation.entity_type, observation.entity_value
    )
    observed_at = observation.observed_at or provenance.collected_at
    entity_id = await upsert_entity(
        session,
        observation.entity_type,
        subject_key,
        observation.entity_display or subject_display,
        observed_at=observed_at,
        simulated=provenance.simulated,
    )
    related: list[dict[str, Any]] = []
    for item in observation.related:
        entry: dict[str, Any] = {
            "type": item.type.value,
            "value": item.value,
            "relation": item.relation,
        }
        try:
            key, display = canonical_value(item.type, item.value)
        except ValueError:
            # Kept as the provider said it, but not turned into an entity.
            entry["rejected"] = "The value is not a valid identifier of this type."
        else:
            entry["entity_id"] = str(
                await upsert_entity(
                    session,
                    item.type,
                    key,
                    item.display or display,
                    observed_at=observed_at,
                    simulated=provenance.simulated,
                )
            )
            entry["value"] = key
        related.append(entry)
    normalized = {
        "kind": observation.kind,
        "entity": {"type": observation.entity_type.value, "value": subject_key},
        "attributes": observation.attributes,
        "related": related,
        "original": observation.original,
    }
    history = [
        {
            "step": "normalized",
            "by": f"{provenance.provider_id}@{provenance.adapter_version}",
            "capability": provenance.capability,
            "at": isoformat(provenance.collected_at),
        }
    ]
    digest = content_hash(
        {
            "normalized": normalized,
            "source_id": provenance.source_id,
            "source_url": observation.source_url,
            "provider_object_id": observation.provider_object_id,
            "observed_at": isoformat(observed_at),
            "raw_sha256": provenance.raw_sha256,
            "raw_pointer": observation.raw_pointer,
        }
    )
    evidence = Evidence(
        entity_id=entity_id,
        source_id=provenance.source_id,
        provider_id=provenance.provider_id,
        job_id=provenance.job_id,
        collection_result_id=provenance.result_id,
        observation_kind=observation.kind,
        source_url=observation.source_url,
        provider_object_id=observation.provider_object_id,
        collected_at=provenance.collected_at,
        observed_at=observed_at,
        normalized=normalized,
        raw_sha256=provenance.raw_sha256,
        raw_pointer=observation.raw_pointer,
        content_hash=digest,
        is_simulated=provenance.simulated,
        transformation_history=history,
    )
    session.add(evidence)
    await session.flush()
    return evidence


async def get_evidence(session: AsyncSession, evidence_id: uuid.UUID) -> Evidence:
    evidence = await session.get(Evidence, evidence_id)
    if evidence is None:
        raise NotFound("The evidence was not found.")
    return evidence


async def list_evidence(
    session: AsyncSession,
    *,
    entity_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    include_simulated: bool = True,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Evidence]:
    size = clamp_limit(limit)
    query = select(Evidence)
    if entity_id is not None:
        query = query.where(Evidence.entity_id == entity_id)
    if job_id is not None:
        query = query.where(Evidence.job_id == job_id)
    if not include_simulated:
        query = query.where(Evidence.is_simulated.is_(False))
    if cursor:
        (position,) = decode_cursor(cursor, parts=1)
        try:
            query = query.where(Evidence.id < uuid.UUID(str(position)))
        except ValueError as error:
            raise ValidationFailed("The cursor is not valid.") from error
    rows = list(
        (await session.execute(query.order_by(Evidence.id.desc()).limit(size + 1))).scalars()
    )
    next_cursor = encode_cursor([str(rows[size - 1].id)]) if len(rows) > size else None
    return Page(items=rows[:size], next_cursor=next_cursor)


@dataclass(frozen=True, slots=True)
class Integrity:
    """What can be said about an evidence row's integrity right now."""

    content_hash_valid: bool
    raw_available: bool
    raw_hash_valid: bool | None
    detail: str


def _recomputed_hash(evidence: Evidence) -> str:
    return content_hash(
        {
            "normalized": evidence.normalized,
            "source_id": evidence.source_id,
            "source_url": evidence.source_url,
            "provider_object_id": evidence.provider_object_id,
            "observed_at": isoformat(evidence.observed_at) if evidence.observed_at else None,
            "raw_sha256": evidence.raw_sha256,
            "raw_pointer": evidence.raw_pointer,
        }
    )


async def check_integrity(
    session: AsyncSession, evidence: Evidence, store: ObjectStore | None
) -> Integrity:
    content_ok = _recomputed_hash(evidence) == evidence.content_hash
    if evidence.raw_sha256 is None:
        return Integrity(content_ok, False, None, "No raw response is attached to this evidence.")
    if await session.get(RawObject, evidence.raw_sha256) is None or store is None:
        return Integrity(
            content_ok,
            False,
            None,
            "The raw response was removed after its retention period; its hash is still recorded.",
        )
    try:
        store.get(evidence.raw_sha256)  # verifies the content against its hash
    except ObjectMissing:
        return Integrity(
            content_ok, False, None, "The raw response is missing from the object store."
        )
    except ObjectStoreError as error:
        return Integrity(content_ok, True, False, str(error))
    detail = "Content and raw response match their recorded hashes."
    if not content_ok:
        detail = "The evidence content does not match its recorded hash."
    return Integrity(content_ok, True, True, detail)


def raw_view(content: bytes, content_type: str, *, redacted: bool) -> dict[str, Any]:
    """A raw response prepared for display. Credentials-like fields are masked
    unless ``redacted`` is false; the stored bytes are never changed."""
    if "json" in content_type:
        try:
            document = json.loads(content)
        except ValueError:
            pass
        else:
            return {
                "format": "json",
                "body": redact(document) if redacted else document,
                "redacted": redacted,
            }
    text = content.decode("utf-8", errors="replace")
    return {"format": "text", "body": text, "redacted": False}
