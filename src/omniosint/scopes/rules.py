"""Scope rules and targets: validation and matching, without the database."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import cast

from omniosint.core.errors import ValidationFailed
from omniosint.indicators.types import IndicatorType
from omniosint.indicators.web import normalize_hostname, split_url
from omniosint.net.addresses import IPAddress, IPNetwork

# Broader than this needs a different kind of authority than a scope record.
MIN_IPV4_PREFIX = 8
MIN_IPV6_PREFIX = 16


def _invalid(message: str) -> ValidationFailed:
    return ValidationFailed(message, details=[{"field": "value", "message": message}])


def normalize_rule(kind: str, value: str) -> str:
    """The canonical form of a rule value. Raises ``ValidationFailed``."""
    text = value.strip()
    if kind == "domain":
        normalized = normalize_hostname(text)
        if normalized is None or "." not in normalized[0]:
            raise _invalid("Not a valid domain name.")
        return normalized[0]
    if kind == "wildcard":
        if not text.startswith("*."):
            raise _invalid("A wildcard rule is written *.example.com.")
        normalized = normalize_hostname(text[2:])
        if normalized is None or "." not in normalized[0]:
            raise _invalid("Not a valid domain name after *.")
        return "*." + normalized[0]
    if kind == "ip":
        try:
            return ipaddress.ip_address(text).compressed
        except ValueError as error:
            raise _invalid("Not a valid IP address.") from error
    if kind == "cidr":
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError as error:
            raise _invalid("Not a valid CIDR block.") from error
        minimum = MIN_IPV4_PREFIX if network.version == 4 else MIN_IPV6_PREFIX
        if network.prefixlen < minimum:
            raise _invalid(f"A block larger than /{minimum} cannot be put in a scope.")
        return network.with_prefixlen
    if kind == "url_prefix":
        parsed = split_url(text)
        if parsed is None or parsed.assumed_scheme:
            raise _invalid("Not a valid http(s) URL; include the scheme.")
        return parsed.canonical
    raise _invalid(f"Unknown rule kind {kind!r}.")


@dataclass(frozen=True, slots=True)
class Target:
    """What an active operation would touch."""

    kind: str  # "domain", "ip", "network" or "url"
    value: str
    host: str | None = None
    address: IPAddress | None = None
    networks: tuple[IPNetwork, ...] = ()

    def describe(self) -> str:
        return self.value


def target_for(indicator_type: IndicatorType, value: str) -> Target | None:
    """The network target named by an indicator, or ``None`` if it names none."""
    if indicator_type is IndicatorType.DOMAIN:
        return Target("domain", value, host=value)
    if indicator_type in (IndicatorType.IPV4, IndicatorType.IPV6):
        return Target("ip", value, address=ipaddress.ip_address(value))
    if indicator_type in (IndicatorType.IP_RANGE, IndicatorType.NETWORK_PREFIX):
        if "-" in value:
            first, last = (ipaddress.ip_address(part) for part in value.split("-"))
            blocks = cast(
                tuple[IPNetwork, ...], tuple(ipaddress.summarize_address_range(first, last))
            )
            return Target("network", value, networks=blocks)
        return Target("network", value, networks=(ipaddress.ip_network(value),))
    if indicator_type is IndicatorType.URL:
        parsed = split_url(value)
        if parsed is None:
            return None
        address = None
        if parsed.host_type != "domain":
            address = ipaddress.ip_address(parsed.host)
        return Target("url", parsed.canonical, host=parsed.host, address=address)
    return None


def _host_matches_domain(host: str | None, domain: str) -> bool:
    return host is not None and host == domain


def _host_matches_wildcard(host: str | None, wildcard: str) -> bool:
    return host is not None and host.endswith(wildcard[1:]) and host != wildcard[2:]


def _url_under(url: str, prefix: str) -> bool:
    if not url.startswith(prefix):
        return False
    rest = url[len(prefix) :]
    return prefix.endswith("/") or rest == "" or rest[0] in "/?"


def covers(kind: str, value: str, target: Target) -> bool:
    """Whether an inclusion rule covers the whole target."""
    if kind == "domain":
        return _host_matches_domain(target.host, value) and target.address is None
    if kind == "wildcard":
        return _host_matches_wildcard(target.host, value) and target.address is None
    if kind == "ip":
        if target.address is not None:
            return target.address == ipaddress.ip_address(value)
        return bool(target.networks) and all(
            network.num_addresses == 1 and network.network_address == ipaddress.ip_address(value)
            for network in target.networks
        )
    if kind == "cidr":
        rule_network = ipaddress.ip_network(value)
        if target.address is not None:
            return target.address in rule_network
        return bool(target.networks) and all(
            network.version == rule_network.version and network.subnet_of(rule_network)  # type: ignore[arg-type]
            for network in target.networks
        )
    if kind == "url_prefix":
        return target.kind == "url" and _url_under(target.value, value)
    return False


def touches(kind: str, value: str, target: Target) -> bool:
    """Whether an exclusion rule touches any part of the target."""
    if kind == "domain":
        return target.host is not None and (
            target.host == value or target.host.endswith("." + value)
        )
    if kind == "wildcard":
        return _host_matches_wildcard(target.host, value)
    if kind in ("ip", "cidr"):
        rule_network = ipaddress.ip_network(value)
        if target.address is not None:
            return target.address in rule_network
        return any(
            network.version == rule_network.version and network.overlaps(rule_network)
            for network in target.networks
        )
    if kind == "url_prefix":
        return target.kind == "url" and _url_under(target.value, value)
    return False
