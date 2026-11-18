"""Software packages and CVE identifiers."""

from __future__ import annotations

import re
import urllib.parse
from datetime import UTC, datetime

from omniosint.indicators.model import Candidate, candidate
from omniosint.indicators.types import IndicatorType

_CVE_RE = re.compile(
    r"^CVE[-_\u2010-\u2015](?P<year>\d{4})[-_\u2010-\u2015](?P<number>\d{4,7})$", re.IGNORECASE
)

# Package URL types (purl-spec) and the ecosystem names people type.
PURL_TYPES = frozenset(
    {
        "alpm", "apk", "bitbucket", "bitnami", "cargo", "cocoapods", "composer", "conan",
        "conda", "cpan", "cran", "deb", "docker", "gem", "generic", "github", "golang",
        "hackage", "hex", "huggingface", "luarocks", "maven", "mlflow", "npm", "nuget",
        "oci", "pub", "pypi", "qpkg", "rpm", "swid", "swift",
    }
)  # fmt: skip
_ECOSYSTEM_ALIASES = {
    "npm": "npm",
    "pypi": "pypi",
    "pip": "pypi",
    "python": "pypi",
    "gem": "gem",
    "rubygems": "gem",
    "cargo": "cargo",
    "crates": "cargo",
    "crates.io": "cargo",
    "go": "golang",
    "golang": "golang",
    "maven": "maven",
    "nuget": "nuget",
    "composer": "composer",
    "packagist": "composer",
    "hex": "hex",
    "pub": "pub",
    "cocoapods": "cocoapods",
    "conda": "conda",
    "cran": "cran",
    "hackage": "hackage",
    "swift": "swift",
}
_ECOSYSTEM_NAMES = {
    "npm": "npm",
    "pypi": "PyPI",
    "gem": "RubyGems",
    "cargo": "crates.io",
    "golang": "Go modules",
    "maven": "Maven",
    "nuget": "NuGet",
    "composer": "Packagist",
    "hex": "Hex",
    "pub": "pub.dev",
    "cocoapods": "CocoaPods",
    "conda": "conda",
    "cran": "CRAN",
    "hackage": "Hackage",
    "swift": "Swift packages",
}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~+-]{0,213}$")
_MAVEN_RE = re.compile(
    r"^(?P<group>[A-Za-z0-9_.-]+):(?P<artifact>[A-Za-z0-9_.-]+)(?::(?P<version>[A-Za-z0-9_.+-]+))?$"
)
_SCOPED_NPM_RE = re.compile(
    r"^@(?P<scope>[a-z0-9][a-z0-9._-]*)/(?P<name>[a-z0-9][a-z0-9._-]*)(?:@(?P<version>[^\s@/]+))?$"
)
_ECOSYSTEM_RE = re.compile(r"^(?P<ecosystem>[A-Za-z.]+)[:/](?P<rest>\S+)$")
_GO_MODULE_RE = re.compile(
    r"^(?P<host>[a-z0-9.-]+\.[a-z]{2,})/(?P<path>[A-Za-z0-9._~/-]+?)(?:@(?P<version>v[\w.+-]+))?$"
)


def parse_cve(text: str) -> list[Candidate]:
    match = _CVE_RE.match(text.strip())
    if not match:
        return []
    year, number = int(match["year"]), match["number"]
    notes: list[str] = []
    rank = "strong"
    current = datetime.now(UTC).year
    if year < 1999 or year > current + 1:
        notes.append(f"CVE identifiers start in 1999; {year} is outside the possible range.")
        rank = "weak"
    value = f"CVE-{year}-{number}"
    return [
        candidate(
            IndicatorType.CVE,
            value,
            rank=rank,  # type: ignore[arg-type]
            reason="A CVE identifier.",
            notes=notes,
            details={"year": year, "sequence": int(number)},
        )
    ]


def _normalize_name(ecosystem: str, name: str) -> str:
    if ecosystem == "pypi":
        # PEP 503 normalisation.
        return re.sub(r"[-_.]+", "-", name).lower()
    if ecosystem in ("npm", "cargo", "gem", "hex", "pub", "composer", "nuget"):
        return name.lower()
    return name


def _purl(ecosystem: str, namespace: str | None, name: str, version: str | None) -> str:
    parts = ["pkg:", ecosystem, "/"]
    if namespace:
        parts += [urllib.parse.quote(namespace, safe="/@"), "/"]
    parts.append(urllib.parse.quote(name, safe=""))
    if version:
        parts += ["@", urllib.parse.quote(version, safe="")]
    return "".join(parts)


def _package(
    ecosystem: str | None,
    namespace: str | None,
    name: str,
    version: str | None,
    *,
    rank: str,
    reason: str,
    notes: list[str] | None = None,
) -> Candidate:
    if ecosystem:
        normalized = _normalize_name(ecosystem, name)
        namespace_norm = (
            namespace.lower() if namespace and ecosystem in ("npm", "composer") else namespace
        )
        value = _purl(ecosystem, namespace_norm, normalized, version)
        label = f"{namespace + '/' if namespace else ''}{name}"
    else:
        value = name.lower()
        label = name
    details: dict[str, object] = {
        "ecosystem": ecosystem,
        "ecosystem_name": _ECOSYSTEM_NAMES.get(ecosystem or "", ecosystem),
        "namespace": namespace,
        "name": name,
        "version": version,
    }
    return candidate(
        IndicatorType.PACKAGE,
        value,
        display=f"{label}@{version}" if version else label,
        rank=rank,  # type: ignore[arg-type]
        reason=reason,
        notes=notes or [],
        details=details,
    )


def parse_purl(text: str) -> list[Candidate]:
    value = text.strip()
    if not value.lower().startswith("pkg:"):
        return []
    body = value[4:].lstrip("/")
    body, _, _subpath = body.partition("#")
    body, _, _qualifiers = body.partition("?")
    kind, _, rest = body.partition("/")
    kind = kind.lower()
    if kind not in PURL_TYPES or not rest:
        return []
    rest, _, version = rest.partition("@") if not rest.startswith("@") else ("", "", "")
    if not rest:
        # npm scopes are written %40scope in a purl; a literal @ is accepted too.
        scoped = body.split("/", 1)[1]
        name_part, _, version = (
            scoped.rpartition("@") if scoped.count("@") > 1 else (scoped, "", "")
        )
        rest = name_part
    segments = [urllib.parse.unquote(segment) for segment in rest.split("/") if segment]
    if not segments:
        return []
    name = segments[-1]
    namespace = "/".join(segments[:-1]) or None
    return [
        _package(
            kind,
            namespace,
            name,
            urllib.parse.unquote(version) or None,
            rank="strong",
            reason="A package URL (purl).",
        )
    ]


def parse_package(text: str) -> list[Candidate]:
    value = text.strip()
    if not value or any(char.isspace() for char in value):
        return []
    if value.lower().startswith("pkg:"):
        return parse_purl(value)
    scoped = _SCOPED_NPM_RE.match(value)
    if scoped:
        return [
            _package(
                "npm",
                "@" + scoped["scope"],
                scoped["name"],
                scoped["version"],
                rank="strong",
                reason="A scoped npm package.",
            )
        ]
    ecosystem_match = _ECOSYSTEM_RE.match(value)
    if ecosystem_match:
        ecosystem = _ECOSYSTEM_ALIASES.get(ecosystem_match["ecosystem"].lower())
        rest = ecosystem_match["rest"]
        if ecosystem is not None and "://" not in value:
            if ecosystem == "maven":
                maven = _MAVEN_RE.match(rest)
                if maven:
                    return [
                        _package(
                            "maven",
                            maven["group"],
                            maven["artifact"],
                            maven["version"],
                            rank="strong",
                            reason="A Maven artifact.",
                        )
                    ]
                return []
            name, _, version = (
                rest.rpartition("@")
                if rest.count("@") and not rest.startswith("@")
                else (rest, "", "")
            )
            namespace = None
            if ecosystem == "golang" or "/" in name:
                namespace, _, name = name.rpartition("/")
            if name and _NAME_RE.match(name):
                return [
                    _package(
                        ecosystem,
                        namespace or None,
                        name,
                        version or None,
                        rank="strong",
                        reason=f"A {_ECOSYSTEM_NAMES[ecosystem]} package.",
                    )
                ]
            return []
    maven = _MAVEN_RE.match(value)
    if maven and maven["version"] and "." in maven["group"]:
        return [
            _package(
                "maven",
                maven["group"],
                maven["artifact"],
                maven["version"],
                rank="plausible",
                reason="Written like Maven coordinates (group:artifact:version).",
            )
        ]
    go = _GO_MODULE_RE.match(value)
    if go and "/" in go["path"] and not value.startswith(("http:", "https:")):
        module = f"{go['host']}/{go['path']}"
        namespace, _, name = module.rpartition("/")
        return [
            _package(
                "golang",
                namespace,
                name,
                go["version"],
                rank="plausible",
                reason="Written like a Go module path.",
            )
        ]
    if (
        _NAME_RE.match(value)
        and not value.isdigit()
        and value == value.lower()
        and "." not in value
    ):
        return [
            _package(
                None,
                None,
                value,
                None,
                rank="weak",
                reason="Could be the name of a software package.",
                notes=["Add the ecosystem (npm:, pypi:, cargo: ...) to identify the package."],
            )
        ]
    return []
