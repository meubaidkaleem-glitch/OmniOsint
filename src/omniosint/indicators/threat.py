"""Defanged indicators and malware names."""

from __future__ import annotations

import re

from omniosint.indicators.model import Candidate, candidate
from omniosint.indicators.types import IndicatorType

# Common ways of "defanging" an indicator so that it cannot be clicked.
_REFANG_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^hxxp(s?)", re.IGNORECASE), r"http\1"),
    (re.compile(r"^fxp", re.IGNORECASE), "ftp"),
    (re.compile(r"\[\s*:\s*\]|\(\s*:\s*\)"), ":"),
    (re.compile(r"\[\s*://\s*\]|\(\s*://\s*\)"), "://"),
    (
        re.compile(
            r"\[\s*\.\s*\]|\(\s*\.\s*\)|\{\s*\.\s*\}|\[dot\]|\(dot\)|\{dot\}", re.IGNORECASE
        ),
        ".",
    ),
    (re.compile(r"\\\."), "."),
    (re.compile(r"\[\s*@\s*\]|\(\s*@\s*\)|\[at\]|\(at\)|\{at\}", re.IGNORECASE), "@"),
    (re.compile(r"\[\s*/\s*\]"), "/"),
)

_MICROSOFT_NAME_RE = re.compile(
    r"^(?P<category>[A-Za-z]{3,24}):(?P<platform>[A-Za-z0-9]{2,16})/(?P<family>[A-Za-z0-9_][A-Za-z0-9_.!#-]{1,80})$"
)
_DOTTED_NAME_RE = re.compile(
    r"^(?:(?P<platform>Win32|Win64|W32|W64|Linux|Unix|MacOS|OSX|Android|JS|HTML|VBS|PDF|MSIL|Script)[./])?"
    r"(?P<category>Trojan|Backdoor|Worm|Ransom|Ransomware|Exploit|HackTool|PUA|PUP|Adware|Spyware|Virus|"
    r"Downloader|Dropper|Rootkit|Stealer|Keylogger|Miner|CoinMiner|Botnet|Banker|RAT)"
    r"(?P<rest>[./:-][A-Za-z0-9_.!#/-]{2,80})$",
    re.IGNORECASE,
)
_MALPEDIA_RE = re.compile(
    r"^(?P<platform>win|elf|osx|apk|ios|js|jar|ps1|py|vbs|php|asp|aix|symbian)\.(?P<family>[a-z0-9_]{2,64})$"
)


def refang(text: str) -> tuple[str, bool]:
    """Undo common defanging. Returns the restored text and whether anything changed."""
    result = text
    for pattern, replacement in _REFANG_RULES:
        result = pattern.sub(replacement, result)
    return result, result != text


def parse_malware_name(text: str) -> list[Candidate]:
    value = text.strip()
    if not value or any(char.isspace() for char in value):
        return []
    microsoft = _MICROSOFT_NAME_RE.match(value)
    if microsoft and "://" not in value:
        return [
            candidate(
                IndicatorType.MALWARE_INDICATOR,
                value,
                rank="strong",
                reason="An antivirus detection name (category:platform/family).",
                notes=["Detection names differ between vendors; one family can have many names."],
                details={
                    "form": "detection_name",
                    "category": microsoft["category"],
                    "platform": microsoft["platform"],
                    "family": microsoft["family"],
                },
            )
        ]
    dotted = _DOTTED_NAME_RE.match(value)
    if dotted:
        return [
            candidate(
                IndicatorType.MALWARE_INDICATOR,
                value,
                rank="plausible",
                reason="Shaped like an antivirus detection name.",
                notes=["Detection names differ between vendors; one family can have many names."],
                details={"form": "detection_name", "category": dotted["category"]},
            )
        ]
    malpedia = _MALPEDIA_RE.match(value)
    if malpedia:
        return [
            candidate(
                IndicatorType.MALWARE_INDICATOR,
                value,
                rank="plausible",
                reason="Shaped like a Malpedia malware family identifier (platform.family).",
                details={
                    "form": "family_identifier",
                    "platform": malpedia["platform"],
                    "family": malpedia["family"],
                },
            )
        ]
    return []


def as_threat_indicator(item: Candidate) -> Candidate:
    """The malware-indicator reading of an indicator that was written defanged."""
    return candidate(
        IndicatorType.MALWARE_INDICATOR,
        item.value,
        display=item.display,
        rank="plausible",
        reason=(
            f"Written defanged, as indicators of compromise usually are; underneath it is a "
            f"{item.label.lower()}."
        ),
        notes=["Defanging was removed to read the indicator. Nothing was contacted."],
        details={"form": "defanged_indicator", "indicator_type": item.type.value},
    )
