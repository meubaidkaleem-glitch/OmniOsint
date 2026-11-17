"""The feature registry and the provider catalogue must stay honest."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from omniosint.core.errors import ConfigurationError
from omniosint.core.features import (
    FEATURES,
    PHASES,
    PLANNED_DASHBOARD_METRICS,
    FeatureStatus,
    feature_counts,
)
from omniosint.providers.catalog import CATEGORY_LABELS, load_catalogue, read_catalogue

# The twenty sections of the brief, in order (docs/UI_NAVIGATION.md).
NAVIGATION_KEYS = [
    "dashboard",
    "universal_search",
    "investigations",
    "identity",
    "infrastructure",
    "internet_assets",
    "network_topology",
    "threat",
    "social_media",
    "image_document",
    "geospatial",
    "software_supply_chain",
    "vulnerability",
    "relationship_graph",
    "historical",
    "ai_investigation",
    "monitoring",
    "reports_evidence",
    "integrations",
    "administration",
]


def test_feature_registry_covers_the_navigation() -> None:
    assert [feature.key for feature in FEATURES] == NAVIGATION_KEYS


def test_features_reference_real_phases() -> None:
    for feature in FEATURES:
        assert feature.phase in PHASES
        assert feature.capabilities, feature.key


def test_only_built_features_are_marked_available() -> None:
    # Phase 1 delivers administration (complete) and partial dashboard and
    # integrations pages. Everything else must be reported as planned.
    built = {f.key: f.status for f in FEATURES if f.status is not FeatureStatus.PLANNED}
    assert built == {
        "dashboard": FeatureStatus.PARTIAL,
        "integrations": FeatureStatus.PARTIAL,
        "administration": FeatureStatus.AVAILABLE,
    }
    for feature in FEATURES:
        if feature.status is FeatureStatus.PARTIAL:
            assert feature.limitations, f"{feature.key} must state its limitations"
    assert feature_counts() == {"available": 1, "partial": 2, "planned": 17}


def test_planned_dashboard_metrics_are_in_future_phases() -> None:
    keys = [metric.key for metric in PLANNED_DASHBOARD_METRICS]
    assert len(keys) == len(set(keys))
    assert all(metric.phase > 1 for metric in PLANNED_DASHBOARD_METRICS)


def test_provider_catalogue_is_valid() -> None:
    catalogue = load_catalogue()
    assert len(catalogue.providers) >= 70
    ids = [provider.id for provider in catalogue.providers]
    assert len(ids) == len(set(ids))
    for provider in catalogue.providers:
        assert provider.category in CATEGORY_LABELS
        if provider.docs_url:
            assert provider.docs_url.startswith("https://") or provider.docs_url.startswith(
                "http://www.net-snmp.org"
            ), provider.id
        if provider.status == "excluded":
            assert provider.notes, f"{provider.id}: an exclusion must say why"


def test_no_provider_claims_to_be_available_without_an_adapter() -> None:
    # No adapter exists in Phase 1. When the first one lands, this test is
    # updated together with it.
    assert load_catalogue().status_counts()["available"] == 0


def test_brief_named_providers_are_catalogued() -> None:
    catalogue = load_catalogue()
    for provider_id in (
        "shodan",
        "censys",
        "fofa",
        "zoomeye",
        "netlas",
        "onyphe",
        "virustotal",
        "abuseipdb",
        "greynoise",
        "securitytrails",
        "urlscan",
        "nvd",
        "cisa_kev",
        "epss",
        "osv",
    ):
        assert catalogue.get(provider_id) is not None, provider_id


def _write_catalogue(path: Path, providers: list[dict[str, object]]) -> Path:
    path.write_text(yaml.safe_dump({"version": 1, "providers": providers}), encoding="utf-8")
    return path


ENTRY = {
    "id": "example",
    "name": "Example",
    "category": "threat",
    "access": "free",
    "auth": "none",
    "phase": 6,
    "status": "planned",
}


def test_catalogue_rejects_duplicates(tmp_path: Path) -> None:
    path = _write_catalogue(tmp_path / "p.yaml", [ENTRY, ENTRY])
    with pytest.raises(ConfigurationError, match="duplicate"):
        read_catalogue(path)


@pytest.mark.parametrize(
    "change",
    [{"category": "nope"}, {"status": "done"}, {"docs_url": "ftp://x"}, {"surprise": 1}],
)
def test_catalogue_rejects_invalid_entries(tmp_path: Path, change: dict[str, object]) -> None:
    path = _write_catalogue(tmp_path / "p.yaml", [{**ENTRY, **change}])
    with pytest.raises(ConfigurationError, match="invalid"):
        read_catalogue(path)
