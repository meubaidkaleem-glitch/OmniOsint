"""Free text: organisation and business names, investigation questions."""

from __future__ import annotations

import re
import unicodedata

from omniosint.indicators.model import Candidate, candidate
from omniosint.indicators.types import IndicatorType

_QUESTION_WORDS = frozenset(
    {
        "who", "what", "which", "where", "when", "why", "how", "whose", "whom",
        "is", "are", "was", "were", "does", "do", "did", "can", "could", "should",
        "would", "will", "has", "have", "had",
    }
)  # fmt: skip
_REQUEST_WORDS = frozenset(
    {
        "find", "show", "list", "identify", "investigate", "check", "determine", "map",
        "compare", "summarise", "summarize", "explain", "enumerate", "lookup", "trace",
        "search", "tell", "give", "describe", "assess", "analyse", "analyze",
    }
)  # fmt: skip
# Legal forms that mark the name of a registered business.
_LEGAL_FORMS = (
    "inc", "incorporated", "corp", "corporation", "co", "company", "llc", "l.l.c",
    "ltd", "limited", "plc", "llp", "lp", "gmbh", "ag", "sa", "s.a", "sas", "sarl",
    "srl", "s.r.l", "spa", "s.p.a", "bv", "b.v", "nv", "n.v", "ab", "asa", "oy", "oyj",
    "kk", "k.k", "pty", "pvt", "sdn bhd", "bhd", "se", "kg", "ohg", "a/s", "aps",
    "as", "jsc", "pjsc", "ooo", "sp. z o.o", "s.l", "sl", "s.c", "gk", "nl", "tbk",
)  # fmt: skip
_LEGAL_FORM_RE = re.compile(
    r"(?:^|[\s,])(?:" + "|".join(re.escape(form) for form in _LEGAL_FORMS) + r")\.?$",
    re.IGNORECASE,
)
_ORGANISATION_WORDS = frozenset(
    {
        "university", "college", "school", "institute", "academy", "ministry",
        "department", "agency", "authority", "commission", "council", "committee",
        "foundation", "association", "society", "federation", "union", "bureau",
        "office", "trust", "hospital", "church", "party", "club", "group", "network",
        "centre", "center", "laboratory", "laboratories", "organisation",
        "organization", "government", "police", "army", "navy", "court", "parliament",
        "museum", "library", "charity", "cooperative", "consortium",
    }
)  # fmt: skip
_NAME_CHARS_RE = re.compile(r"^[\w&.,'\u2019()\-/+ ]+$", re.UNICODE)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SINGLE_NAME_RE = re.compile(r"^[^\W\d_][\w&'\u2019-]{1,63}$", re.UNICODE)


def clean_text(text: str) -> str:
    """Collapse whitespace and apply Unicode NFC normalisation."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def parse_question(text: str) -> list[Candidate]:
    value = clean_text(text)
    words = _words(value)
    # Numbers and hex pairs are not words of a sentence.
    real = [word for word in words if len(word) >= 3 and word.isalpha()]
    if len(words) < 3 or len(real) < 2:
        return []
    first = words[0]
    if (value.endswith("?") and len(real) >= 2) or (first in _QUESTION_WORDS and len(real) >= 3):
        rank, reason = "strong", "A question in plain language."
    elif first in _REQUEST_WORDS and len(real) >= 3:
        rank, reason = "strong", "A request in plain language."
    elif len(real) >= 6:
        rank, reason = "plausible", "A sentence in plain language."
    else:
        return []
    return [
        candidate(
            IndicatorType.QUESTION,
            value,
            rank=rank,  # type: ignore[arg-type]
            reason=reason,
            notes=[
                "Questions are answered by the AI investigation engine (Phase 10). "
                "The indicators it mentions can be investigated now."
            ],
            details={"words": len(words)},
            no_entity=True,
        )
    ]


def parse_name(text: str) -> list[Candidate]:
    """Organisation and business names. A name is never read as a person."""
    value = clean_text(text)
    if not 2 <= len(value) <= 200 or not _NAME_CHARS_RE.match(value) or value.endswith("?"):
        return []
    words = _words(value)
    if not words or len(words) > 12 or not any(char.isalpha() for char in value):
        return []
    if " " not in value and not _SINGLE_NAME_RE.match(value):
        # "example.com" or "a/b" are not names; one plain word may be.
        return []
    if words[0] in _QUESTION_WORDS | _REQUEST_WORDS and len(words) >= 3:
        return []
    key = value.casefold()
    legal_form = bool(_LEGAL_FORM_RE.search(value)) and len(words) >= 2
    organisation_word = any(word in _ORGANISATION_WORDS for word in words)
    single = " " not in value
    if legal_form:
        business_rank, organisation_rank = "strong", "plausible"
        reason_business = "Ends with a company legal form."
    elif organisation_word:
        business_rank, organisation_rank = "weak", "strong"
        reason_business = "Could be a trading name."
    elif single:
        business_rank, organisation_rank = "weak", "weak"
        reason_business = "Could be the name of a business."
    else:
        business_rank, organisation_rank = "plausible", "plausible"
        reason_business = "Could be the name of a business."
    note = (
        "Read as the name of an organisation. "
        "OmniOSINT does not search for private individuals by name."
    )
    return [
        candidate(
            IndicatorType.ORGANIZATION,
            key,
            display=value,
            rank=organisation_rank,  # type: ignore[arg-type]
            reason=(
                "Contains a word typical of organisation names."
                if organisation_word
                else "Could be the name of an organisation."
            ),
            notes=[note],
            details={"name": value},
        ),
        candidate(
            IndicatorType.BUSINESS_NAME,
            key,
            display=value,
            rank=business_rank,  # type: ignore[arg-type]
            reason=reason_business,
            notes=[note],
            details={"name": value, "legal_form": legal_form},
        ),
    ]
