"""Input types, entity types and intelligence modules.

The 24 input types and 29 entity types are those of the development brief
(sections 4.1 and 6.1); the module identifiers are those used by the provider
catalogue (``config/providers.yaml``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IndicatorType(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    USERNAME = "username"
    DOMAIN = "domain"
    URL = "url"
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    IP_RANGE = "ip_range"
    ASN = "asn"
    NETWORK_PREFIX = "network_prefix"
    ORGANIZATION = "organization"
    BUSINESS_NAME = "business_name"
    FILE_HASH = "file_hash"
    FILE = "file"
    IMAGE = "image"
    DOCUMENT = "document"
    CERTIFICATE_FINGERPRINT = "certificate_fingerprint"
    SOCIAL_PROFILE_URL = "social_profile_url"
    REPOSITORY_URL = "repository_url"
    PACKAGE = "package"
    CVE = "cve"
    MALWARE_INDICATOR = "malware_indicator"
    COORDINATES = "coordinates"
    QUESTION = "question"


class EntityType(StrEnum):
    PERSON_REFERENCE = "person_reference"
    EMAIL = "email"
    PHONE = "phone"
    USERNAME = "username"
    DOMAIN = "domain"
    SUBDOMAIN = "subdomain"
    URL = "url"
    IP_ADDRESS = "ip_address"
    NETWORK_PREFIX = "network_prefix"
    ASN = "asn"
    ORGANIZATION = "organization"
    ROUTER = "router"
    SWITCH = "switch"
    FIREWALL = "firewall"
    SERVER = "server"
    ACCESS_POINT = "access_point"
    ENDPOINT = "endpoint"
    CLOUD_ASSET = "cloud_asset"
    CERTIFICATE = "certificate"
    IMAGE = "image"
    DOCUMENT = "document"
    FILE_HASH = "file_hash"
    REPOSITORY = "repository"
    PACKAGE = "package"
    VULNERABILITY = "vulnerability"
    THREAT_INDICATOR = "threat_indicator"
    MALWARE_SAMPLE = "malware_sample"
    PUBLIC_EVENT = "public_event"
    GEOGRAPHIC_LOCATION = "geographic_location"


ENTITY_LABELS: dict[EntityType, str] = {
    EntityType.PERSON_REFERENCE: "Person reference",
    EntityType.EMAIL: "Email address",
    EntityType.PHONE: "Phone number",
    EntityType.USERNAME: "Username",
    EntityType.DOMAIN: "Domain",
    EntityType.SUBDOMAIN: "Subdomain",
    EntityType.URL: "URL",
    EntityType.IP_ADDRESS: "IP address",
    EntityType.NETWORK_PREFIX: "Network prefix",
    EntityType.ASN: "Autonomous system",
    EntityType.ORGANIZATION: "Organisation",
    EntityType.ROUTER: "Router",
    EntityType.SWITCH: "Switch",
    EntityType.FIREWALL: "Firewall",
    EntityType.SERVER: "Server",
    EntityType.ACCESS_POINT: "Access point",
    EntityType.ENDPOINT: "Endpoint",
    EntityType.CLOUD_ASSET: "Cloud asset",
    EntityType.CERTIFICATE: "Certificate",
    EntityType.IMAGE: "Image",
    EntityType.DOCUMENT: "Document",
    EntityType.FILE_HASH: "File hash",
    EntityType.REPOSITORY: "Repository",
    EntityType.PACKAGE: "Package",
    EntityType.VULNERABILITY: "Vulnerability",
    EntityType.THREAT_INDICATOR: "Threat indicator",
    EntityType.MALWARE_SAMPLE: "Malware sample metadata",
    EntityType.PUBLIC_EVENT: "Public event",
    EntityType.GEOGRAPHIC_LOCATION: "Geographic location",
}


@dataclass(frozen=True, slots=True)
class Module:
    """One of the intelligence modules of brief section 5."""

    id: str
    title: str
    phase: int


MODULES: tuple[Module, ...] = (
    Module("email", "Email intelligence", 4),
    Module("phone", "Phone intelligence", 4),
    Module("username", "Username intelligence", 4),
    Module("domain", "Domain intelligence", 4),
    Module("ip", "IP intelligence", 4),
    Module("internet_assets", "Internet-wide asset intelligence", 5),
    Module("network_topology", "Network topology", 8),
    Module("social", "Social and public profile intelligence", 9),
    Module("organization", "Organisation intelligence", 9),
    Module("image", "Image intelligence", 9),
    Module("document", "Document intelligence", 9),
    Module("geospatial", "Geospatial intelligence", 9),
    Module("threat", "Threat intelligence", 6),
    Module("vulnerability", "Vulnerability intelligence", 6),
    Module("software_supply_chain", "Software and supply chain intelligence", 6),
    Module("brand_protection", "Brand abuse and impersonation", 11),
    Module("news", "News and events intelligence", 9),
    Module("academic", "Academic and research intelligence", 9),
    Module("cloud", "Cloud and digital infrastructure", 8),
    Module("historical", "Historical and temporal intelligence", 11),
    Module("ai_investigation", "AI investigation", 10),
)
MODULES_BY_ID: dict[str, Module] = {module.id: module for module in MODULES}


@dataclass(frozen=True, slots=True)
class TypeInfo:
    type: IndicatorType
    label: str
    description: str
    input_kind: str  # "text" or "file"
    entity_type: EntityType | None
    modules: tuple[str, ...]
    example: str


_TYPES: tuple[TypeInfo, ...] = (
    TypeInfo(
        IndicatorType.EMAIL,
        "Email address",
        "An email address.",
        "text",
        EntityType.EMAIL,
        ("email", "domain", "threat", "historical"),
        "analyst@example.org",
    ),
    TypeInfo(
        IndicatorType.PHONE,
        "Phone number",
        "A telephone number, preferably in international format (+44 20 7946 0958).",
        "text",
        EntityType.PHONE,
        ("phone",),
        "+44 20 7946 0958",
    ),
    TypeInfo(
        IndicatorType.USERNAME,
        "Username",
        "An account name or handle on a public platform.",
        "text",
        EntityType.USERNAME,
        ("username", "social"),
        "@example_handle",
    ),
    TypeInfo(
        IndicatorType.DOMAIN,
        "Domain",
        "A domain or host name.",
        "text",
        EntityType.DOMAIN,
        ("domain", "internet_assets", "threat", "brand_protection", "historical"),
        "example.com",
    ),
    TypeInfo(
        IndicatorType.URL,
        "URL",
        "A web address (http, https, ftp, ws or wss).",
        "text",
        EntityType.URL,
        ("domain", "threat", "historical"),
        "https://example.com/login",
    ),
    TypeInfo(
        IndicatorType.IPV4,
        "IPv4 address",
        "A single IPv4 address.",
        "text",
        EntityType.IP_ADDRESS,
        ("ip", "internet_assets", "threat", "network_topology", "historical"),
        "198.51.100.7",
    ),
    TypeInfo(
        IndicatorType.IPV6,
        "IPv6 address",
        "A single IPv6 address.",
        "text",
        EntityType.IP_ADDRESS,
        ("ip", "internet_assets", "threat", "network_topology", "historical"),
        "2001:db8::7",
    ),
    TypeInfo(
        IndicatorType.IP_RANGE,
        "IP range",
        "A range of addresses, as CIDR (192.0.2.0/24) or first-last.",
        "text",
        EntityType.NETWORK_PREFIX,
        ("ip", "internet_assets", "network_topology"),
        "192.0.2.0/24",
    ),
    TypeInfo(
        IndicatorType.ASN,
        "Autonomous system number",
        "An autonomous system (AS) number.",
        "text",
        EntityType.ASN,
        ("ip", "network_topology"),
        "AS64500",
    ),
    TypeInfo(
        IndicatorType.NETWORK_PREFIX,
        "Network prefix",
        "A routed network prefix, as announced in BGP.",
        "text",
        EntityType.NETWORK_PREFIX,
        ("ip", "network_topology"),
        "198.51.100.0/24",
    ),
    TypeInfo(
        IndicatorType.ORGANIZATION,
        "Organisation name",
        "The name of an organisation: a company, agency, institution or group.",
        "text",
        EntityType.ORGANIZATION,
        ("organization", "news", "academic"),
        "Example University",
    ),
    TypeInfo(
        IndicatorType.BUSINESS_NAME,
        "Public business name",
        "The registered or trading name of a business.",
        "text",
        EntityType.ORGANIZATION,
        ("organization", "news", "brand_protection"),
        "Example Trading Ltd",
    ),
    TypeInfo(
        IndicatorType.FILE_HASH,
        "File hash",
        "A cryptographic or fuzzy hash of a file (MD5, SHA-1, SHA-256, SHA-512, ssdeep, TLSH).",
        "text",
        EntityType.FILE_HASH,
        ("threat",),
        "44d88612fea8a8f36de82e1278abb02f",
    ),
    TypeInfo(
        IndicatorType.FILE,
        "File",
        "A file to examine. Uploads arrive in Phase 9; the type is detected from its content.",
        "file",
        EntityType.FILE_HASH,
        ("document", "image", "threat"),
        "sample.bin",
    ),
    TypeInfo(
        IndicatorType.IMAGE,
        "Image",
        "An image file. Uploads arrive in Phase 9.",
        "file",
        EntityType.IMAGE,
        ("image", "geospatial"),
        "photo.jpg",
    ),
    TypeInfo(
        IndicatorType.DOCUMENT,
        "Document",
        "A document file (PDF, office formats, text). Uploads arrive in Phase 9.",
        "file",
        EntityType.DOCUMENT,
        ("document",),
        "report.pdf",
    ),
    TypeInfo(
        IndicatorType.CERTIFICATE_FINGERPRINT,
        "Certificate fingerprint",
        "The SHA-1 or SHA-256 fingerprint of an X.509 certificate.",
        "text",
        EntityType.CERTIFICATE,
        ("domain", "internet_assets"),
        "SHA256 Fingerprint=AB:CD:...",
    ),
    TypeInfo(
        IndicatorType.SOCIAL_PROFILE_URL,
        "Public social profile URL",
        "The address of a public profile on a social platform.",
        "text",
        EntityType.URL,
        ("social", "username"),
        "https://github.com/example",
    ),
    TypeInfo(
        IndicatorType.REPOSITORY_URL,
        "Repository URL",
        "The address of a source code repository.",
        "text",
        EntityType.REPOSITORY,
        ("software_supply_chain",),
        "https://github.com/example/project",
    ),
    TypeInfo(
        IndicatorType.PACKAGE,
        "Package name",
        "A software package, best with its ecosystem (npm:name, pypi:name or a purl).",
        "text",
        EntityType.PACKAGE,
        ("software_supply_chain", "vulnerability"),
        "pkg:pypi/example-package@1.0.0",
    ),
    TypeInfo(
        IndicatorType.CVE,
        "CVE identifier",
        "A Common Vulnerabilities and Exposures identifier.",
        "text",
        EntityType.VULNERABILITY,
        ("vulnerability", "threat"),
        "CVE-2021-44228",
    ),
    TypeInfo(
        IndicatorType.MALWARE_INDICATOR,
        "Malware indicator",
        "A malware family or detection name, or a defanged indicator of compromise.",
        "text",
        EntityType.THREAT_INDICATOR,
        ("threat",),
        "Trojan:Win32/Example",
    ),
    TypeInfo(
        IndicatorType.COORDINATES,
        "Geographic coordinates",
        "Latitude and longitude, in decimal degrees or degrees-minutes-seconds.",
        "text",
        EntityType.GEOGRAPHIC_LOCATION,
        ("geospatial",),
        "51.5007, -0.1246",
    ),
    TypeInfo(
        IndicatorType.QUESTION,
        "Investigation question",
        "A question or request in plain language.",
        "text",
        None,
        ("ai_investigation",),
        "Which domains share infrastructure with example.com?",
    ),
)

TYPE_INFO: dict[IndicatorType, TypeInfo] = {info.type: info for info in _TYPES}

# Display order of candidates of equal strength: specific before general.
TYPE_ORDER: dict[IndicatorType, int] = {
    indicator: position
    for position, indicator in enumerate(
        (
            IndicatorType.CVE,
            IndicatorType.REPOSITORY_URL,
            IndicatorType.SOCIAL_PROFILE_URL,
            IndicatorType.EMAIL,
            IndicatorType.URL,
            IndicatorType.IPV4,
            IndicatorType.IPV6,
            IndicatorType.IP_RANGE,
            IndicatorType.NETWORK_PREFIX,
            IndicatorType.ASN,
            IndicatorType.CERTIFICATE_FINGERPRINT,
            IndicatorType.FILE_HASH,
            IndicatorType.PACKAGE,
            IndicatorType.COORDINATES,
            IndicatorType.PHONE,
            IndicatorType.DOMAIN,
            IndicatorType.MALWARE_INDICATOR,
            IndicatorType.USERNAME,
            IndicatorType.BUSINESS_NAME,
            IndicatorType.ORGANIZATION,
            IndicatorType.QUESTION,
            IndicatorType.DOCUMENT,
            IndicatorType.IMAGE,
            IndicatorType.FILE,
        )
    )
}
