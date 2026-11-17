"""Provider catalogue (read-only).

No provider integration exists yet, so there is nothing to configure, test or
query here. Health, quota, credentials and usage endpoints arrive with the
provider framework (Phase 2) and the first integrations (Phase 5).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from omniosint.api.deps import ActivePrincipalDep
from omniosint.api.schemas.common import ERROR_RESPONSES, ErrorResponse
from omniosint.api.schemas.system import CategoryOut, ProviderCounts, ProviderList, ProviderOut
from omniosint.core.errors import NotFound
from omniosint.providers.catalog import CATEGORY_LABELS, load_catalogue

router = APIRouter(prefix="/providers", tags=["providers"])


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
