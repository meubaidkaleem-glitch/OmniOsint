"""Phone numbers and usernames."""

from __future__ import annotations

import re

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType

from omniosint.indicators.model import Candidate, Rank, candidate
from omniosint.indicators.types import IndicatorType

_PHONE_CHARS_RE = re.compile(
    r"^\+?[0-9 ()./\-]{6,32}(?:\s*(?:ext\.?|x|#)\s*\d{1,6})?$", re.IGNORECASE
)
_NUMBER_TYPES: dict[int, str] = {
    PhoneNumberType.FIXED_LINE: "fixed_line",
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.SHARED_COST: "shared_cost",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "uan",
    PhoneNumberType.VOICEMAIL: "voicemail",
}
PHONE_CAVEAT = (
    "Country and line type come from the public numbering plan. They say nothing "
    "about who holds the number, and OmniOSINT does not look up subscribers."
)


def parse_phone(text: str, default_region: str | None = None) -> list[Candidate]:
    value = text.strip()
    if value.lower().startswith("tel:"):
        value = value[4:].split(";", 1)[0]
    if not _PHONE_CHARS_RE.match(value):
        return []
    digits = re.sub(r"\D", "", value.split("x")[0].split("ext")[0])
    if not 7 <= len(digits) <= 17:
        return []
    international = value.startswith("+") or value.startswith("00")
    if value.startswith("00"):
        value = "+" + value[2:]
    region = None if international else (default_region.upper() if default_region else None)
    if not international and region is None:
        if len(digits) < 8:
            return []
        return [
            candidate(
                IndicatorType.PHONE,
                digits,
                rank="weak",
                reason="Digits that could be a phone number, but without a country code.",
                notes=["Add the country code (for example +44) so the number can be validated."],
                details={"needs_country_code": True},
            )
        ]
    try:
        number = phonenumbers.parse(value, region)
    except NumberParseException:
        return []
    if not phonenumbers.is_possible_number(number):
        return []
    valid = phonenumbers.is_valid_number(number)
    e164 = phonenumbers.format_number(number, PhoneNumberFormat.E164)
    notes = [PHONE_CAVEAT]
    if not international:
        notes.append(f"No country code was given; the default region {region} was assumed.")
    if not valid:
        notes.append("The number has a possible length but is not assigned in the numbering plan.")
    if number.extension:
        notes.append(f"The extension {number.extension} was kept apart from the number.")
    rank: Rank
    if valid and international:
        rank = "strong"
    elif valid:
        rank = "plausible"
    else:
        rank = "weak"
    details: dict[str, object] = {
        "e164": e164,
        "international": phonenumbers.format_number(number, PhoneNumberFormat.INTERNATIONAL),
        "country_code": number.country_code,
        "numbering_plan_region": phonenumbers.region_code_for_number(number),
        "line_type": _NUMBER_TYPES.get(phonenumbers.number_type(number), "unknown"),
        "valid": valid,
    }
    if number.extension:
        details["extension"] = number.extension
    return [
        candidate(
            IndicatorType.PHONE,
            e164,
            display=details["international"],  # type: ignore[arg-type]
            rank=rank,
            reason="A valid phone number." if valid else "Shaped like a phone number.",
            notes=notes,
            details=details,
        )
    ]


# --------------------------------------------------------------------------- usernames
_HANDLE_RE = re.compile(r"^@(?P<name>[A-Za-z0-9_](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9_])?)$")
_FEDIVERSE_RE = re.compile(
    r"^@(?P<name>[A-Za-z0-9_.-]{1,64})@(?P<server>[A-Za-z0-9.-]+\.[A-Za-z]{2,63})$"
)
_PLAIN_RE = re.compile(r"^(?P<name>[A-Za-z0-9_](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9_])?)$")
USERNAME_CAVEAT = (
    "The same username on different platforms is a candidate link only, never proof "
    "that the accounts belong to one person."
)


def parse_username(text: str) -> list[Candidate]:
    value = text.strip()
    fediverse = _FEDIVERSE_RE.match(value)
    if fediverse:
        name, server = fediverse["name"], fediverse["server"].lower()
        return [
            candidate(
                IndicatorType.USERNAME,
                f"{name.lower()}@{server}",
                display=f"@{name}@{server}",
                rank="strong",
                reason="A fediverse handle (Mastodon and similar).",
                notes=[USERNAME_CAVEAT],
                details={"name": name, "server": server, "form": "fediverse"},
            )
        ]
    handle = _HANDLE_RE.match(value)
    if handle:
        name = handle["name"]
        return [
            candidate(
                IndicatorType.USERNAME,
                name.lower(),
                display=f"@{name}",
                rank="strong",
                reason="A handle written with a leading @.",
                notes=[USERNAME_CAVEAT, "Compared without regard to letter case."],
                details={"name": name, "form": "handle"},
            )
        ]
    plain = _PLAIN_RE.match(value)
    if not plain:
        return []
    name = plain["name"]
    if name.isdigit() or re.fullmatch(r"[0-9a-fA-F]{24,}", name) or re.fullmatch(r"[\d.]+", name):
        return []
    return [
        candidate(
            IndicatorType.USERNAME,
            name.lower(),
            display=name,
            rank="weak" if "." in name else "plausible",
            reason="Could be an account name.",
            notes=[USERNAME_CAVEAT, "Compared without regard to letter case."],
            details={"name": name, "form": "plain"},
        )
    ]
