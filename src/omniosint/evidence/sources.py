"""The source registry and the providers table, kept in step with the code.

Every catalogue entry and every adapter is a source evidence can be attributed
to. Lineage (``upstream``) is recorded so that sources repeating one dataset
are not treated as independent corroboration. Synchronised after every
migration, like the built-in roles.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.database.models import EvidenceSource, Provider
from omniosint.providers.base import IntelligenceProvider
from omniosint.providers.catalog import ProviderCatalogue, ProviderEntry

ANALYST_INPUT = "omniosint.input"

_KIND_BY_ACCESS = {
    "free": "api",
    "free_key": "api",
    "freemium": "api",
    "paid": "api",
    "self_hosted": "api",
    "local_library": "local",
    "local_tool": "tool",
    "none": "dataset",
}


@dataclass(frozen=True, slots=True)
class SourceRow:
    id: str
    name: str
    kind: str
    provider_id: str | None
    homepage_url: str | None
    upstream: tuple[str, ...]
    terms_note: str | None
    simulated: bool


def _from_entry(entry: ProviderEntry) -> SourceRow:
    return SourceRow(
        id=entry.id,
        name=entry.name,
        kind=_KIND_BY_ACCESS[entry.access],
        provider_id=entry.id,
        homepage_url=entry.docs_url or None,
        upstream=entry.upstream,
        terms_note=entry.notes or None,
        simulated=False,
    )


def _from_adapter(adapter: IntelligenceProvider) -> SourceRow:
    metadata = adapter.metadata
    return SourceRow(
        id=metadata.id,
        name=metadata.name,
        kind=metadata.source_kind,
        provider_id=metadata.id,
        homepage_url=metadata.homepage_url,
        upstream=metadata.upstream_sources,
        terms_note=metadata.terms_note,
        simulated=metadata.simulated,
    )


BUILTIN_SOURCES = (
    SourceRow(
        id=ANALYST_INPUT,
        name="Analyst input",
        kind="analyst",
        provider_id=None,
        homepage_url=None,
        upstream=(),
        terms_note="Indicators entered by users. An input is not an observation about the world.",
        simulated=False,
    ),
)


@dataclass(frozen=True, slots=True)
class SourceSyncReport:
    sources: int
    providers: int


async def sync_sources(
    session: AsyncSession,
    catalogue: ProviderCatalogue,
    adapters: Iterable[IntelligenceProvider],
) -> SourceSyncReport:
    adapter_list = list(adapters)
    rows: dict[str, SourceRow] = {row.id: row for row in BUILTIN_SOURCES}
    rows.update({entry.id: _from_entry(entry) for entry in catalogue.providers})
    # An adapter's own metadata is more specific than its catalogue entry.
    rows.update({adapter.metadata.id: _from_adapter(adapter) for adapter in adapter_list})
    for row in rows.values():
        values = {
            "name": row.name,
            "kind": row.kind,
            "provider_id": row.provider_id,
            "homepage_url": row.homepage_url,
            "upstream_source_ids": list(row.upstream),
            "terms_note": row.terms_note,
            "is_simulated": row.simulated,
        }
        await session.execute(
            insert(EvidenceSource)
            .values(id=row.id, **values)
            .on_conflict_do_update(index_elements=[EvidenceSource.id], set_=values)
        )
    for adapter in adapter_list:
        metadata = adapter.metadata
        described = {
            "name": metadata.name,
            "category": metadata.category,
            "adapter_version": metadata.version,
        }
        # enabled and priority belong to the administrator and are left alone.
        await session.execute(
            insert(Provider)
            .values(id=metadata.id, **described)
            .on_conflict_do_update(index_elements=[Provider.id], set_=described)
        )
    return SourceSyncReport(sources=len(rows), providers=len(adapter_list))
