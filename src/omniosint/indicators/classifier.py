"""The universal input classifier.

Every parser offers the readings it recognises, each with a rank and a reason.
The classifier never picks one reading when several are comparably likely:
the result is then ``ambiguous`` and lists them all, and the user chooses.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable

from omniosint.core.errors import ValidationFailed
from omniosint.indicators.digests import parse_digest
from omniosint.indicators.files import classify_file_content
from omniosint.indicators.geo import parse_coordinates
from omniosint.indicators.identity import parse_phone, parse_username
from omniosint.indicators.model import RANK_WEIGHT, Candidate, Classification, Status
from omniosint.indicators.network import parse_asn, parse_cidr, parse_ip, parse_range
from omniosint.indicators.software import parse_cve, parse_package, parse_purl
from omniosint.indicators.text import clean_text, parse_name, parse_question
from omniosint.indicators.threat import as_threat_indicator, parse_malware_name, refang
from omniosint.indicators.types import TYPE_ORDER, IndicatorType
from omniosint.indicators.web import (
    parse_domain,
    parse_email,
    parse_ssh_repository,
    parse_url,
)
from omniosint.indicators.wording import in_sentence, with_article

MAX_INPUT_LENGTH = 2000
MAX_MENTIONS = 20

# Invisible characters that sneak in with copy and paste. Removed, with a note.
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))
# Bidirectional controls can make text read differently from what it is
# ("Trojan Source"). Removed, with a warning.
_BIDI = dict.fromkeys(
    map(ord, "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f")
)

# Readings of free text that only make sense when nothing more specific matched.
_FREE_TEXT = frozenset(
    {IndicatorType.ORGANIZATION, IndicatorType.BUSINESS_NAME, IndicatorType.QUESTION}
)
# Readings that are noise next to a strong, specific reading ("8.8.8.8" is not
# a phone number, "AS15169" is not a username).
_NOISE_NEXT_TO_STRONG = frozenset({IndicatorType.PHONE, IndicatorType.ASN})


def _is_generic(item: Candidate) -> bool:
    if item.type in _FREE_TEXT:
        return True
    if item.type is IndicatorType.USERNAME:
        return item.details.get("form") == "plain"
    if item.type is IndicatorType.PACKAGE:
        return not item.details.get("ecosystem")
    return False


# Readings that can be written defanged.
_DEFANGABLE = frozenset(
    {
        IndicatorType.URL,
        IndicatorType.DOMAIN,
        IndicatorType.IPV4,
        IndicatorType.IPV6,
        IndicatorType.EMAIL,
    }
)

# "scheme://user:password@host": the credentials are removed from any input,
# whatever it is classified as, so that they never reach history or logs.
_URL_CREDENTIALS_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]{1,15}://)[^\s/@]+@")

Parser = Callable[[str], list[Candidate]]


def _token_parsers(default_region: str | None) -> tuple[Parser, ...]:
    return (
        parse_cve,
        parse_ip,
        parse_cidr,
        parse_range,
        parse_asn,
        parse_email,
        parse_ssh_repository,
        parse_url,
        parse_domain,
        parse_digest,
        parse_package,
        parse_coordinates,
        parse_malware_name,
        parse_username,
        lambda text: parse_phone(text, default_region),
        parse_name,
    )


def _phrase_parsers(default_region: str | None) -> tuple[Parser, ...]:
    return (
        parse_coordinates,
        lambda text: parse_phone(text, default_region),
        parse_range,
        parse_digest,
        parse_asn,
        parse_question,
        parse_name,
    )


def sanitize(text: str) -> tuple[str, list[str]]:
    """Validate raw input and remove invisible characters. Raises ``ValidationFailed``."""
    if len(text) > MAX_INPUT_LENGTH:
        raise ValidationFailed(f"The input is longer than {MAX_INPUT_LENGTH:,} characters.")
    notes: list[str] = []
    cleaned = text.translate(_INVISIBLE)
    if cleaned != text:
        notes.append("Invisible characters were removed.")
    without_bidi = cleaned.translate(_BIDI)
    if without_bidi != cleaned:
        notes.append(
            "Text-direction control characters were removed: they can make text look "
            "different from what it is."
        )
    for char in without_bidi:
        if unicodedata.category(char) in ("Cc", "Cf", "Cs", "Co") and char not in "\t\n\r":
            raise ValidationFailed("The input contains control characters.")
    without_credentials = _URL_CREDENTIALS_RE.sub(r"\1", without_bidi)
    if without_credentials != without_bidi:
        notes.append("A user name or password inside an address was removed; it is never stored.")
    return without_credentials.strip(), notes


def _rank_key(item: Candidate) -> tuple[int, int]:
    return (-RANK_WEIGHT[item.rank], TYPE_ORDER[item.type])


def _dedupe(items: Iterable[Candidate]) -> list[Candidate]:
    best: dict[tuple[IndicatorType, str], Candidate] = {}
    for item in items:
        key = (item.type, item.value)
        current = best.get(key)
        if current is None or RANK_WEIGHT[item.rank] > RANK_WEIGHT[current.rank]:
            best[key] = item
    return sorted(best.values(), key=_rank_key)


def _adjust(items: list[Candidate]) -> list[Candidate]:
    specific = [item for item in items if not _is_generic(item)]
    if any(item.rank == "strong" for item in specific):
        # A strong specific reading ("CVE-2021-44228", "example.com") leaves no
        # room for generic ones, nor for weak unrelated ones.
        items = [
            item
            for item in items
            if not _is_generic(item)
            and not (item.type in _NOISE_NEXT_TO_STRONG and item.rank != "strong")
        ]
    elif specific:
        items = [item for item in items if not (_is_generic(item) and item.rank == "weak")]
    if any(
        item.type in (IndicatorType.REPOSITORY_URL, IndicatorType.SOCIAL_PROFILE_URL)
        and item.rank == "strong"
        for item in items
    ):
        # The specific reading leads; the plain URL stays available.
        items = [
            item.model_copy(update={"rank": "plausible"})
            if item.type is IndicatorType.URL and item.rank == "strong"
            else item
            for item in items
        ]
    return items


def _status(items: list[Candidate]) -> Status:
    if not items:
        return "unrecognized"
    top, others = items[0], items[1:]
    if not others:
        return "recognized"
    if top.rank == "strong" and all(item.rank != "strong" for item in others):
        return "recognized"
    return "ambiguous"


def _message(status: str, items: list[Candidate]) -> str:
    if status == "unrecognized":
        return "Not recognised as any supported input type."
    top = items[0]
    if status == "recognized":
        message = f"Recognised as {with_article(top.label)}."
        if len(items) > 1:
            others = ", ".join(in_sentence(item.label) for item in items[1:4])
            message += f" Also possible: {others}."
        return message
    return f"This input can be read in {len(items)} ways. Choose the one you mean."


def _hints(text: str) -> list[str]:
    hints: list[str] = []
    lowered = text.lower()
    if re.match(r"^(?:javascript|data|file|vbscript|about|chrome):", lowered):
        hints.append("Only web addresses (http, https, ftp, ws, wss) are accepted as URLs.")
    if re.match(r"^[a-z]:\\", lowered) or lowered.startswith(
        ("/etc/", "/home/", "/usr/", "~/", "\\\\")
    ):
        hints.append(
            "This looks like a path on a computer. To classify a file use "
            "`omniosint classify --file`; uploads arrive in Phase 9."
        )
    if re.match(r"^ghsa-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}$", lowered):
        hints.append(
            "GitHub advisory identifiers are not an input type; "
            "use the CVE identifier if it has one."
        )
    if not hints:
        hints.append(
            "Supported inputs include email addresses, phone numbers, usernames, domains, URLs, IP "
            "addresses and ranges, AS numbers, hashes, CVE identifiers, packages, coordinates "
            "and questions."
        )
    return hints


def extract_mentions(text: str) -> list[Candidate]:
    """Indicators named inside free text, such as a question."""
    found: list[Candidate] = []
    seen: set[tuple[IndicatorType, str]] = set()
    strict: tuple[Parser, ...] = (
        parse_cve,
        parse_email,
        parse_ip,
        parse_cidr,
        parse_purl,
        parse_digest,
        lambda token: parse_url(token) if "://" in token else [],
        lambda token: parse_asn(token) if token[:2].lower() == "as" else [],
        parse_domain,
    )
    for raw in text.split():
        token = raw.strip(".,;:!?()[]{}\"'<>\u00ab\u00bb\u201c\u201d\u2018\u2019")
        if len(token) < 3:
            continue
        token, _ = refang(token)
        for parser in strict:
            readings = [item for item in parser(token) if item.rank == "strong"]
            if readings:
                for item in readings[:1]:
                    key = (item.type, item.value)
                    if key not in seen:
                        seen.add(key)
                        found.append(item)
                break
        if len(found) >= MAX_MENTIONS:
            break
    return found


def classify(text: str, *, default_region: str | None = None) -> Classification:
    """Classify one input. Raises ``ValidationFailed`` for oversized or malformed input."""
    value, notes = sanitize(text)
    if not value:
        return Classification(
            input="",
            status="unrecognized",
            candidates=(),
            message="Enter something to classify.",
        )
    phrase = clean_text(value)
    restored, refanged = refang(phrase)
    single_token = not any(char.isspace() for char in restored)
    parsers = _token_parsers(default_region) if single_token else _phrase_parsers(default_region)
    readings: list[Candidate] = []
    for parser in parsers:
        readings.extend(parser(restored))
    if refanged:
        threat = [as_threat_indicator(item) for item in readings if item.type in _DEFANGABLE]
        readings.extend(threat)
        notes.append("The input was written defanged; it was restored before reading.")
    if notes:
        readings = [item.model_copy(update={"notes": (*notes, *item.notes)}) for item in readings]
    readings = _dedupe(_adjust(readings))
    status = _status(readings)
    mentions: list[Candidate] = []
    if any(item.type is IndicatorType.QUESTION for item in readings):
        mentions = extract_mentions(restored)
    return Classification(
        input=value,
        status=status,
        candidates=tuple(readings),
        mentions=tuple(mentions),
        refanged=refanged,
        message=_message(status, readings),
        hints=tuple(_hints(value)) if status == "unrecognized" else (),
    )


def classify_file(
    name: str | None, head: bytes, size: int | None = None, sha256: str | None = None
) -> Classification:
    """Classify a file from its name and first bytes (see ``indicators.files``)."""
    readings = _dedupe(classify_file_content(name, head, size, sha256))
    mentions: list[Candidate] = []
    if sha256:
        mentions = [item for item in parse_digest(sha256) if item.type is IndicatorType.FILE_HASH]
    status = _status(readings)
    return Classification(
        input=name or "file",
        status=status,
        candidates=tuple(readings),
        mentions=tuple(mentions),
        message=_message(status, readings),
    )
