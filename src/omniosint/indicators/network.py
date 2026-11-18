"""IP addresses, ranges, network prefixes and autonomous system numbers."""

from __future__ import annotations

import ipaddress
import re
from typing import cast

from omniosint.indicators.model import Candidate, candidate
from omniosint.indicators.types import IndicatorType
from omniosint.net.addresses import (
    AddressScope,
    IPAddress,
    IPNetwork,
    classify_address,
    classify_network,
    network_note,
)

_MAX_RANGE_BLOCKS = 32
_ASN_MAX = 4_294_967_295
_ASN_RE = re.compile(r"^(?:AS|ASN)\s?(?P<number>\d{1,10}(?:\.\d{1,5})?)$", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^\d{1,10}$")
_SHORT_RANGE_RE = re.compile(r"^(?P<prefix>(?:\d{1,3}\.){3})(?P<first>\d{1,3})-(?P<last>\d{1,3})$")


def parse_address(text: str) -> IPAddress | None:
    value = text.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _address_candidate(address: IPAddress, raw: str) -> Candidate:
    info = classify_address(address)
    notes: list[str] = []
    if info.note:
        notes.append(info.note)
    if info.embedded is not None:
        notes.append(f"This IPv6 address carries the IPv4 address {info.embedded}.")
    if "%" in raw:
        notes.append("The zone index after % only has meaning on the computer that wrote it.")
    indicator = IndicatorType.IPV4 if address.version == 4 else IndicatorType.IPV6
    details: dict[str, object] = {
        "version": address.version,
        "scope": info.scope.value,
        "public": info.is_public,
    }
    if info.range_name:
        details["special_range"] = info.range_name
    if info.embedded is not None:
        details["embedded_ipv4"] = str(info.embedded)
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    value = f"::ffff:{mapped}" if mapped is not None else address.compressed
    return candidate(
        indicator,
        value,
        rank="strong",
        reason=f"Valid IPv{address.version} address.",
        notes=notes,
        details=details,
    )


def parse_ip(text: str) -> list[Candidate]:
    address = parse_address(text)
    if address is None:
        return []
    return [_address_candidate(address, text)]


def _network_details(network: IPNetwork) -> dict[str, object]:
    scope = classify_network(network)
    return {
        "version": network.version,
        "prefix_length": network.prefixlen,
        "first": str(network.network_address),
        "last": str(network.broadcast_address),
        "addresses": network.num_addresses,
        "scope": scope.value,
        "public": scope is AddressScope.GLOBAL,
    }


def parse_cidr(text: str) -> list[Candidate]:
    value = text.strip()
    if "/" not in value:
        return []
    address_part, _, length = value.partition("/")
    if not length.isdigit() or parse_address(address_part) is None:
        return []
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return []
    exact = network.network_address == ipaddress.ip_address(address_part.strip("[]"))
    notes: list[str] = []
    note = network_note(network)
    if note:
        notes.append(note)
    if not exact:
        notes.append(f"Host bits were set; the network is {network.with_prefixlen}.")
    if network.prefixlen == 0:
        notes.append("This is the entire address space.")
    details = _network_details(network)
    as_range = candidate(
        IndicatorType.IP_RANGE,
        network.with_prefixlen,
        rank="strong",
        reason="CIDR notation: a block of addresses.",
        notes=notes,
        details=details,
    )
    as_prefix = candidate(
        IndicatorType.NETWORK_PREFIX,
        network.with_prefixlen,
        rank="strong" if exact else "weak",
        reason=(
            "CIDR notation can also name a routed network prefix (who announces it, who holds it)."
            if exact
            else "Could name the routed prefix, but host bits were set."
        ),
        notes=notes,
        details=details,
    )
    return [as_range, as_prefix]


def parse_range(text: str) -> list[Candidate]:
    value = text.strip().replace(" ", "")
    notes: list[str] = []
    short = _SHORT_RANGE_RE.match(value)
    if short:
        value = f"{short['prefix']}{short['first']}-{short['prefix']}{short['last']}"
        notes.append(f"Read as {value}.")
    if value.count("-") != 1:
        return []
    first_text, last_text = value.split("-")
    first, last = parse_address(first_text), parse_address(last_text)
    if first is None or last is None or first.version != last.version:
        return []
    if int(first) > int(last):
        return []
    blocks = cast(list[IPNetwork], list(ipaddress.summarize_address_range(first, last)))
    count = int(last) - int(first) + 1
    for block in blocks:
        note = network_note(block)
        if note:
            notes.append(note)
    canonical = f"{first.compressed}-{last.compressed}"
    details: dict[str, object] = {
        "version": first.version,
        "first": first.compressed,
        "last": last.compressed,
        "addresses": count,
        "cidr_blocks": [block.with_prefixlen for block in blocks[:_MAX_RANGE_BLOCKS]],
        "cidr_block_count": len(blocks),
        "public": all(classify_network(block) is AddressScope.GLOBAL for block in blocks),
    }
    results = [
        candidate(
            IndicatorType.IP_RANGE,
            canonical,
            rank="strong",
            reason="A first-last range of addresses.",
            notes=notes,
            details=details,
            # Several blocks are several prefixes, not one entity.
            no_entity=len(blocks) > 1,
        )
    ]
    if len(blocks) == 1:
        block = blocks[0]
        results.append(
            candidate(
                IndicatorType.NETWORK_PREFIX,
                block.with_prefixlen,
                rank="weak",
                reason=f"The range is exactly the prefix {block.with_prefixlen}.",
                notes=notes,
                details=_network_details(block),
            )
        )
    return results


def _asn_notes(number: int) -> list[str]:
    if number == 0:
        return ["AS0 is reserved and never announced (RFC 7607)."]
    if number == 23456:
        return ["AS23456 is AS_TRANS, a placeholder used by older routers (RFC 6793)."]
    if 64496 <= number <= 64511 or 65536 <= number <= 65551:
        return ["Documentation AS number, reserved for examples (RFC 5398)."]
    if 64512 <= number <= 65534 or 4_200_000_000 <= number <= 4_294_967_294:
        return ["Private AS number: it does not identify a public network (RFC 6996)."]
    if number in (65535, _ASN_MAX):
        return ["Reserved AS number (RFC 7300)."]
    return []


def parse_asn(text: str) -> list[Candidate]:
    value = text.strip()
    match = _ASN_RE.match(value)
    plain = _DIGITS_RE.match(value)
    if not match and not plain:
        return []
    raw = match["number"] if match else value
    notes: list[str] = []
    if "." in raw:
        high, low = (int(part) for part in raw.split("."))
        if high > 65535 or low > 65535:
            return []
        number = high * 65536 + low
        notes.append(f"Converted from asdot notation ({raw}).")
    else:
        number = int(raw)
    if number > _ASN_MAX:
        return []
    notes.extend(_asn_notes(number))
    if plain:
        notes.append("A plain number; read as an AS number. Write AS before it to be explicit.")
    return [
        candidate(
            IndicatorType.ASN,
            f"AS{number}",
            # Numbers in use today have up to six digits; a longer bare number
            # is more often something else (a phone number, an account id).
            rank="strong" if match else ("plausible" if len(value) <= 6 else "weak"),
            reason="Autonomous system number." if match else "A number in the AS number range.",
            notes=notes,
            details={"number": number, "four_byte": number > 65535},
        )
    ]
