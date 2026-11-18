"""Universal input engine: classification, validation and normalisation."""

from omniosint.indicators.classifier import MAX_INPUT_LENGTH, classify, classify_file
from omniosint.indicators.model import Candidate, Classification
from omniosint.indicators.types import (
    ENTITY_LABELS,
    MODULES,
    MODULES_BY_ID,
    TYPE_INFO,
    EntityType,
    IndicatorType,
)

__all__ = [
    "ENTITY_LABELS",
    "MAX_INPUT_LENGTH",
    "MODULES",
    "MODULES_BY_ID",
    "TYPE_INFO",
    "Candidate",
    "Classification",
    "EntityType",
    "IndicatorType",
    "classify",
    "classify_file",
]
