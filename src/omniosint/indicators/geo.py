"""Geographic coordinates."""

from __future__ import annotations

import re

from omniosint.indicators.model import Candidate, candidate
from omniosint.indicators.types import IndicatorType

_NUMBER = r"[+-]?\d{1,3}(?:\.\d+)?"
_DECIMAL_RE = re.compile(rf"^\s*(?P<lat>{_NUMBER})\s*(?P<sep>[,;]|\s)\s*(?P<lon>{_NUMBER})\s*$")
_GEO_URI_RE = re.compile(
    rf"^geo:(?P<lat>{_NUMBER}),(?P<lon>{_NUMBER})(?:,[-\d.]+)?(?:;.*)?$", re.IGNORECASE
)
_DMS_PART = (
    r"(?P<{n}d>\d{{1,3}}(?:\.\d+)?)\s*[\u00b0\u00ba:\s]\s*"
    r"(?:(?P<{n}m>\d{{1,2}}(?:\.\d+)?)\s*['\u2032\u2019:\s]\s*)?"
    r"(?:(?P<{n}s>\d{{1,2}}(?:\.\d+)?)\s*(?:\"|\u2033|''|\u201d)?\s*)?"
    r"(?P<{n}h>[NSEW])"
)
_DMS_RE = re.compile(
    "^\\s*" + _DMS_PART.format(n="a") + r"\s*[,;]?\s*" + _DMS_PART.format(n="b") + "\\s*$",
    re.IGNORECASE,
)
COORDINATE_NOTE = (
    "Coordinates as entered. Place names and maps arrive with the geospatial module (Phase 9)."
)


def _format(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def _result(
    lat: float, lon: float, *, rank: str, reason: str, precision: int | None
) -> list[Candidate]:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return []
    notes = [COORDINATE_NOTE]
    details: dict[str, object] = {"latitude": round(lat, 6), "longitude": round(lon, 6)}
    if precision is not None:
        # One decimal place of a degree is about 11 km; five is about 1 m.
        details["decimal_places"] = precision
        if precision < 2:
            notes.append("Few decimal places: this is only a rough area.")
    value = f"{_format(lat)},{_format(lon)}"
    return [
        candidate(
            IndicatorType.COORDINATES,
            value,
            display=f"{_format(lat)}, {_format(lon)}",
            rank=rank,  # type: ignore[arg-type]
            reason=reason,
            notes=notes,
            details=details,
        )
    ]


def _dms(groups: dict[str, str | None], prefix: str) -> tuple[float, str]:
    degrees = float(groups[f"{prefix}d"] or 0)
    minutes = float(groups[f"{prefix}m"] or 0)
    seconds = float(groups[f"{prefix}s"] or 0)
    hemisphere = (groups[f"{prefix}h"] or "").upper()
    if minutes >= 60 or seconds >= 60:
        raise ValueError("minutes and seconds must be below 60")
    value = degrees + minutes / 60 + seconds / 3600
    return (-value if hemisphere in ("S", "W") else value), hemisphere


def parse_coordinates(text: str) -> list[Candidate]:
    value = text.strip()
    uri = _GEO_URI_RE.match(value)
    if uri:
        lat, lon = float(uri["lat"]), float(uri["lon"])
        return _result(
            lat,
            lon,
            rank="strong",
            reason="A geo: URI.",
            precision=min(_decimals(uri["lat"]), _decimals(uri["lon"])),
        )
    decimal = _DECIMAL_RE.match(value)
    if decimal:
        lat_text, lon_text = decimal["lat"], decimal["lon"]
        places = min(_decimals(lat_text), _decimals(lon_text))
        separated_by_comma = decimal["sep"] in ",;"
        if places >= 1 and separated_by_comma:
            rank = "strong"
        elif places >= 1:
            rank = "plausible"
        else:
            rank = "weak"
        return _result(
            float(lat_text),
            float(lon_text),
            rank=rank,
            reason="Latitude and longitude in decimal degrees.",
            precision=places,
        )
    dms = _DMS_RE.match(value)
    if dms:
        groups = dms.groupdict()
        try:
            first, first_h = _dms(groups, "a")
            second, second_h = _dms(groups, "b")
        except ValueError:
            return []
        if first_h in ("N", "S") and second_h in ("E", "W"):
            lat, lon = first, second
        elif first_h in ("E", "W") and second_h in ("N", "S"):
            lat, lon = second, first
        else:
            return []
        return _result(
            lat, lon, rank="strong", reason="Degrees, minutes and seconds.", precision=None
        )
    return []
