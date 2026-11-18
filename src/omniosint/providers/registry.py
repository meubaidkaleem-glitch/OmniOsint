"""Which providers exist, and the real status of each.

Adapters are the code that can collect. The catalogue (``config/providers.yaml``)
lists everything planned. The registry combines them with the installation's
settings, credentials and the ``providers`` table, so every provider has one
honest status:

* ``available``: an adapter exists, is enabled and has what it needs;
* ``not_configured``: an adapter exists but its credentials are missing;
* ``disabled``: switched off by an administrator, or (for the simulated
  provider) not enabled in the settings;
* ``planned``: listed in the catalogue, no adapter yet;
* ``excluded``: will not be integrated (the catalogue says why).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from omniosint.core.errors import NOT_CONFIGURED_MESSAGE, PLANNED_MESSAGE
from omniosint.indicators.types import IndicatorType
from omniosint.providers.base import Capability, IntelligenceProvider, ProviderMetadata
from omniosint.providers.catalog import ProviderCatalogue, ProviderEntry
from omniosint.providers.simulated import SimulatedProvider

BUILTIN_ADAPTERS: tuple[type[IntelligenceProvider], ...] = (SimulatedProvider,)

STATUS_MESSAGES = {
    "available": "Available.",
    "not_configured": NOT_CONFIGURED_MESSAGE,
    "disabled": "Disabled in this installation.",
    "simulated_disabled": (
        "Disabled. Set collection.enable_simulated_provider to use it for testing."
    ),
    "planned": PLANNED_MESSAGE,
    "excluded": "Excluded — see notes.",
}


@dataclass(frozen=True, slots=True)
class ProviderState:
    id: str
    name: str
    status: str
    message: str
    adapter: IntelligenceProvider | None
    entry: ProviderEntry | None
    simulated: bool = False
    missing_credentials: tuple[str, ...] = ()

    @property
    def metadata(self) -> ProviderMetadata | None:
        return self.adapter.metadata if self.adapter else None

    @property
    def runnable(self) -> bool:
        return self.status == "available" and self.adapter is not None


@dataclass(frozen=True, slots=True)
class CapabilityOption:
    provider: ProviderState
    capability: Capability


class ProviderRegistry:
    def __init__(
        self,
        catalogue: ProviderCatalogue,
        *,
        adapters: Iterable[IntelligenceProvider] | None = None,
        simulated_enabled: bool = False,
        has_secret: Callable[[str], bool] = lambda _name: False,
        disabled_ids: Iterable[str] = (),
        priorities: dict[str, int] | None = None,
    ) -> None:
        self._catalogue = catalogue
        self._adapters = {
            adapter.metadata.id: adapter
            for adapter in (
                adapters if adapters is not None else (cls() for cls in BUILTIN_ADAPTERS)
            )
        }
        self._simulated_enabled = simulated_enabled
        self._has_secret = has_secret
        self._disabled = frozenset(disabled_ids)
        self._priorities = priorities or {}

    # ------------------------------------------------------------------ queries
    def adapter(self, provider_id: str) -> IntelligenceProvider | None:
        return self._adapters.get(provider_id)

    def adapters(self) -> list[IntelligenceProvider]:
        return list(self._adapters.values())

    def state(self, provider_id: str) -> ProviderState | None:
        adapter = self._adapters.get(provider_id)
        entry = next((item for item in self._catalogue.providers if item.id == provider_id), None)
        if adapter is not None:
            return self._adapter_state(adapter, entry)
        if entry is not None:
            return self._entry_state(entry)
        return None

    def states(self) -> list[ProviderState]:
        result = [
            self._adapter_state(adapter, self._entry(adapter.metadata.id))
            for adapter in self._adapters.values()
        ]
        result += [
            self._entry_state(entry)
            for entry in self._catalogue.providers
            if entry.id not in self._adapters
        ]
        return result

    def options_for(self, indicator_type: IndicatorType) -> list[CapabilityOption]:
        """Every adapter capability that accepts ``indicator_type``, runnable or not."""
        options = [
            CapabilityOption(
                self._adapter_state(adapter, self._entry(adapter.metadata.id)), capability
            )
            for adapter in self._adapters.values()
            for capability in adapter.metadata.capabilities
            if indicator_type in capability.accepts
        ]
        return sorted(
            options,
            key=lambda option: (self._priorities.get(option.provider.id, 100), option.provider.id),
        )

    def planned_for(self, modules: Iterable[str]) -> list[ProviderState]:
        """Catalogue entries without an adapter that serve any of ``modules``."""
        wanted = set(modules)
        return [
            self._entry_state(entry)
            for entry in self._catalogue.providers
            if entry.id not in self._adapters and wanted & set(entry.modules)
        ]

    # ------------------------------------------------------------------ internals
    def _entry(self, provider_id: str) -> ProviderEntry | None:
        return next((item for item in self._catalogue.providers if item.id == provider_id), None)

    def _adapter_state(
        self, adapter: IntelligenceProvider, entry: ProviderEntry | None
    ) -> ProviderState:
        metadata = adapter.metadata
        missing = tuple(name for name in metadata.credential_names if not self._has_secret(name))
        if metadata.simulated and not self._simulated_enabled:
            status, message = "disabled", STATUS_MESSAGES["simulated_disabled"]
        elif metadata.id in self._disabled:
            status, message = "disabled", STATUS_MESSAGES["disabled"]
        elif missing:
            status, message = "not_configured", STATUS_MESSAGES["not_configured"]
        else:
            status, message = "available", STATUS_MESSAGES["available"]
        return ProviderState(
            id=metadata.id,
            name=metadata.name,
            status=status,
            message=message,
            adapter=adapter,
            entry=entry,
            simulated=metadata.simulated,
            missing_credentials=missing,
        )

    def _entry_state(self, entry: ProviderEntry) -> ProviderState:
        status = "excluded" if entry.status == "excluded" else "planned"
        return ProviderState(
            id=entry.id,
            name=entry.name,
            status=status,
            message=STATUS_MESSAGES[status],
            adapter=None,
            entry=entry,
        )
