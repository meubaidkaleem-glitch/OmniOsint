"""Collection plans: what would run for an indicator, and why or why not.

A plan is computed before anything runs and shown to the user. Each step is a
provider capability with a status:

* ``ready``: will be called;
* ``cached``: a fresh earlier result will be reused instead of calling again;
* ``needs_approval``: will wait for approval (active operations always; paid
  calls above the configured threshold);
* ``blocked``: cannot run as asked (the reason says why: no scope, scope
  denies the target, active operation in passive mode);
* ``skipped``: not chosen (paid while "free first", or not among the selected
  providers);
* ``unavailable``: the adapter exists but is not configured or not enabled;
* ``planned`` / ``excluded``: from the catalogue; no adapter exists.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omniosint.core.config import CollectionSettings
from omniosint.core.timeutil import isoformat
from omniosint.database.models import CollectionResult
from omniosint.indicators.types import MODULES_BY_ID, TYPE_INFO
from omniosint.providers.base import Capability, CostKind, Indicator, Operation
from omniosint.providers.manager import call_key
from omniosint.providers.registry import ProviderRegistry, ProviderState
from omniosint.scopes.manager import ScopeView, evaluate
from omniosint.scopes.rules import target_for

Mode = Literal["passive", "active"]
Strategy = Literal["free_first", "include_paid"]
SELECTED_STATUSES = frozenset({"ready", "cached", "needs_approval"})
SIMULATED_WARNING = (
    "The simulated provider is enabled. It generates test data; its results are "
    "marked simulated and are never real findings."
)


@dataclass(frozen=True, slots=True)
class PlanOptions:
    mode: Mode = "passive"
    strategy: Strategy = "free_first"
    providers: tuple[str, ...] | None = None
    scope_id: uuid.UUID | None = None
    force_refresh: bool = False
    # Passed to adapters unchanged; only the simulated provider reads any today.
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlanStep:
    provider_id: str
    provider_name: str
    capability_id: str | None
    capability_name: str | None
    description: str | None
    operation: str | None
    active: bool
    cost: dict[str, Any]
    simulated: bool
    status: str
    message: str
    phase: int | None = None
    cache_key: str | None = None
    cached_result_id: str | None = None
    cache_fresh_until: str | None = None
    scope_decision: dict[str, Any] | None = None

    @property
    def selected(self) -> bool:
        return self.status in SELECTED_STATUSES

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["selected"] = self.selected
        return data


@dataclass(frozen=True, slots=True)
class CollectionPlan:
    indicator: Indicator
    options: PlanOptions
    scope_name: str | None
    steps: tuple[PlanStep, ...]
    warnings: tuple[str, ...]

    @property
    def selected(self) -> tuple[PlanStep, ...]:
        return tuple(step for step in self.steps if step.selected)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for step in self.steps:
            counts[step.status] = counts.get(step.status, 0) + 1
        counts["selected"] = len(self.selected)
        return counts

    def as_dict(self) -> dict[str, Any]:
        info = TYPE_INFO[self.indicator.type]
        return {
            "indicator": {
                "type": self.indicator.type.value,
                "label": info.label,
                "value": self.indicator.value,
                "display": self.indicator.display,
                "entity_type": self.indicator.entity_type.value
                if self.indicator.entity_type
                else None,
            },
            "mode": self.options.mode,
            "strategy": self.options.strategy,
            "providers": list(self.options.providers)
            if self.options.providers is not None
            else None,
            "scope": (
                {"id": str(self.options.scope_id), "name": self.scope_name}
                if self.options.scope_id
                else None
            ),
            "force_refresh": self.options.force_refresh,
            "modules": [
                {
                    "id": module,
                    "title": MODULES_BY_ID[module].title,
                    "phase": MODULES_BY_ID[module].phase,
                }
                for module in info.modules
            ],
            "steps": [step.as_dict() for step in self.steps],
            "summary": self.summary(),
            "warnings": list(self.warnings),
        }


def options_for_provider(options: PlanOptions, simulated: bool) -> dict[str, Any]:
    """Free-form options reach only the simulated provider; real adapters accept
    no options they have not declared."""
    return dict(options.provider_options) if simulated else {}


def cache_key_for(
    provider_id: str, capability_id: str, indicator: Indicator, provider_options: dict[str, Any]
) -> str:
    raw = call_key(provider_id, capability_id, indicator, provider_options)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def find_fresh_result(
    session: AsyncSession, cache_key: str, now: datetime
) -> CollectionResult | None:
    """The newest original result for ``cache_key`` that has not expired."""
    result = await session.execute(
        select(CollectionResult)
        .where(
            CollectionResult.cache_key == cache_key,
            CollectionResult.expires_at > now,
            CollectionResult.from_cache.is_(False),
            CollectionResult.normalization_error.is_(None),
            CollectionResult.page == 1,
        )
        .order_by(CollectionResult.received_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


class Planner:
    def __init__(self, registry: ProviderRegistry, settings: CollectionSettings) -> None:
        self._registry = registry
        self._settings = settings

    def _needs_paid_approval(self, capability: Capability) -> bool:
        cost = capability.cost
        if cost.kind is CostKind.FREE:
            return False
        if cost.kind is CostKind.CREDITS and cost.credits_per_call is not None:
            return cost.credits_per_call > self._settings.approval_credit_threshold
        return True  # paid, or cost unknown

    async def plan(
        self,
        session: AsyncSession,
        indicator: Indicator,
        options: PlanOptions,
        *,
        scope: ScopeView | None,
        now: datetime,
    ) -> CollectionPlan:
        steps: list[PlanStep] = []
        target = target_for(indicator.type, indicator.value)
        free_alternative = any(
            option.provider.runnable
            and option.capability.cost.is_free
            and not option.capability.active
            for option in self._registry.options_for(indicator.type)
        )
        for option in self._registry.options_for(indicator.type):
            steps.append(
                await self._step(
                    session,
                    option.provider,
                    option.capability,
                    indicator,
                    options,
                    scope,
                    target,
                    now,
                    free_alternative,
                )
            )
        info = TYPE_INFO[indicator.type]
        for state in self._registry.planned_for(info.modules):
            steps.append(
                PlanStep(
                    provider_id=state.id,
                    provider_name=state.name,
                    capability_id=None,
                    capability_name=None,
                    description=state.entry.notes if state.entry else None,
                    operation=None,
                    active=False,
                    cost={"kind": "unknown", "credits_per_call": None, "note": None},
                    simulated=False,
                    status=state.status,
                    message=state.message,
                    phase=state.entry.phase if state.entry else None,
                )
            )
        warnings: list[str] = []
        if indicator.details.get("public") is False:
            warnings.append(
                "This is not public Internet address space: public sources hold no data "
                "about it, and active operations need an approved internal scope."
            )
        if any(step.simulated and step.selected for step in steps):
            warnings.append(SIMULATED_WARNING)
        if not any(step.selected for step in steps):
            warnings.append(
                "Nothing can be collected for this indicator yet. The providers that will "
                "serve it are listed with the phase that delivers them."
            )
        return CollectionPlan(
            indicator=indicator,
            options=options,
            scope_name=scope.name if scope else None,
            steps=tuple(steps),
            warnings=tuple(warnings),
        )

    async def _step(
        self,
        session: AsyncSession,
        state: ProviderState,
        capability: Capability,
        indicator: Indicator,
        options: PlanOptions,
        scope: ScopeView | None,
        target: Any,
        now: datetime,
        free_alternative: bool,
    ) -> PlanStep:
        metadata = state.metadata
        assert metadata is not None
        cache_key = cache_key_for(
            state.id, capability.id, indicator, options_for_provider(options, metadata.simulated)
        )
        base: dict[str, Any] = {
            "provider_id": state.id,
            "provider_name": state.name,
            "capability_id": capability.id,
            "capability_name": capability.name,
            "description": capability.description,
            "operation": capability.operation.value,
            "active": capability.active,
            "cost": capability.cost.as_dict(),
            "simulated": metadata.simulated,
            "cache_key": cache_key,
        }

        def step(status: str, message: str, **extra: Any) -> PlanStep:
            return PlanStep(**base, status=status, message=message, **extra)

        if not state.runnable:
            return step("unavailable", state.message)
        if options.providers is not None and state.id not in options.providers:
            return step("skipped", "Not among the selected providers.")
        decision = None
        if capability.active:
            if options.mode != "active":
                return step(
                    "blocked",
                    "Active operation: it contacts the target. "
                    "Choose active mode and an approved scope.",
                )
            decision = evaluate(Operation(capability.operation), target, scope, now=now)
            if not decision.allowed:
                return step("blocked", decision.reason, scope_decision=decision.as_dict())
        paid = not capability.cost.is_free
        if paid and options.strategy == "free_first" and options.providers is None:
            reason = (
                "Paid; free sources come first."
                if free_alternative
                else "Paid; include paid providers to use it."
            )
            return step("skipped", reason)
        if capability.cache_ttl_seconds > 0 and not options.force_refresh:
            cached = await find_fresh_result(session, cache_key, now)
            if cached is not None:
                return step(
                    "cached",
                    "A fresh result from earlier is reused; the provider is not called again.",
                    cached_result_id=str(cached.id),
                    cache_fresh_until=isoformat(cached.expires_at),
                )
        if decision is not None:
            return step(
                "needs_approval",
                f"Active operation allowed by the scope; it waits for approval. {decision.reason}",
                scope_decision=decision.as_dict(),
            )
        if paid and self._needs_paid_approval(capability):
            credits = capability.cost.credits_per_call
            cost_text = f"{credits:g} credits" if credits is not None else "an unknown cost"
            return step("needs_approval", f"Costs {cost_text} per call; it waits for approval.")
        return step("ready", "Will be collected.")
