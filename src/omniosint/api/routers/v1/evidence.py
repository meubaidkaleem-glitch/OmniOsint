"""Evidence, entities and the source registry (read-only)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from omniosint.api.deps import IntelDep, RequestInfoDep, SessionDep, permission_doc, require
from omniosint.api.schemas.common import ERROR_RESPONSES
from omniosint.api.schemas.intel import (
    EntityList,
    EntityOut,
    EvidenceDetailOut,
    EvidenceList,
    EvidenceOut,
    IntegrityOut,
    RawOut,
    SourceList,
    SourceOut,
)
from omniosint.audit.service import record
from omniosint.auth.permissions import Permission
from omniosint.auth.service import Principal
from omniosint.core.errors import Conflict, NotFound, PermissionDenied
from omniosint.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from omniosint.database.models import CollectionResult, EvidenceSource, RawObject
from omniosint.evidence import entities as entity_registry
from omniosint.evidence import service as evidence_service
from omniosint.evidence.objectstore import ObjectStoreError
from omniosint.indicators.types import EntityType

router = APIRouter(tags=["evidence"])


class RawNotMaskable(Conflict):
    code = "raw_not_maskable"
    default_message = "This raw response cannot be shown masked."


CanRead = Annotated[Principal, Depends(require(Permission.EVIDENCE_READ))]
LimitQuery = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
CursorQuery = Annotated[str | None, Query(max_length=512)]
_ERRORS: dict[int | str, dict[str, Any]] = {401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]}
_ONE: dict[int | str, dict[str, Any]] = {**_ERRORS, 404: ERROR_RESPONSES[404]}


@router.get(
    "/evidence",
    response_model=EvidenceList,
    summary="List evidence",
    description="Newest first. Simulated evidence is included and flagged unless excluded.",
    openapi_extra=permission_doc(Permission.EVIDENCE_READ),
    responses=_ERRORS,
)
async def list_evidence(
    _principal: CanRead,
    session: SessionDep,
    entity_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    include_simulated: bool = True,
    limit: LimitQuery = DEFAULT_LIMIT,
    cursor: CursorQuery = None,
) -> EvidenceList:
    page = await evidence_service.list_evidence(
        session,
        entity_id=entity_id,
        job_id=job_id,
        include_simulated=include_simulated,
        limit=limit,
        cursor=cursor,
    )
    return EvidenceList(
        items=[EvidenceOut.model_validate(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceDetailOut,
    summary="Get evidence with its entity, source and integrity",
    openapi_extra=permission_doc(Permission.EVIDENCE_READ),
    responses=_ONE,
)
async def get_evidence(
    evidence_id: uuid.UUID, _principal: CanRead, session: SessionDep, intel: IntelDep
) -> EvidenceDetailOut:
    item = await evidence_service.get_evidence(session, evidence_id)
    integrity = await evidence_service.check_integrity(session, item, intel.store)
    entity = await entity_registry.get_entity(session, item.entity_id)
    source = await session.get(EvidenceSource, item.source_id)
    return EvidenceDetailOut(
        evidence=EvidenceOut.model_validate(item),
        integrity=IntegrityOut(
            content_hash_valid=integrity.content_hash_valid,
            raw_available=integrity.raw_available,
            raw_hash_valid=integrity.raw_hash_valid,
            detail=integrity.detail,
        ),
        entity=EntityOut.model_validate(entity),
        source=SourceOut.model_validate(source) if source else None,
    )


@router.get(
    "/evidence/{evidence_id}/raw",
    response_model=RawOut,
    summary="The raw response behind evidence",
    description=(
        "Credential-like fields are masked. `unmasked=true` needs the "
        "`evidence:read_raw` permission and is recorded in the audit trail. A response "
        "that is not JSON cannot be masked, so it is shown only unmasked (409 "
        "`raw_not_maskable` otherwise)."
    ),
    openapi_extra=permission_doc(Permission.EVIDENCE_READ),
    responses={**_ONE, 409: ERROR_RESPONSES[409]},
)
async def raw_response(
    evidence_id: uuid.UUID,
    principal: CanRead,
    session: SessionDep,
    intel: IntelDep,
    info: RequestInfoDep,
    unmasked: bool = False,
) -> RawOut:
    item = await evidence_service.get_evidence(session, evidence_id)
    if unmasked and not principal.has(Permission.EVIDENCE_READ_RAW.value):
        # Audited like every other permission denial.
        record(
            session,
            action="authz.denied",
            actor=principal.actor,
            outcome="denied",
            target_type="evidence",
            target_id=item.id,
            request=info,
            details={"permission": Permission.EVIDENCE_READ_RAW.value, "unmasked": True},
        )
        await session.commit()
        raise PermissionDenied(
            "Viewing raw responses unmasked needs the evidence:read_raw permission."
        )
    if item.raw_sha256 is None or await session.get(RawObject, item.raw_sha256) is None:
        raise NotFound("The raw response is no longer stored; its hash is kept with the evidence.")
    result = (
        await session.get(CollectionResult, item.collection_result_id)
        if item.collection_result_id
        else None
    )
    content_type = result.content_type if result else "application/octet-stream"
    try:
        content = intel.store.get(item.raw_sha256)
    except ObjectStoreError as error:
        raise NotFound(str(error)) from error
    view = (
        evidence_service.raw_view(content, content_type, redacted=False)
        if unmasked
        else evidence_service.masked_raw_view(content, content_type)
    )
    if view is None:
        raise RawNotMaskable(
            "This raw response is not JSON, so credential-like values in it cannot be "
            "masked. Viewing it unmasked needs the evidence:read_raw permission and is "
            "recorded in the audit trail."
        )
    if unmasked:
        record(
            session,
            action="evidence.raw_viewed",
            actor=principal.actor,
            target_type="evidence",
            target_id=item.id,
            request=info,
            details={"raw_sha256": item.raw_sha256, "unmasked": True},
        )
        await session.commit()
    return RawOut(
        sha256=item.raw_sha256,
        content_type=content_type,
        size=len(content),
        format=view["format"],
        body=view["body"],
        redacted=view["redacted"],
        simulated=item.is_simulated,
    )


@router.get(
    "/entities",
    response_model=EntityList,
    summary="List entities",
    openapi_extra=permission_doc(Permission.EVIDENCE_READ),
    responses=_ERRORS,
)
async def list_entities(
    _principal: CanRead,
    session: SessionDep,
    type: Annotated[EntityType | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=256)] = None,
    limit: LimitQuery = DEFAULT_LIMIT,
    cursor: CursorQuery = None,
) -> EntityList:
    page = await entity_registry.list_entities(
        session,
        entity_type=type.value if type else None,
        search=search,
        limit=limit,
        cursor=cursor,
    )
    return EntityList(
        items=[EntityOut.model_validate(item) for item in page.items], next_cursor=page.next_cursor
    )


@router.get(
    "/entities/{entity_id}",
    response_model=EntityOut,
    summary="Get an entity",
    openapi_extra=permission_doc(Permission.EVIDENCE_READ),
    responses=_ONE,
)
async def get_entity(entity_id: uuid.UUID, _principal: CanRead, session: SessionDep) -> EntityOut:
    return EntityOut.model_validate(await entity_registry.get_entity(session, entity_id))


@router.get(
    "/sources",
    response_model=SourceList,
    summary="The source registry",
    description="Every source evidence can be attributed to, with its lineage.",
    openapi_extra=permission_doc(Permission.EVIDENCE_READ),
    responses=_ERRORS,
)
async def list_sources(_principal: CanRead, session: SessionDep) -> SourceList:
    from sqlalchemy import select

    rows = (await session.execute(select(EvidenceSource).order_by(EvidenceSource.name))).scalars()
    return SourceList(items=[SourceOut.model_validate(row) for row in rows])
