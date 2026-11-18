"""Collection: plan previews, requests and jobs."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status

from omniosint.api.deps import (
    ContextDep,
    IntelDep,
    RequestInfoDep,
    SessionDep,
    permission_doc,
    require,
)
from omniosint.api.schemas.common import ERROR_RESPONSES
from omniosint.api.schemas.intel import (
    JobDetailOut,
    JobEventOut,
    JobList,
    JobOut,
    PlanOut,
    PlanRequest,
    RequestDetailOut,
    RequestList,
    RequestOut,
    ResultOut,
)
from omniosint.auth.permissions import Permission
from omniosint.auth.service import Principal
from omniosint.collection import service as collection
from omniosint.collection.inputs import resolve
from omniosint.collection.planner import PlanOptions
from omniosint.core.pagination import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(prefix="/collection", tags=["collection"])

CanRead = Annotated[Principal, Depends(require(Permission.COLLECTION_READ))]
CanRun = Annotated[Principal, Depends(require(Permission.COLLECTION_RUN))]
CanApprove = Annotated[Principal, Depends(require(Permission.COLLECTION_APPROVE))]
LimitQuery = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
CursorQuery = Annotated[str | None, Query(max_length=512)]

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: ERROR_RESPONSES[401],
    403: ERROR_RESPONSES[403],
    503: ERROR_RESPONSES[503],
}
_CHANGE: dict[int | str, dict[str, Any]] = {
    **_ERRORS,
    404: ERROR_RESPONSES[404],
    409: ERROR_RESPONSES[409],
}

JobStatus = Literal[
    "queued", "awaiting_approval", "running", "succeeded", "failed", "cancelled", "skipped"
]


def _options(body: PlanRequest) -> PlanOptions:
    return PlanOptions(
        mode=body.mode,
        strategy=body.strategy,
        providers=tuple(body.providers) if body.providers is not None else None,
        scope_id=body.scope_id,
        force_refresh=body.force_refresh,
        provider_options=dict(body.provider_options),
    )


@router.post(
    "/plan",
    response_model=PlanOut,
    summary="Preview a collection plan",
    description=(
        "What would run for the input, and why each provider would or would not be "
        "used. Nothing is collected. An ambiguous input needs `type`."
    ),
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses={**_ERRORS, 422: ERROR_RESPONSES[422]},
)
async def plan(
    body: PlanRequest,
    _principal: CanRead,
    context: ContextDep,
    intel: IntelDep,
    session: SessionDep,
) -> PlanOut:
    indicator, _result = resolve(
        body.input, body.type, default_region=context.settings.collection.default_phone_region
    )
    preview = await collection.preview(session, intel, indicator, _options(body))
    return PlanOut.model_validate(preview.as_dict())


@router.post(
    "/requests",
    response_model=RequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a collection request",
    description=(
        "Computes the plan again and queues every step that can run. Active operations "
        "and paid calls above the threshold wait for approval."
    ),
    openapi_extra=permission_doc(Permission.COLLECTION_RUN),
    responses={**_ERRORS, 422: ERROR_RESPONSES[422]},
)
async def submit(
    body: PlanRequest,
    principal: CanRun,
    context: ContextDep,
    intel: IntelDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> RequestOut:
    indicator, result = resolve(
        body.input, body.type, default_region=context.settings.collection.default_phone_region
    )
    created = await collection.submit(
        session,
        intel,
        indicator=indicator,
        input_text=result.input,
        options=_options(body),
        actor=principal.actor,
        request=info,
    )
    return RequestOut.model_validate(created)


@router.get(
    "/requests",
    response_model=RequestList,
    summary="List collection requests",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses=_ERRORS,
)
async def list_requests(
    _principal: CanRead,
    session: SessionDep,
    limit: LimitQuery = DEFAULT_LIMIT,
    cursor: CursorQuery = None,
) -> RequestList:
    page = await collection.list_requests(session, limit=limit, cursor=cursor)
    return RequestList(
        items=[RequestOut.model_validate(item) for item in page.items], next_cursor=page.next_cursor
    )


@router.get(
    "/requests/{request_id}",
    response_model=RequestDetailOut,
    summary="Get a collection request, its plan and its jobs",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses={**_ERRORS, 404: ERROR_RESPONSES[404]},
)
async def get_request(
    request_id: uuid.UUID, _principal: CanRead, session: SessionDep
) -> RequestDetailOut:
    detail = await collection.get_request(session, request_id)
    return RequestDetailOut(
        request=RequestOut.model_validate(detail.request),
        plan=detail.request.plan,
        jobs=[JobOut.model_validate(job) for job in detail.jobs],
    )


@router.post(
    "/requests/{request_id}/cancel",
    response_model=RequestOut,
    summary="Cancel every unfinished job of a request",
    openapi_extra=permission_doc(Permission.COLLECTION_RUN),
    responses=_CHANGE,
)
async def cancel_request(
    request_id: uuid.UUID, principal: CanRun, session: SessionDep, info: RequestInfoDep
) -> RequestOut:
    updated = await collection.cancel_request(
        session, request_id, actor=principal.actor, request=info
    )
    return RequestOut.model_validate(updated)


@router.get(
    "/jobs",
    response_model=JobList,
    summary="List jobs (the job history)",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses=_ERRORS,
)
async def list_jobs(
    _principal: CanRead,
    session: SessionDep,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    provider: Annotated[str | None, Query(max_length=64)] = None,
    limit: LimitQuery = DEFAULT_LIMIT,
    cursor: CursorQuery = None,
) -> JobList:
    page = await collection.list_jobs(
        session, status=status_filter, provider_id=provider, limit=limit, cursor=cursor
    )
    return JobList(
        items=[JobOut.model_validate(job) for job in page.items], next_cursor=page.next_cursor
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobDetailOut,
    summary="Get a job with its history and results",
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses={**_ERRORS, 404: ERROR_RESPONSES[404]},
)
async def get_job(job_id: uuid.UUID, _principal: CanRead, session: SessionDep) -> JobDetailOut:
    detail = await collection.get_job(session, job_id)
    return JobDetailOut(
        job=JobOut.model_validate(detail.job),
        events=[JobEventOut.model_validate(event) for event in detail.events],
        results=[ResultOut.model_validate(result) for result in detail.results],
        evidence_count=detail.evidence_count,
    )


@router.post(
    "/jobs/{job_id}/approve",
    response_model=JobOut,
    summary="Approve a job that waits for approval",
    description="Active operations are checked against their scope again before approval.",
    openapi_extra=permission_doc(Permission.COLLECTION_APPROVE),
    responses=_CHANGE,
)
async def approve_job(
    job_id: uuid.UUID, principal: CanApprove, session: SessionDep, info: RequestInfoDep
) -> JobOut:
    job = await collection.approve_job(session, job_id, actor=principal.actor, request=info)
    return JobOut.model_validate(job)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobOut,
    summary="Cancel a job",
    openapi_extra=permission_doc(Permission.COLLECTION_RUN),
    responses=_CHANGE,
)
async def cancel_job(
    job_id: uuid.UUID, principal: CanRun, session: SessionDep, info: RequestInfoDep
) -> JobOut:
    job = await collection.cancel_job(session, job_id, actor=principal.actor, request=info)
    return JobOut.model_validate(job)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobOut,
    summary="Retry a failed or cancelled job",
    description="An active operation goes back to waiting for approval.",
    openapi_extra=permission_doc(Permission.COLLECTION_RUN),
    responses=_CHANGE,
)
async def retry_job(
    job_id: uuid.UUID, principal: CanRun, session: SessionDep, info: RequestInfoDep
) -> JobOut:
    job = await collection.retry_job(session, job_id, actor=principal.actor, request=info)
    return JobOut.model_validate(job)
