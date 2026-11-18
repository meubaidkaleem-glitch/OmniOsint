"""Type labels inside sentences."""

from __future__ import annotations


def in_sentence(label: str) -> str:
    """A type label inside a sentence: "Domain" becomes "domain", while labels
    that start with an acronym ("IPv4 address", "CVE identifier") are kept."""
    first = label.split(" ", 1)[0]
    if len(first) > 1 and any(char.isupper() for char in first[1:]):
        return label
    return label[:1].lower() + label[1:]


def with_article(label: str) -> str:
    """ "a domain", "an IPv4 address", "a URL", "geographic coordinates"."""
    phrase = in_sentence(label)
    if label.endswith("coordinates"):  # plural: no article
        return phrase
    if label.startswith(("IP", "ASN")):  # letters said aloud: "eye-pee"
        return f"an {phrase}"
    if label[:1] in "Uu":  # "username", "URL": a "you" sound
        return f"a {phrase}"
    return f"{'an' if label[:1].lower() in 'aeio' else 'a'} {phrase}"
