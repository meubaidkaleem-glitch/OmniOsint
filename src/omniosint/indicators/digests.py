"""File hashes and certificate fingerprints."""

from __future__ import annotations

import re

from omniosint.indicators.model import Candidate, candidate
from omniosint.indicators.types import IndicatorType

_HEX_LENGTHS = {32: "md5", 40: "sha1", 56: "sha224", 64: "sha256", 96: "sha384", 128: "sha512"}
_CERT_ALGORITHMS = {40: "sha1", 64: "sha256"}
_PREFIX_RE = re.compile(
    r"^(?P<label>(?:(?P<algo>md5|sha-?1|sha-?224|sha-?256|sha-?384|sha-?512)"
    r"(?:\s+fingerprint)?)|fingerprint)\s*[:=]\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_SEPARATED_RE = re.compile(r"^[0-9a-fA-F]{2}(?:[:\- ][0-9a-fA-F]{2}){15,63}$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_SSDEEP_RE = re.compile(r"^\d{1,10}:[A-Za-z0-9/+]{1,64}:[A-Za-z0-9/+]{1,64}$")
_TLSH_RE = re.compile(r"^(?:T1)?[0-9A-Fa-f]{70}$")


def _algorithm_name(raw: str | None) -> str | None:
    return raw.lower().replace("-", "") if raw else None


def parse_digest(text: str) -> list[Candidate]:
    value = text.strip()
    stated_algorithm: str | None = None
    fingerprint_label = False
    prefix = _PREFIX_RE.match(value)
    if prefix:
        stated_algorithm = _algorithm_name(prefix["algo"])
        fingerprint_label = "fingerprint" in prefix["label"].lower()
        value = prefix["rest"].strip()

    if _SSDEEP_RE.match(value) and not prefix and _plausible_ssdeep(value):
        return [_fuzzy("ssdeep", value)]
    if _TLSH_RE.match(value) and not prefix and value.upper().startswith("T1"):
        return [_fuzzy("tlsh", value.upper())]

    separated = bool(_SEPARATED_RE.match(value))
    hex_value = re.sub(r"[:\- ]", "", value) if separated else value
    if not _HEX_RE.match(hex_value):
        return []
    hex_value = hex_value.lower()
    algorithm = _HEX_LENGTHS.get(len(hex_value))
    if algorithm is None:
        return []
    if stated_algorithm and stated_algorithm != algorithm:
        return []

    notes: list[str] = []
    if separated:
        notes.append("Separators between the bytes were removed.")
    results: list[Candidate] = []
    cert_algorithm = _CERT_ALGORITHMS.get(len(hex_value))
    # Certificates are usually shown with separators or a "Fingerprint" label;
    # files are not. A bare SHA-1 or SHA-256 value is genuinely either.
    if cert_algorithm:
        cert_rank = "strong" if (separated or fingerprint_label) else "plausible"
        results.append(
            candidate(
                IndicatorType.CERTIFICATE_FINGERPRINT,
                hex_value,
                rank=cert_rank,  # type: ignore[arg-type]
                reason=f"A {cert_algorithm.upper()} digest, the form of a certificate fingerprint.",
                notes=notes,
                details={"algorithm": cert_algorithm},
            )
        )
    if fingerprint_label or separated:
        file_rank = "weak"
    elif cert_algorithm:
        file_rank = "plausible"
    else:
        file_rank = "strong"
    results.append(
        candidate(
            IndicatorType.FILE_HASH,
            hex_value,
            rank=file_rank,  # type: ignore[arg-type]
            reason=f"A {algorithm.upper()} digest, the form of a file hash.",
            notes=notes,
            details={"algorithm": algorithm},
        )
    )
    return results


def _plausible_ssdeep(value: str) -> bool:
    """ssdeep block sizes are 3 times a power of two, and its chunks are base64
    text; this keeps out look-alikes such as the time 12:34:56."""
    block, first, second = value.split(":")
    size = int(block)
    if size < 3 or size % 3 or (size // 3) & (size // 3 - 1):
        return False
    return len(first) + len(second) >= 8 and bool(re.search(r"[A-Za-z]", first + second))


def _fuzzy(algorithm: str, value: str) -> Candidate:
    return candidate(
        IndicatorType.FILE_HASH,
        value,
        rank="strong",
        reason=f"A {algorithm} similarity hash.",
        notes=["A similarity hash finds similar files; a match is not proof of identity."],
        details={"algorithm": algorithm, "fuzzy": True},
    )
