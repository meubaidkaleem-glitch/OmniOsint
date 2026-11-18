"""Universal search: classification, input types, history and saved searches."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from omniosint.api.deps import ContextDep, SessionDep, permission_doc, require
from omniosint.api.schemas.common import ERROR_RESPONSES
from omniosint.api.schemas.intel import (
    ClassificationOut,
    ClassifyRequest,
    HistoryEntryOut,
    HistoryList,
    InputTypeList,
    InputTypeOut,
    SavedSearchIn,
    SavedSearchList,
    SavedSearchOut,
)
from omniosint.auth.permissions import Permission
from omniosint.auth.service import Principal
from omniosint.collection import service as collection
from omniosint.indicators import TYPE_INFO, classify

router = APIRouter(prefix="/search", tags=["search"])

CanRead = Annotated[Principal, Depends(require(Permission.COLLECTION_READ))]
_ERRORS: dict[int | str, dict[str, Any]] = {401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]}


@router.post(
    "/classify",
    response_model=ClassificationOut,
    summary="Classify an input",
    description=(
        "Detects which of the 24 input types the input is, validates and normalises it. "
        "An ambiguous input returns every reading with `status` = `ambiguous`; nothing is "
        "guessed. Nothing is collected and no provider is contacted."
    ),
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses={**_ERRORS, 422: ERROR_RESPONSES[422]},
)
async def classify_input(
    body: ClassifyRequest, principal: CanRead, context: ContextDep, session: SessionDep
) -> ClassificationOut:
    result = classify(body.input, default_region=context.settings.collection.default_phone_region)
    if body.remember and result.input:
        await collection.record_search(session, principal.user_id, result)
    return ClassificationOut.model_validate(result.model_dump())


@router.get(
    "/types",
    response_model=InputTypeList,
    summary="List the supported input types",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses=_ERRORS,
)
async def input_types(_principal: CanRead) -> InputTypeList:
    return InputTypeList(
        items=[
            InputTypeOut(
                type=info.type,
                label=info.label,
                description=info.description,
                input_kind=info.input_kind,
                entity_type=info.entity_type,
                modules=list(info.modules),
                example=info.example,
            )
            for info in TYPE_INFO.values()
        ]
    )


@router.get(
    "/history",
    response_model=HistoryList,
    summary="Your search history",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses=_ERRORS,
)
async def history(
    principal: CanRead,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HistoryList:
    entries = await collection.list_history(session, principal.user_id, limit=limit)
    return HistoryList(items=[HistoryEntryOut.model_validate(entry) for entry in entries])


@router.delete(
    "/history",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear your search history",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses=_ERRORS,
)
async def clear_history(principal: CanRead, session: SessionDep) -> None:
    await collection.clear_history(session, principal.user_id)


@router.get(
    "/saved",
    response_model=SavedSearchList,
    summary="Your saved searches",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses=_ERRORS,
)
async def saved(principal: CanRead, session: SessionDep) -> SavedSearchList:
    items = await collection.list_saved(session, principal.user_id)
    return SavedSearchList(items=[SavedSearchOut.model_validate(item) for item in items])


@router.post(
    "/saved",
    response_model=SavedSearchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save a search",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses={**_ERRORS, 409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422]},
)
async def save(body: SavedSearchIn, principal: CanRead, session: SessionDep) -> SavedSearchOut:
    item = await collection.save_search(
        session,
        principal.user_id,
        name=body.name,
        query=body.query,
        indicator_type=body.indicator_type.value if body.indicator_type else None,
        options=body.options,
    )
    return SavedSearchOut.model_validate(item)


@router.delete(
    "/saved/{saved_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved search",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses={**_ERRORS, 404: ERROR_RESPONSES[404]},
)
async def delete_saved(saved_id: uuid.UUID, principal: CanRead, session: SessionDep) -> None:
    await collection.delete_saved(session, principal.user_id, saved_id)
