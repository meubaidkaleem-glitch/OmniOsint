"""Provider catalogue.

The inventory of data sources and tools the platform is designed to integrate,
loaded from ``config/providers.yaml``. It is metadata only: no adapter is
implied by an entry being listed, and every entry states its real status.

Adapters, health checks and credentials arrive with the provider framework in
Phase 2 and the integrations in Phase 5 onward.
"""

from __future__ import annotations

from collections import Counter
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from omniosint.core.errors import PLANNED_MESSAGE, ConfigurationError
from omniosint.core.paths import default_config_dir

ProviderStatus = Literal["planned", "available", "excluded"]
ProviderAccess = Literal[
    "free",
    "free_key",
    "freemium",
    "paid",
    "self_hosted",
    "local_library",
    "local_tool",
    "none",
]
ProviderAuth = Literal["none", "api_key", "token", "account"]

CATEGORY_LABELS: dict[str, str] = {
    "internet_assets": "Internet asset intelligence",
    "threat": "Threat intelligence",
    "dns_domain": "DNS and domains",
    "web": "Web intelligence",
    "code": "Public code",
    "vulnerability": "Vulnerability and software",
    "network": "Network and IP data",
    "geospatial": "Geospatial",
    "corporate": "Corporate records",
    "research": "Research",
    "phone": "Phone",
    "email": "Email",
    "username": "Username",
    "social_news": "Social and news",
    "network_tools": "Authorised network discovery tools",
    "ai_models": "AI models",
}

ACCESS_LABELS: dict[str, str] = {
    "free": "Free",
    "free_key": "Free, key required",
    "freemium": "Limited free tier",
    "paid": "Paid",
    "self_hosted": "Your own instance",
    "local_library": "Built in (offline)",
    "local_tool": "Tool you install",
    "none": "No official API",
}

STATUS_MESSAGES: dict[str, str] = {
    "planned": PLANNED_MESSAGE,
    "available": "Available.",
    "excluded": "Excluded — see notes.",
}


class ProviderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{1,47}$")
    name: str = Field(min_length=1, max_length=96)
    category: str
    access: ProviderAccess
    auth: ProviderAuth
    docs_url: str = ""
    phase: int = Field(ge=1, le=14)
    status: ProviderStatus
    modules: tuple[str, ...] = ()
    # Sources this one derives its data from: they are not independent evidence.
    upstream: tuple[str, ...] = ()
    notes: str = ""

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in CATEGORY_LABELS:
            raise ValueError(f"unknown category {value!r}")
        return value

    @field_validator("docs_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("docs_url must be an http(s) URL or empty")
        return value

    @field_validator("notes")
    @classmethod
    def _single_line(cls, value: str) -> str:
        return " ".join(value.split())

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS[self.category]

    @property
    def access_label(self) -> str:
        return ACCESS_LABELS[self.access]

    @property
    def status_message(self) -> str:
        return STATUS_MESSAGES[self.status]


class ProviderCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    providers: tuple[ProviderEntry, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> ProviderCatalogue:
        duplicates = [
            key for key, count in Counter(p.id for p in self.providers).items() if count > 1
        ]
        if duplicates:
            raise ValueError(f"duplicate provider id(s): {', '.join(sorted(duplicates))}")
        known = {provider.id for provider in self.providers}
        for provider in self.providers:
            unknown = [source for source in provider.upstream if source not in known]
            if unknown or provider.id in provider.upstream:
                raise ValueError(
                    f"{provider.id}: unknown or circular upstream {unknown or [provider.id]}"
                )
        return self

    def get(self, provider_id: str) -> ProviderEntry | None:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        return None

    def status_counts(self) -> dict[str, int]:
        counts = {"planned": 0, "available": 0, "excluded": 0}
        for provider in self.providers:
            counts[provider.status] += 1
        return counts


def catalogue_path() -> Path:
    return default_config_dir() / "providers.yaml"


def read_catalogue(path: Path) -> ProviderCatalogue:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"The provider catalogue {path} could not be read: {exc}") from exc
    try:
        return ProviderCatalogue.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigurationError(f"The provider catalogue {path} is invalid: {problems}") from exc


@cache
def load_catalogue() -> ProviderCatalogue:
    return read_catalogue(catalogue_path())
