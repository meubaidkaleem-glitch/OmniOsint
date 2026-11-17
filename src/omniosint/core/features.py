"""Feature registry: the single statement of what exists and what is planned.

The web interface, the dashboard and the CLI read this registry to decide what
to present as available. A section is marked ``available`` or ``partial`` only
when its backend exists and is tested; everything else is ``planned`` and is
shown as "Planned - integration not yet implemented".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FeatureStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    PLANNED = "planned"


PHASES: dict[int, str] = {
    0: "Requirements and architecture",
    1: "Project foundation",
    2: "Core intelligence foundation",
    3: "Investigation management",
    4: "First intelligence modules",
    5: "Internet asset providers",
    6: "Threat, vulnerability and software intelligence",
    7: "Universal graph engine",
    8: "Network topology and cloud infrastructure",
    9: "Social, organisation, image, document, geospatial, news and research",
    10: "AI investigation engine",
    11: "Historical intelligence, monitoring and brand protection",
    12: "Advanced analytics and workflow builder",
    13: "Reporting and enterprise capabilities",
    14: "Hardening and release",
}

CURRENT_PHASE = 1


@dataclass(frozen=True, slots=True)
class Feature:
    key: str
    title: str
    group: str | None
    phase: int
    status: FeatureStatus
    summary: str
    capabilities: tuple[str, ...]
    limitations: str | None = None

    @property
    def phase_title(self) -> str:
        return PHASES[self.phase]


_P = FeatureStatus.PLANNED

FEATURES: tuple[Feature, ...] = (
    Feature(
        key="dashboard",
        title="Dashboard",
        group=None,
        phase=1,
        status=FeatureStatus.PARTIAL,
        summary="System health, platform status and recent activity.",
        capabilities=(
            "System and service health",
            "Module availability by phase",
            "Recent activity from the audit trail",
        ),
        limitations=(
            "Investigation, finding, alert and provider-usage metrics appear when "
            "those modules are built (Phases 3, 5 and 11)."
        ),
    ),
    Feature(
        key="universal_search",
        title="Universal Search",
        group=None,
        phase=2,
        status=_P,
        summary="One input for every indicator type, with automatic classification.",
        capabilities=(
            "Classification of 24 input types with validation and normalisation",
            "Ambiguous input shown as candidate classifications",
            "Collection plan preview with provider selection",
            "Search history and saved searches",
        ),
    ),
    Feature(
        key="investigations",
        title="Investigations",
        group=None,
        phase=3,
        status=_P,
        summary="Case management: every investigation is an independent case.",
        capabilities=(
            "Create, duplicate, archive, reopen and compare cases",
            "Scope, members and permissions per case",
            "Notes, findings, evidence and task history",
            "Workspace tabs: overview, entities, results, graph, timeline, evidence, "
            "notes, tasks, reports, activity",
        ),
    ),
    Feature(
        key="identity",
        title="Identity Intelligence",
        group="Intelligence",
        phase=4,
        status=_P,
        summary="Email, phone number and username intelligence from public sources.",
        capabilities=(
            "Email: syntax, MX, SPF, DKIM, DMARC, domain reputation, authorised breach checks",
            "Phone: E.164 validation, region, number type, range-allocation carrier metadata",
            "Username: public profile discovery as candidate associations",
            "No mailbox access, subscriber records, tracking or private-account access",
        ),
    ),
    Feature(
        key="infrastructure",
        title="Infrastructure Intelligence",
        group="Intelligence",
        phase=4,
        status=_P,
        summary="Domain and IP address intelligence.",
        capabilities=(
            "DNS records, RDAP/WHOIS, nameservers, certificate transparency",
            "Subdomain discovery from public sources",
            "ASN, prefix, reverse DNS, hosting and approximate geolocation",
            "Lookalike and typosquatting detection",
        ),
    ),
    Feature(
        key="internet_assets",
        title="Internet Asset Intelligence",
        group="Intelligence",
        phase=5,
        status=_P,
        summary="Internet-exposed hosts and services from asset intelligence providers.",
        capabilities=(
            "Shodan, Censys, FOFA, ZoomEye, Netlas and ONYPHE through official APIs",
            "Ports, banners, certificates and software fingerprints",
            "Provider comparison and duplicate observation detection",
            "Exposure prioritisation with the evidence shown",
        ),
    ),
    Feature(
        key="network_topology",
        title="Network Topology",
        group="Intelligence",
        phase=8,
        status=_P,
        summary="Public infrastructure maps and authorised internal network discovery.",
        capabilities=(
            "Public infrastructure visualisation",
            "Authorised internal discovery inside an approved scope only",
            "Device inventory, segments and path views",
            "Edges drawn only where network evidence supports them",
        ),
    ),
    Feature(
        key="threat",
        title="Threat Intelligence",
        group="Intelligence",
        phase=6,
        status=_P,
        summary="Reputation and indicator enrichment for IPs, domains, URLs and file hashes.",
        capabilities=(
            "VirusTotal, AbuseIPDB, GreyNoise, OTX, URLhaus, ThreatFox, MalwareBazaar",
            "Indicator enrichment and reputation history",
            "MITRE ATT&CK mapping and STIX 2.1 export",
            "Submitted files are never executed",
        ),
    ),
    Feature(
        key="social_media",
        title="Social and Media Intelligence",
        group="Intelligence",
        phase=9,
        status=_P,
        summary="Public profiles, organisations, news and events.",
        capabilities=(
            "Public profile and page metadata through official APIs",
            "Organisation profiles from public registries and filings",
            "News, press releases and event timelines",
            "Nothing behind a login or privacy setting is collected",
        ),
    ),
    Feature(
        key="image_document",
        title="Image and Document Intelligence",
        group="Intelligence",
        phase=9,
        status=_P,
        summary="Metadata, hashes and text from images and documents you supply.",
        capabilities=(
            "EXIF and file metadata, cryptographic and perceptual hashes",
            "Text extraction and OCR for PDF, Office and image files",
            "URL, email and domain extraction",
            "Safe parsing with size limits; similarity is never proof of identity",
        ),
    ),
    Feature(
        key="geospatial",
        title="Geospatial Intelligence",
        group="Intelligence",
        phase=9,
        status=_P,
        summary="Map-based exploration of location evidence.",
        capabilities=(
            "Interactive map with layers and clustering",
            "Evidence-linked markers with approximate-location warnings",
            "Time-based filtering",
            "No live tracking",
        ),
    ),
    Feature(
        key="software_supply_chain",
        title="Software and Supply Chain",
        group="Intelligence",
        phase=6,
        status=_P,
        summary="Repositories, packages, dependencies and SBOMs.",
        capabilities=(
            "Public repository and package metadata",
            "SBOM ingestion and dependency vulnerability mapping",
            "Licence and release history",
            "Secret detection on authorised material only, always redacted",
        ),
    ),
    Feature(
        key="vulnerability",
        title="Vulnerability Intelligence",
        group="Intelligence",
        phase=6,
        status=_P,
        summary="CVE, CVSS, CWE, KEV and EPSS with source links.",
        capabilities=(
            "NVD, CISA KEV, FIRST EPSS, MITRE CWE and OSV",
            "Affected-product relationships validated by version and evidence",
            "Prioritisation with the scoring method shown",
            "Remediation references",
        ),
    ),
    Feature(
        key="relationship_graph",
        title="Relationship Graph",
        group="Analysis",
        phase=7,
        status=_P,
        summary="One entity and relationship graph shared by every module.",
        capabilities=(
            "Evidence-linked edges with distinct styles per verification status",
            "Filters by entity type, source, confidence and time",
            "Path analysis, annotations and snapshots",
            "Export to PNG, SVG, JSON, GraphML and CSV",
        ),
    ),
    Feature(
        key="historical",
        title="Historical Intelligence",
        group="Analysis",
        phase=11,
        status=_P,
        summary="How entities changed over time.",
        capabilities=(
            "Historical DNS, certificates and website snapshots",
            "First seen, last seen and change detection",
            "Snapshot comparison",
            "Evidence-backed digital footprint history",
        ),
    ),
    Feature(
        key="ai_investigation",
        title="AI Investigation Center",
        group="Analysis",
        phase=10,
        status=_P,
        summary="Tool-based AI assistance with approval gates and evidence citations.",
        capabilities=(
            "Lead orchestrator with specialist, verification and reporting agents",
            "Local and cloud models; local-only mode",
            "Every tool call permission-checked, approved where needed and recorded",
            "Unsupported claims are flagged, never presented as findings",
        ),
    ),
    Feature(
        key="monitoring",
        title="Monitoring and Alerts",
        group="Operations",
        phase=11,
        status=_P,
        summary="Scheduled checks on watched indicators with change alerts.",
        capabilities=(
            "Watchlists for domains, IPs, ASNs, certificates, brands and repositories",
            "Change detection with severity, explanation and evidence",
            "Acknowledgement and suppression",
            "Desktop, email and webhook notifications",
        ),
    ),
    Feature(
        key="reports_evidence",
        title="Reports and Evidence",
        group="Operations",
        phase=13,
        status=_P,
        summary="Evidence explorer and professional report generation.",
        capabilities=(
            "Evidence explorer with raw and normalised views (Phase 3)",
            "Report templates and builder",
            "PDF, HTML, JSON, CSV and STIX export",
            "Verified findings kept separate from hypotheses",
        ),
    ),
    Feature(
        key="integrations",
        title="Integrations",
        group="Platform",
        phase=5,
        status=FeatureStatus.PARTIAL,
        summary="Provider control centre.",
        capabilities=(
            "Catalogue of planned data sources and tools",
            "Credential configuration, health and quota per provider (Phase 5)",
            "Usage and cost tracking (Phase 5)",
        ),
        limitations=(
            "Only the catalogue is available. No provider integration is implemented "
            "yet, so no provider can be configured or tested."
        ),
    ),
    Feature(
        key="administration",
        title="Administration and Settings",
        group="Platform",
        phase=1,
        status=FeatureStatus.AVAILABLE,
        summary="Users, roles, audit trail, system status and your account.",
        capabilities=(
            "User accounts and role assignment",
            "Audit trail viewer",
            "System and service status",
            "Password, sessions and theme for your own account",
        ),
    ),
)

_BY_KEY = {feature.key: feature for feature in FEATURES}


def get_feature(key: str) -> Feature:
    return _BY_KEY[key]


def feature_counts() -> dict[str, int]:
    counts = {status.value: 0 for status in FeatureStatus}
    for feature in FEATURES:
        counts[feature.status.value] += 1
    return counts


@dataclass(frozen=True, slots=True)
class PlannedMetric:
    """A dashboard metric whose backing module does not exist yet."""

    key: str
    label: str
    phase: int


# Dashboard metrics named in the brief (section 13.3) that have no data source
# until their module is built. They are reported as unavailable, never as zero.
PLANNED_DASHBOARD_METRICS: tuple[PlannedMetric, ...] = (
    PlannedMetric("investigations_total", "Total investigations", 3),
    PlannedMetric("investigations_active", "Active investigations", 3),
    PlannedMetric("findings_recent", "Recent findings", 3),
    PlannedMetric("findings_verified", "Verified findings", 7),
    PlannedMetric("reviews_pending", "Pending reviews", 7),
    PlannedMetric("monitored_assets", "Monitored assets", 11),
    PlannedMetric("alerts_recent", "Recent alerts", 11),
    PlannedMetric("provider_quota", "Provider usage and quota", 5),
)
