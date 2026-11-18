"""Providers: the catalogue, the installed adapters and their health.

The catalogue lists everything planned. Adapters are the code that can collect;
in Phase 2 the only one is the simulated provider, used for testing. Real
integrations start in Phase 4. Credential management arrives in Phase 5.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from omniosint.api.deps import (
    ActivePrincipalDep,
    IntelDep,
    RequestInfoDep,
    SessionDep,
    permission_doc,
    require,
)
from omniosint.api.schemas.common import ERROR_RESPONSES, ErrorResponse
from omniosint.api.schemas.intel import AdapterList, AdapterOut, CapabilityOut, HealthOut
from omniosint.api.schemas.system import CategoryOut, ProviderCounts, ProviderList, ProviderOut
from omniosint.audit.service import record
from omniosint.auth.permissions import Permission
from omniosint.auth.service import Principal
from omniosint.core.errors import NotFound
from omniosint.core.timeutil import utcnow
from omniosint.database.models import Provider, ProviderUsage
from omniosint.providers.catalog import CATEGORY_LABELS, load_catalogue

router = APIRouter(prefix="/providers", tags=["providers"])

CanReadCollection = Annotated[Principal, Depends(require(Permission.COLLECTION_READ))]
CanRunCollection = Annotated[Principal, Depends(require(Permission.COLLECTION_RUN))]


@router.get(
    "",
    response_model=ProviderList,
    summary="List the provider catalogue",
    description=(
        "The inventory of data sources and tools the platform is designed to "
        "integrate, each with its real status. `counts` and `categories` describe the "
        "whole catalogue, not only the filtered items."
    ),
    responses={401: ERROR_RESPONSES[401]},
)
async def list_providers(
    _principal: ActivePrincipalDep,
    category: Annotated[str | None, Query(max_length=48)] = None,
    status: Annotated[Literal["planned", "available", "excluded"] | None, Query()] = None,
    q: Annotated[
        str | None, Query(max_length=96, description="Matches name, identifier or notes.")
    ] = None,
) -> ProviderList:
    catalogue = load_catalogue()
    needle = q.strip().lower() if q else ""
    items = [
        provider
        for provider in catalogue.providers
        if (category is None or provider.category == category)
        and (status is None or provider.status == status)
        and (
            not needle
            or needle in provider.name.lower()
            or needle in provider.id
            or needle in provider.notes.lower()
        )
    ]
    per_category: dict[str, int] = {}
    for provider in catalogue.providers:
        per_category[provider.category] = per_category.get(provider.category, 0) + 1
    return ProviderList(
        items=[ProviderOut.from_entry(provider) for provider in items],
        counts=ProviderCounts(total=len(catalogue.providers), **catalogue.status_counts()),
        categories=[
            CategoryOut(key=key, label=label, count=per_category[key])
            for key, label in CATEGORY_LABELS.items()
            if key in per_category
        ],
    )


@router.get(
    "/adapters",
    response_model=AdapterList,
    summary="List installed adapters and their state",
    description=(
        "Adapters are the code that can collect. Each has its real status, circuit "
        "breaker state, capabilities and today's usage."
    ),
    openapi_extra=permission_doc(Permission.COLLECTION_READ),
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403], 503: ERROR_RESPONSES[503]},
)
async def list_adapters(
    _principal: CanReadCollection, intel: IntelDep, session: SessionDep
) -> AdapterList:
    today = utcnow().date()
    usage_rows = (
        await session.execute(
            select(
                ProviderUsage.provider_id,
                func.sum(ProviderUsage.requests),
                func.sum(ProviderUsage.failures),
                func.sum(ProviderUsage.cache_hits),
                func.sum(ProviderUsage.credits),
            )
            .where(ProviderUsage.day == today)
            .group_by(ProviderUsage.provider_id)
        )
    ).all()
    usage = {
        row[0]: {
            "day": today.isoformat(),
            "requests": int(row[1] or 0),
            "failures": int(row[2] or 0),
            "cache_hits": int(row[3] or 0),
            "credits": float(row[4] or 0),
        }
        for row in usage_rows
    }
    items = []
    for state in intel.registry.states():
        metadata = state.metadata
        if metadata is None:
            continue
        items.append(
            AdapterOut(
                id=state.id,
                name=state.name,
                category=metadata.category,
                version=metadata.version,
                description=metadata.description,
                status=state.status,
                message=state.message,
                simulated=metadata.simulated,
                verified_live=metadata.verified_live,
                requires_credentials=metadata.requires_credentials,
                missing_credentials=list(state.missing_credentials),
                circuit=intel.manager.circuit.state(state.id),
                rate_limit={
                    "requests": metadata.rate_limit.requests,
                    "per_seconds": metadata.rate_limit.per_seconds,
                    "burst": metadata.rate_limit.capacity,
                },
                capabilities=[
                    CapabilityOut(
                        id=capability.id,
                        name=capability.name,
                        description=capability.description,
                        accepts=sorted(capability.accepts),
                        operation=capability.operation.value,
                        active=capability.active,
                        cost=capability.cost.as_dict(),
                        cache_ttl_seconds=capability.cache_ttl_seconds,
                        timeout_seconds=capability.timeout_seconds,
                        max_pages=capability.max_pages,
                    )
                    for capability in metadata.capabilities
                ],
                usage_today=usage.get(
                    state.id,
                    {
                        "day": today.isoformat(),
                        "requests": 0,
                        "failures": 0,
                        "cache_hits": 0,
                        "credits": 0.0,
                    },
                ),
            )
        )
    return AdapterList(items=items)


@router.post(
    "/{provider_id}/health",
    response_model=HealthOut,
    summary="Run a provider's health check",
    description="Only adapters can be checked; catalogue entries report their planned status.",
    openapi_extra=permission_doc(Permission.COLLECTION_RUN),
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403], 503: ERROR_RESPONSES[503]},
)
async def health_check(
    provider_id: str,
    principal: CanRunCollection,
    intel: IntelDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> HealthOut:
    result = await intel.manager.health(provider_id)
    row = await session.get(Provider, provider_id)
    if row is not None:
        row.last_health = result.model_dump(mode="json")
        row.last_health_at = utcnow()
    record(
        session,
        action="provider.health_checked",
        actor=principal.actor,
        target_type="provider",
        target_id=provider_id,
        request=info,
        details={"status": result.status},
    )
    await session.commit()
    return HealthOut(
        status=result.status,
        detail=result.detail,
        latency_ms=result.latency_ms,
        quota=result.quota.model_dump(mode="json") if result.quota else None,
    )


@router.get(
    "/{provider_id}",
    response_model=ProviderOut,
    summary="Get one catalogue entry",
    responses={401: ERROR_RESPONSES[401], 404: {"model": ErrorResponse}},
)
async def get_provider(provider_id: str, _principal: ActivePrincipalDep) -> ProviderOut:
    entry = load_catalogue().get(provider_id)
    if entry is None:
        raise NotFound("No such provider in the catalogue.")
    return ProviderOut.from_entry(entry)
