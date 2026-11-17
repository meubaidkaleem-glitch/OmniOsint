"""Health, version, feature registry and detailed system status."""

from __future__ import annotations

import os
import platform
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from omniosint import __version__
from omniosint.api.deps import (
    PUBLIC_DOC,
    ActivePrincipalDep,
    ContextDep,
    SessionDep,
    permission_doc,
    require,
)
from omniosint.api.schemas.common import ERROR_RESPONSES
from omniosint.api.schemas.system import (
    ComponentDetail,
    ComponentSummary,
    FeatureCounts,
    FeatureList,
    FeatureOut,
    LiveResponse,
    PhaseOut,
    ReadyResponse,
    RuntimeInfo,
    ServerInfo,
    SystemInfo,
    SystemStatus,
)
from omniosint.auth.permissions import Permission
from omniosint.auth.service import Principal
from omniosint.core.config import is_loopback_host
from omniosint.core.features import CURRENT_PHASE, FEATURES, PHASES, feature_counts
from omniosint.core.logging import get_logger
from omniosint.core.timeutil import utcnow
from omniosint.system.health import collect_health

router = APIRouter(prefix="/system", tags=["system"])
log = get_logger(__name__)

CanReadSystem = Annotated[Principal, Depends(require(Permission.SYSTEM_READ))]


@router.get(
    "/health/live",
    response_model=LiveResponse,
    summary="Liveness: the API process is running",
    openapi_extra=PUBLIC_DOC,
)
async def live() -> LiveResponse:
    return LiveResponse()


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    summary="Readiness: the API can serve requests",
    description=(
        "Returns 200 when the database is reachable and its schema is current "
        "(status `ok` or `degraded`), otherwise 503. Component names and states only; "
        "details are in `/system/status`."
    ),
    openapi_extra=PUBLIC_DOC,
    responses={503: {"model": ReadyResponse, "description": "A required component is down."}},
)
async def ready(response: Response, context: ContextDep) -> ReadyResponse:
    report = await collect_health(context.db, context.settings, context.paths)
    if not report.ready:
        response.status_code = 503
    return ReadyResponse(
        status=report.status.value,
        checked_at=report.checked_at,
        components=[
            ComponentSummary(
                name=item.name, label=item.label, status=item.status.value, required=item.required
            )
            for item in report.components
        ],
    )


@router.get(
    "/info",
    response_model=SystemInfo,
    summary="Service name, version and whether first-run setup is pending",
    openapi_extra=PUBLIC_DOC,
)
async def info(context: ContextDep, session: SessionDep) -> SystemInfo:
    setup_required: bool | None
    try:
        setup_required = await context.auth.setup_required(session)
    except Exception as exc:
        log.warning("system.info.database_unavailable", error=type(exc).__name__)
        setup_required = None
    return SystemInfo(version=__version__, setup_required=setup_required)


@router.get(
    "/features",
    response_model=FeatureList,
    summary="What is available and what is planned",
    description=(
        "The feature registry. The interface uses it to show unbuilt sections as "
        "planned instead of presenting controls that do nothing."
    ),
    responses={401: ERROR_RESPONSES[401]},
)
async def features(_principal: ActivePrincipalDep) -> FeatureList:
    return FeatureList(
        current_phase=CURRENT_PHASE,
        phases=[PhaseOut(number=number, title=title) for number, title in PHASES.items()],
        counts=FeatureCounts(**feature_counts()),
        features=[FeatureOut.from_feature(feature) for feature in FEATURES],
    )


@router.get(
    "/status",
    response_model=SystemStatus,
    summary="Detailed system and service status",
    openapi_extra=permission_doc(Permission.SYSTEM_READ),
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def system_status(_principal: CanReadSystem, context: ContextDep) -> SystemStatus:
    report = await collect_health(context.db, context.settings, context.paths)
    server = context.settings.server
    now = utcnow()
    return SystemStatus(
        status=report.status.value,
        checked_at=report.checked_at,
        version=__version__,
        environment=context.settings.environment,
        started_at=context.started_at,
        uptime_seconds=int((now - context.started_at).total_seconds()),
        runtime=RuntimeInfo(
            python=platform.python_version(),
            platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
            pid=os.getpid(),
        ),
        server=ServerInfo(
            host=server.host, port=server.port, local_only=is_loopback_host(server.host)
        ),
        data_directory=str(context.paths.home),
        components=[ComponentDetail.from_health(item) for item in report.components],
    )
