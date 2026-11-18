"""What the classifier returns."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from omniosint.indicators.types import TYPE_INFO, EntityType, IndicatorType

Rank = Literal["strong", "plausible", "weak"]
RANK_WEIGHT: dict[str, int] = {"strong": 3, "plausible": 2, "weak": 1}

Status = Literal["recognized", "ambiguous", "unrecognized"]


class Candidate(BaseModel):
    """One way of reading the input.

    ``rank`` orders the readings; it is not a confidence assessment of any
    finding. ``value`` is the normalised form used as the identity of the
    indicator, ``display`` the form shown to people.
    """

    model_config = ConfigDict(frozen=True)

    type: IndicatorType
    label: str
    value: str
    display: str
    rank: Rank
    reason: str
    notes: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)
    entity_type: EntityType | None
    modules: tuple[str, ...]


def candidate(
    indicator: IndicatorType,
    value: str,
    *,
    rank: Rank,
    reason: str,
    display: str | None = None,
    notes: list[str] | tuple[str, ...] = (),
    details: dict[str, Any] | None = None,
    entity_type: EntityType | None = None,
    no_entity: bool = False,
) -> Candidate:
    """Build a candidate. ``entity_type`` defaults to the type's usual entity;
    ``no_entity`` says that this reading names no single entity."""
    info = TYPE_INFO[indicator]
    resolved = None if no_entity else (entity_type or info.entity_type)
    return Candidate(
        type=indicator,
        label=info.label,
        value=value,
        display=display if display is not None else value,
        rank=rank,
        reason=reason,
        notes=tuple(dict.fromkeys(note for note in notes if note)),
        details=details or {},
        entity_type=resolved,
        modules=info.modules,
    )


class Classification(BaseModel):
    model_config = ConfigDict(frozen=True)

    input: str
    status: Status
    candidates: tuple[Candidate, ...]
    mentions: tuple[Candidate, ...] = ()
    refanged: bool = False
    message: str
    hints: tuple[str, ...] = ()

    @property
    def best(self) -> Candidate | None:
        """The reading to use without asking, or ``None`` when the user must choose."""
        if self.status == "recognized" and self.candidates:
            return self.candidates[0]
        return None

    def find(self, indicator: IndicatorType) -> Candidate | None:
        return next((item for item in self.candidates if item.type is indicator), None)
