"""From user input to the indicator a plan runs on.

The classifier's best reading is used only when the input is unambiguous.
Otherwise the caller must say which reading it means; the error lists them.
"""

from __future__ import annotations

from omniosint.core.errors import ValidationFailed
from omniosint.indicators import classify
from omniosint.indicators.model import Classification
from omniosint.indicators.types import TYPE_INFO, IndicatorType
from omniosint.providers.base import Indicator

_FILE_TYPES = frozenset({IndicatorType.FILE, IndicatorType.IMAGE, IndicatorType.DOCUMENT})


def resolve(
    text: str, wanted: IndicatorType | None = None, *, default_region: str | None = None
) -> tuple[Indicator, Classification]:
    result = classify(text, default_region=default_region)
    readings = [
        {"field": "type", "message": f"{item.type.value}: {item.label} ({item.rank})"}
        for item in result.candidates
    ]
    if wanted is not None:
        candidate = result.find(wanted)
        if candidate is None:
            raise ValidationFailed(
                f"The input cannot be read as {TYPE_INFO[wanted].label.lower()}.",
                details=readings or [{"field": "input", "message": result.message}],
            )
    else:
        candidate = result.best
        if candidate is None:
            if result.status == "ambiguous":
                raise ValidationFailed(
                    "The input can be read in several ways: choose one with `type`.",
                    details=readings,
                )
            raise ValidationFailed(
                "The input was not recognised.",
                details=[{"field": "input", "message": hint} for hint in result.hints],
            )
    if candidate.type in _FILE_TYPES:
        raise ValidationFailed("Files are examined from uploads, which arrive in Phase 9.")
    if candidate.type is IndicatorType.QUESTION:
        raise ValidationFailed(
            "Questions are answered by the AI investigation engine (Phase 10). "
            "Investigate the indicators the question mentions instead."
        )
    if candidate.details.get("needs_country_code"):
        raise ValidationFailed("Add the country code (for example +44) to the phone number.")
    indicator = Indicator(
        type=candidate.type,
        value=candidate.value,
        display=candidate.display,
        entity_type=candidate.entity_type,
        details=dict(candidate.details),
    )
    return indicator, result
