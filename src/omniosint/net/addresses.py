"""Classification of IP addresses by the IANA special-purpose registries.

One table serves two purposes: the input classifier explains what kind of
address a user entered, and the outbound HTTP client refuses to connect to
anything that is not a public Internet address unless a scope allows it.

Sources: IANA IPv4 and IPv6 Special-Purpose Address Registries (RFC 6890 and
the RFCs listed per entry).
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import StrEnum
from functools import cache

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class AddressScope(StrEnum):
    GLOBAL = "global"
    PRIVATE = "private"
    SHARED = "shared"
    LOOPBACK = "loopback"
    LINK_LOCAL = "link_local"
    MULTICAST = "multicast"
    DOCUMENTATION = "documentation"
    BENCHMARKING = "benchmarking"
    UNSPECIFIED = "unspecified"
    BROADCAST = "broadcast"
    RESERVED = "reserved"


@dataclass(frozen=True, slots=True)
class SpecialRange:
    network: IPNetwork
    scope: AddressScope
    name: str


_NOTES: dict[AddressScope, str] = {
    AddressScope.PRIVATE: (
        "Private address space: public sources hold no data about it. It can only "
        "be investigated inside an approved internal scope."
    ),
    AddressScope.SHARED: (
        "Shared address space used inside carrier networks (carrier-grade NAT); "
        "not reachable from the Internet."
    ),
    AddressScope.LOOPBACK: "Loopback address: it always means the local computer.",
    AddressScope.LINK_LOCAL: "Link-local address: only meaningful on one network segment.",
    AddressScope.MULTICAST: "Multicast address: it identifies a group, not a host.",
    AddressScope.DOCUMENTATION: (
        "Documentation address: reserved for examples, never used on the Internet."
    ),
    AddressScope.BENCHMARKING: "Benchmarking address: reserved for network test equipment.",
    AddressScope.UNSPECIFIED: "Unspecified address: it identifies no host.",
    AddressScope.BROADCAST: "Broadcast address: it identifies no single host.",
    AddressScope.RESERVED: "Reserved address: not used on the public Internet.",
}


def _ranges() -> tuple[SpecialRange, ...]:
    table: list[tuple[str, AddressScope, str]] = [
        # IPv4
        ("0.0.0.0/32", AddressScope.UNSPECIFIED, "Unspecified address"),
        ("0.0.0.0/8", AddressScope.RESERVED, "This network (RFC 791)"),
        ("10.0.0.0/8", AddressScope.PRIVATE, "Private use (RFC 1918)"),
        ("100.64.0.0/10", AddressScope.SHARED, "Shared address space (RFC 6598)"),
        ("127.0.0.0/8", AddressScope.LOOPBACK, "Loopback (RFC 1122)"),
        ("169.254.0.0/16", AddressScope.LINK_LOCAL, "Link local (RFC 3927)"),
        ("172.16.0.0/12", AddressScope.PRIVATE, "Private use (RFC 1918)"),
        ("192.0.0.0/24", AddressScope.RESERVED, "IETF protocol assignments (RFC 6890)"),
        ("192.0.2.0/24", AddressScope.DOCUMENTATION, "Documentation TEST-NET-1 (RFC 5737)"),
        ("192.88.99.0/24", AddressScope.RESERVED, "Deprecated 6to4 relay anycast (RFC 7526)"),
        ("192.168.0.0/16", AddressScope.PRIVATE, "Private use (RFC 1918)"),
        ("198.18.0.0/15", AddressScope.BENCHMARKING, "Benchmarking (RFC 2544)"),
        ("198.51.100.0/24", AddressScope.DOCUMENTATION, "Documentation TEST-NET-2 (RFC 5737)"),
        ("203.0.113.0/24", AddressScope.DOCUMENTATION, "Documentation TEST-NET-3 (RFC 5737)"),
        ("224.0.0.0/4", AddressScope.MULTICAST, "Multicast (RFC 5771)"),
        ("255.255.255.255/32", AddressScope.BROADCAST, "Limited broadcast (RFC 919)"),
        ("240.0.0.0/4", AddressScope.RESERVED, "Reserved (RFC 1112)"),
        # IPv6
        ("::/128", AddressScope.UNSPECIFIED, "Unspecified address (RFC 4291)"),
        ("::1/128", AddressScope.LOOPBACK, "Loopback (RFC 4291)"),
        ("100::/64", AddressScope.RESERVED, "Discard-only (RFC 6666)"),
        ("2001:2::/48", AddressScope.BENCHMARKING, "Benchmarking (RFC 5180)"),
        ("2001:db8::/32", AddressScope.DOCUMENTATION, "Documentation (RFC 3849)"),
        ("3fff::/20", AddressScope.DOCUMENTATION, "Documentation (RFC 9637)"),
        ("5f00::/16", AddressScope.RESERVED, "Segment routing SIDs (RFC 9602)"),
        ("fc00::/7", AddressScope.PRIVATE, "Unique local (RFC 4193)"),
        ("fe80::/10", AddressScope.LINK_LOCAL, "Link-local unicast (RFC 4291)"),
        ("fec0::/10", AddressScope.RESERVED, "Deprecated site-local (RFC 3879)"),
        ("ff00::/8", AddressScope.MULTICAST, "Multicast (RFC 4291)"),
        ("::/96", AddressScope.RESERVED, "Deprecated IPv4-compatible (RFC 4291)"),
        ("64:ff9b:1::/48", AddressScope.RESERVED, "Local-use IPv4/IPv6 translation (RFC 8215)"),
    ]
    return tuple(
        SpecialRange(ipaddress.ip_network(cidr), scope, name) for cidr, scope, name in table
    )


@cache
def special_ranges() -> tuple[SpecialRange, ...]:
    return _ranges()


def embedded_ipv4(address: IPAddress) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 address carries and leads to: IPv4-mapped, NAT64
    (RFC 6052), 6to4 (RFC 3056; the tunnel endpoint) or Teredo (RFC 4380; the
    client the traffic is relayed to)."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return address.ipv4_mapped
        if address in ipaddress.IPv6Network("64:ff9b::/96"):
            return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
        if address.sixtofour is not None:
            return address.sixtofour
        if address.teredo is not None:
            return address.teredo[1]
    return None


@dataclass(frozen=True, slots=True)
class AddressInfo:
    address: IPAddress
    scope: AddressScope
    range_name: str | None
    embedded: ipaddress.IPv4Address | None = None

    @property
    def is_public(self) -> bool:
        return self.scope is AddressScope.GLOBAL

    @property
    def note(self) -> str | None:
        return _NOTES.get(self.scope)


def classify_address(address: IPAddress) -> AddressInfo:
    """Scope of ``address``. IPv4 inside IPv6 (mapped, NAT64, 6to4, Teredo) is
    judged by the IPv4 part."""
    inner = embedded_ipv4(address)
    if inner is not None:
        info = classify_address(inner)
        return AddressInfo(address, info.scope, info.range_name, embedded=inner)
    # The most specific matching range wins (0.0.0.0/32 before 0.0.0.0/8).
    best: SpecialRange | None = None
    for special in special_ranges():
        if special.network.version != address.version or address not in special.network:
            continue
        if best is None or special.network.prefixlen > best.network.prefixlen:
            best = special
    if best is None:
        return AddressInfo(address, AddressScope.GLOBAL, None)
    return AddressInfo(address, best.scope, best.name)


def _containing(network: IPNetwork) -> tuple[SpecialRange | None, bool]:
    """The most specific special range containing ``network``, and whether it
    overlaps any special range it is not contained in."""
    best: SpecialRange | None = None
    partial = False
    for special in special_ranges():
        if special.network.version != network.version or not special.network.overlaps(network):
            continue
        if network.subnet_of(special.network):  # type: ignore[arg-type]
            if best is None or special.network.prefixlen > best.network.prefixlen:
                best = special
        else:
            partial = True
    return best, partial


def classify_network(network: IPNetwork) -> AddressScope:
    """Scope of a whole network. A network that mixes public and special space
    is reported as reserved: it cannot be treated as purely public."""
    best, partial = _containing(network)
    if best is not None:
        return best.scope
    return AddressScope.RESERVED if partial else AddressScope.GLOBAL


def network_note(network: IPNetwork) -> str | None:
    best, partial = _containing(network)
    if best is not None:
        return _NOTES.get(best.scope)
    return "Part of this range is not public Internet address space." if partial else None
