"""Domains, URLs, email addresses, repository and social profile URLs."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from functools import cache

import idna
from email_validator import EmailNotValidError, ValidatedEmail, validate_email
from publicsuffixlist import PublicSuffixList

from omniosint.indicators.model import Candidate, Rank, candidate
from omniosint.indicators.network import parse_address
from omniosint.indicators.types import EntityType, IndicatorType
from omniosint.net.addresses import classify_address

_LABEL_RE = re.compile(r"^(?!-)[a-z0-9_-]{1,63}(?<!-)$")
_SCHEMES = frozenset({"http", "https", "ftp", "ftps", "ws", "wss"})
_DEFAULT_PORTS = {"http": 80, "https": 443, "ftp": 21, "ftps": 990, "ws": 80, "wss": 443}
_PATH_SAFE = "/%:@!$&'()*+,;=-._~"
_QUERY_SAFE = "/%:@!$&'()*+,;=-._~?"

# Top-level domains that are also common file extensions: "readme.md" is a
# valid domain name, but more often a file name.
_FILE_EXTENSION_TLDS = frozenset({"zip", "mov", "md", "sh", "py", "rs", "pl", "ps", "app"})

_SPECIAL_USE: dict[str, str] = {
    "local": "A multicast DNS name on a local network (RFC 6762), not an Internet domain.",
    "localhost": "Always the local computer (RFC 6761).",
    "test": "Reserved for testing (RFC 2606); never an Internet domain.",
    "example": "Reserved for examples (RFC 2606); never an Internet domain.",
    "invalid": "Reserved as an always-invalid name (RFC 2606).",
    "internal": "Reserved for private networks (ICANN, 2024); not an Internet domain.",
    "alt": "Reserved for alternative name systems (RFC 9476).",
    "onion": (
        "A Tor onion service (RFC 7686): reachable only through Tor, which OmniOSINT does not use."
    ),
    "lan": "Commonly used inside private networks; not a public top-level domain.",
    "home": "Commonly used inside private networks; not a public top-level domain.",
    "corp": "Commonly used inside private networks; not a public top-level domain.",
    "intranet": "Commonly used inside private networks; not a public top-level domain.",
}


@cache
def _psl() -> PublicSuffixList:
    # accept_unknown=False: an unknown top-level label is reported, not assumed.
    return PublicSuffixList(accept_unknown=False)


def normalize_hostname(host: str) -> tuple[str, str] | None:
    """The ASCII (A-label) and Unicode forms of a host name, or ``None``."""
    name = host.strip().rstrip(".")
    if not name or len(name) > 253 or ".." in name or name.startswith("."):
        return None
    try:
        ascii_name = idna.encode(name, uts46=True, transitional=False).decode("ascii")
    except (idna.IDNAError, UnicodeError, ValueError):
        # Underscores are valid in DNS labels (service records) but not in IDNA.
        lowered = name.lower()
        if not lowered.isascii() or not all(_LABEL_RE.fullmatch(p) for p in lowered.split(".")):
            return None
        ascii_name = lowered
    if len(ascii_name) > 253 or not all(_LABEL_RE.fullmatch(p) for p in ascii_name.split(".")):
        return None
    try:
        unicode_name = idna.decode(ascii_name)
    except (idna.IDNAError, UnicodeError, ValueError):
        unicode_name = ascii_name
    return ascii_name, unicode_name


@dataclass(frozen=True, slots=True)
class DomainFacts:
    ascii: str
    unicode: str
    public_suffix: str | None
    registrable: str | None
    note: str | None

    @property
    def is_public(self) -> bool:
        return self.public_suffix is not None and self.registrable is not None

    @property
    def is_subdomain(self) -> bool:
        return self.registrable is not None and self.registrable != self.ascii

    def details(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ascii": self.ascii,
            "public_suffix": self.public_suffix,
            "registrable_domain": self.registrable,
            "subdomain": self.is_subdomain,
        }
        if self.unicode != self.ascii:
            result["unicode"] = self.unicode
        return result


def domain_facts(host: str) -> DomainFacts | None:
    normalized = normalize_hostname(host)
    if normalized is None:
        return None
    ascii_name, unicode_name = normalized
    labels = ascii_name.split(".")
    if len(labels) < 2 or labels[-1].isdigit() or not re.search(r"[a-z]", labels[-1]):
        return None
    top = labels[-1]
    second = ".".join(labels[-2:])
    note = _SPECIAL_USE.get(top)
    if second == "home.arpa":
        note = "A residential home network name (RFC 8375), not an Internet domain."
    suffix = _psl().publicsuffix(ascii_name)
    registrable = _psl().privatesuffix(ascii_name) if suffix else None
    if suffix is None and note is None:
        note = f".{top} is not a public top-level domain: an internal name, or a typing error."
    elif suffix is not None and registrable is None:
        note = f"{ascii_name} is a public suffix (like co.uk): names are registered under it."
    return DomainFacts(ascii_name, unicode_name, suffix, registrable, note)


def parse_domain(text: str) -> list[Candidate]:
    value = text.strip()
    if any(char in value for char in "/:@ \\?#[]") or "." not in value.strip("."):
        return []
    facts = domain_facts(value)
    if facts is None:
        return []
    notes = [facts.note] if facts.note else []
    labels = facts.ascii.split(".")
    rank: Rank
    if not facts.is_public:
        rank = "weak"
        reason = "Shaped like a host name, but not a public Internet domain."
    elif labels[-1] in _FILE_EXTENSION_TLDS and len(labels) == 2:
        rank = "plausible"
        reason = "A valid domain name."
        notes.append(
            f".{labels[-1]} is also a common file extension; check this is not a file name."
        )
    elif labels[-1] == "onion":
        rank = "plausible"
        reason = "A Tor onion service name."
    else:
        rank = "strong"
        reason = (
            f"A host name under the registered domain {facts.registrable}."
            if facts.is_subdomain
            else "A registrable domain name."
        )
    return [
        candidate(
            IndicatorType.DOMAIN,
            facts.ascii,
            display=facts.unicode,
            rank=rank,
            reason=reason,
            notes=notes,
            details=facts.details(),
            entity_type=EntityType.SUBDOMAIN if facts.is_subdomain else EntityType.DOMAIN,
        )
    ]


# --------------------------------------------------------------------------- URLs
@dataclass(frozen=True, slots=True)
class ParsedUrl:
    canonical: str
    scheme: str
    host: str  # ASCII host, IPv6 without brackets
    host_type: str  # "domain", "ipv4" or "ipv6"
    port: int | None
    path: str
    query: str
    notes: tuple[str, ...]
    assumed_scheme: bool
    domain: DomainFacts | None

    def details(self) -> dict[str, object]:
        result: dict[str, object] = {
            "scheme": self.scheme,
            "host": self.host,
            "host_type": self.host_type,
            "path": self.path,
        }
        if self.port is not None:
            result["port"] = self.port
        if self.query:
            result["query"] = self.query
        if self.domain is not None:
            result["registrable_domain"] = self.domain.registrable
        return result


_HOST_PATH_RE = re.compile(r"^[^\s/:@]+\.[^\s/:@]+(?::\d{1,5})?/\S*$")


def split_url(text: str) -> ParsedUrl | None:
    value = text.strip()
    if not value or any(char.isspace() for char in value):
        return None
    notes: list[str] = []
    assumed = False
    if "://" in value:
        scheme = value.split("://", 1)[0].lower()
        if scheme not in _SCHEMES:
            return None
    elif value.lower().startswith("www.") or (
        _HOST_PATH_RE.match(value) and re.search(r"[A-Za-z]", value.split("/", 1)[0])
    ):
        value = "https://" + value
        assumed = True
        notes.append("No scheme was given; https is assumed.")
    else:
        return None
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = parts.hostname
    if not host:
        return None
    if parts.username is not None or parts.password is not None:
        notes.append("The user name or password in the address was removed; it is never stored.")
    address = parse_address(host)
    domain: DomainFacts | None = None
    if address is not None:
        host_type = f"ipv{address.version}"
        host_ascii = address.compressed
        info = classify_address(address)
        if info.note:
            notes.append(info.note)
        netloc = f"[{host_ascii}]" if address.version == 6 else host_ascii
    else:
        normalized = normalize_hostname(host)
        if normalized is None:
            return None
        host_ascii = normalized[0]
        host_type = "domain"
        domain = domain_facts(host_ascii)
        if domain is None:
            # A single-label host such as "intranet".
            notes.append("The host has no domain suffix: an internal name.")
        elif domain.note:
            notes.append(domain.note)
        netloc = host_ascii
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{netloc}:{port}"
    else:
        port = None
    path = urllib.parse.quote(parts.path or "/", safe=_PATH_SAFE)
    query = urllib.parse.quote(parts.query, safe=_QUERY_SAFE)
    if parts.fragment:
        notes.append("The fragment after # is never sent to servers and was dropped.")
    canonical = urllib.parse.urlunsplit((scheme, netloc, path, query, ""))
    return ParsedUrl(
        canonical, scheme, host_ascii, host_type, port, path, query, tuple(notes), assumed, domain
    )


def parse_url(text: str) -> list[Candidate]:
    parsed = split_url(text)
    if parsed is None:
        return []
    results = [
        candidate(
            IndicatorType.URL,
            parsed.canonical,
            rank="plausible" if parsed.assumed_scheme else "strong",
            reason="A web address."
            if not parsed.assumed_scheme
            else "A host and path without a scheme.",
            notes=parsed.notes,
            details=parsed.details(),
        )
    ]
    repository = repository_from_url(parsed)
    if repository is not None:
        results.append(repository)
    profile = social_profile_from_url(parsed)
    if profile is not None:
        results.append(profile)
    return results


# ---------------------------------------------------------------------- repositories
_GITHUB_RESERVED = frozenset(
    {
        "about", "account", "apps", "blog", "collections", "contact", "copilot",
        "customer-stories", "codespaces", "dashboard", "discussions", "enterprise",
        "events", "explore", "features", "github", "issues", "join", "login", "logout",
        "marketplace", "mobile", "new", "nonprofit", "notifications", "organizations",
        "orgs", "partners", "pricing", "pulls", "readme", "resources", "search",
        "security", "settings", "signup", "site", "solutions", "sponsors", "stars",
        "team", "topics", "trending", "users", "watching",
    }
)  # fmt: skip
_OWNER_REPO_HOSTS = {
    "github.com": "GitHub",
    "bitbucket.org": "Bitbucket",
    "codeberg.org": "Codeberg",
    "gitea.com": "Gitea",
    "git.sr.ht": "SourceHut",
}
_CASE_INSENSITIVE_HOSTS = frozenset({"github.com", "gitlab.com", "bitbucket.org"})
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.~-]{1,100}$")
_SSH_RE = re.compile(
    r"^(?P<user>[\w.-]+)@(?P<host>[A-Za-z0-9.-]+):(?P<path>[\w./~-]+?)(?:\.git)?/?$"
)


def _strip_host(host: str) -> str:
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix):
            return host[len(prefix) :]
    return host


def _repository(host: str, segments: list[str], platform: str, *, rank: Rank) -> Candidate:
    path = "/".join(segment.removesuffix(".git") for segment in segments)
    canonical = f"https://{host}/{path}"
    if host in _CASE_INSENSITIVE_HOSTS:
        canonical = canonical.lower()
    owner = segments[0].lstrip("~")
    return candidate(
        IndicatorType.REPOSITORY_URL,
        canonical,
        display=f"https://{host}/{path}",
        rank=rank,
        reason=f"A {platform} repository.",
        details={"platform": platform, "host": host, "owner": owner, "path": path},
    )


def repository_from_url(parsed: ParsedUrl) -> Candidate | None:
    host = _strip_host(parsed.host)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if host in _OWNER_REPO_HOSTS and len(segments) >= 2:
        if host == "github.com" and segments[0].lower() in _GITHUB_RESERVED:
            return None
        if not all(_SEGMENT_RE.match(segment) for segment in segments[:2]):
            return None
        return _repository(host, segments[:2], _OWNER_REPO_HOSTS[host], rank="strong")
    if host == "gitlab.com" and len(segments) >= 2:
        # Groups nest; "/-/" starts the project's own pages.
        project = segments[: segments.index("-")] if "-" in segments else segments
        if len(project) >= 2 and all(_SEGMENT_RE.match(segment) for segment in project):
            return _repository(host, project, "GitLab", rank="strong")
        return None
    if host == "dev.azure.com" and len(segments) >= 4 and segments[2] == "_git":
        return _repository(host, segments[:4], "Azure Repos", rank="strong")
    if host == "sourceforge.net" and len(segments) >= 2 and segments[0] == "projects":
        return _repository(host, segments[:2], "SourceForge", rank="strong")
    if parsed.path.endswith(".git") and len(segments) >= 2:
        return _repository(host, segments, "Git", rank="plausible")
    return None


def parse_ssh_repository(text: str) -> list[Candidate]:
    match = _SSH_RE.match(text.strip())
    if not match or "@" not in text or "://" in text:
        return []
    facts = domain_facts(match["host"])
    if facts is None:
        return []
    host = facts.ascii
    segments = [segment for segment in match["path"].split("/") if segment]
    if len(segments) < 2:
        return []
    platform = _OWNER_REPO_HOSTS.get(host) or ("GitLab" if host == "gitlab.com" else "Git")
    rank: Rank = "strong" if platform != "Git" else "plausible"
    result = _repository(host, segments, platform, rank=rank)
    notes = ("Written as an SSH clone address.",)
    return [result.model_copy(update={"notes": notes})]


# --------------------------------------------------------------------------- social
@dataclass(frozen=True, slots=True)
class Platform:
    id: str
    name: str
    hosts: frozenset[str]
    pattern: re.Pattern[str]
    reserved: frozenset[str] = frozenset()
    case_insensitive: bool = True


def _platform(
    id_: str, name: str, hosts: set[str], pattern: str, reserved: set[str] | None = None
) -> Platform:
    return Platform(id_, name, frozenset(hosts), re.compile(pattern), frozenset(reserved or ()))


_PLATFORMS: tuple[Platform, ...] = (
    _platform(
        "x", "X (Twitter)", {"x.com", "twitter.com"}, r"^/(?P<handle>[A-Za-z0-9_]{1,15})/?$",
        {"home", "explore", "search", "i", "settings", "login", "signup", "messages",
         "notifications", "intent", "share", "hashtag", "tos", "privacy"},
    ),
    _platform(
        "instagram", "Instagram", {"instagram.com"}, r"^/(?P<handle>[A-Za-z0-9._]{1,30})/?$",
        {"p", "reel", "reels", "explore", "accounts", "stories", "direct", "about", "legal"},
    ),
    _platform(
        "facebook", "Facebook", {"facebook.com", "fb.com"}, r"^/(?P<handle>[A-Za-z0-9.]{5,50})/?$",
        {"groups", "pages", "events", "watch", "marketplace", "login", "help", "policies",
         "gaming", "profile.php", "sharer", "share"},
    ),
    _platform(
        "linkedin", "LinkedIn", {"linkedin.com"},
        r"^/(?P<kind>in|company|school)/(?P<handle>[^/]{2,100})/?$",
    ),
    _platform(
        "github", "GitHub", {"github.com"},
        r"^/(?P<handle>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/?$", set(_GITHUB_RESERVED),
    ),
    _platform(
        "gitlab", "GitLab", {"gitlab.com"}, r"^/(?P<handle>[A-Za-z0-9_.-]{2,255})/?$",
        {"explore", "help", "users", "dashboard", "search", "projects", "groups", "admin"},
    ),
    _platform(
        "reddit", "Reddit", {"reddit.com", "old.reddit.com"},
        r"^/(?:u|user)/(?P<handle>[A-Za-z0-9_-]{3,20})/?$",
    ),
    _platform(
        "youtube", "YouTube", {"youtube.com"},
        r"^/(?:@(?P<handle>[A-Za-z0-9._-]{3,30})|channel/(?P<channel>UC[A-Za-z0-9_-]{22})|c/(?P<custom>[^/]{1,100})|user/(?P<legacy>[^/]{1,100}))/?$",
    ),
    _platform("tiktok", "TikTok", {"tiktok.com"}, r"^/@(?P<handle>[A-Za-z0-9._]{2,24})/?$"),
    _platform(
        "telegram", "Telegram", {"t.me", "telegram.me"}, r"^/(?P<handle>[A-Za-z0-9_]{5,32})/?$",
        {"joinchat", "s", "share", "addstickers", "proxy", "socks", "iv"},
    ),
    _platform("bluesky", "Bluesky", {"bsky.app"}, r"^/profile/(?P<handle>[^/]{3,253})/?$"),
    _platform("threads", "Threads", {"threads.net", "threads.com"},
              r"^/@(?P<handle>[A-Za-z0-9._]{1,30})/?$"),
    _platform("medium", "Medium", {"medium.com"}, r"^/@(?P<handle>[A-Za-z0-9._-]{1,50})/?$"),
    _platform("twitch", "Twitch", {"twitch.tv"}, r"^/(?P<handle>[A-Za-z0-9_]{4,25})/?$",
              {"directory", "downloads", "jobs", "p", "settings", "subscriptions", "videos"}),
    _platform("keybase", "Keybase", {"keybase.io"}, r"^/(?P<handle>[A-Za-z0-9_]{2,16})/?$",
              {"docs", "blog", "download", "team"}),
    _platform("vk", "VK", {"vk.com"}, r"^/(?P<handle>[A-Za-z0-9_.]{3,32})/?$",
              {"feed", "im", "groups", "search", "login", "settings", "about", "terms"}),
    _platform("steam", "Steam Community", {"steamcommunity.com"},
              r"^/(?:id/(?P<handle>[A-Za-z0-9_-]{2,32})|profiles/(?P<steamid>\d{17}))/?$"),
    _platform("soundcloud", "SoundCloud", {"soundcloud.com"}, r"^/(?P<handle>[a-z0-9_-]{3,25})/?$",
              {"discover", "stream", "search", "upload", "you", "pages", "charts"}),
    _platform("mastodon_social", "Mastodon", {"mastodon.social", "mastodon.online", "fosstodon.org",
                                               "infosec.exchange", "hachyderm.io"},
              r"^/@(?P<handle>[A-Za-z0-9_]{1,30})/?$"),
)  # fmt: skip
_HOSTS_TO_PLATFORM = {host: platform for platform in _PLATFORMS for host in platform.hosts}
_FEDIVERSE_PATH = re.compile(r"^/@(?P<handle>[A-Za-z0-9_]{1,30})/?$")


def social_profile_from_url(parsed: ParsedUrl) -> Candidate | None:
    if parsed.scheme not in ("http", "https"):
        return None
    host = _strip_host(parsed.host)
    platform = _HOSTS_TO_PLATFORM.get(host)
    if platform is None:
        if host == "news.ycombinator.com" and parsed.path == "/user":
            query = urllib.parse.parse_qs(parsed.query)
            name = (query.get("id") or [""])[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{2,15}", name):
                return _profile("hackernews", "Hacker News", host, name, parsed)
        match = _FEDIVERSE_PATH.match(parsed.path)
        if match and parsed.domain is not None and parsed.domain.is_public:
            result = _profile("fediverse", "Fediverse server", host, match["handle"], parsed)
            return result.model_copy(
                update={
                    "rank": "plausible",
                    "reason": "Shaped like a profile on a fediverse server (Mastodon and similar).",
                }
            )
        return None
    if platform.id == "facebook" and parsed.path == "/profile.php":
        identifier = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
        if identifier.isdigit():
            return _profile(platform.id, platform.name, host, identifier, parsed)
        return None
    match = platform.pattern.match(parsed.path)
    if not match:
        return None
    handle = next((value for value in match.groupdict().values() if value), None)
    if not handle or handle.lower() in platform.reserved:
        return None
    kind = match.groupdict().get("kind")
    return _profile(platform.id, platform.name, host, handle, parsed, kind=kind)


def _profile(
    platform_id: str,
    platform_name: str,
    host: str,
    handle: str,
    parsed: ParsedUrl,
    *,
    kind: str | None = None,
) -> Candidate:
    details: dict[str, object] = {
        "platform": platform_id,
        "platform_name": platform_name,
        "handle": handle,
        "host": host,
    }
    if kind:
        details["kind"] = kind
    notes = []
    if kind in ("company", "school"):
        notes.append("This is an organisation page, not a personal profile.")
    canonical = parsed.canonical.rstrip("/") if parsed.path != "/" else parsed.canonical
    return candidate(
        IndicatorType.SOCIAL_PROFILE_URL,
        canonical,
        rank="strong",
        reason=f"A public profile address on {platform_name}.",
        notes=notes,
        details=details,
    )


# --------------------------------------------------------------------------- email
_DISPLAY_NAME_RE = re.compile(r"^(?P<name>[^<>]*)<(?P<address>[^<>]+)>$")


def _validate(value: str) -> tuple[ValidatedEmail, bool] | None:
    try:
        return validate_email(value, check_deliverability=False), True
    except EmailNotValidError:
        pass
    try:
        return (
            validate_email(
                value, check_deliverability=False, globally_deliverable=False, test_environment=True
            ),
            False,
        )
    except EmailNotValidError:
        return None


def parse_email(text: str) -> list[Candidate]:
    value = text.strip()
    if value.lower().startswith("mailto:"):
        value = urllib.parse.unquote(value[7:].split("?", 1)[0])
    display = _DISPLAY_NAME_RE.match(value)
    if display:
        value = display["address"].strip()
    if value.count("@") != 1 or value.startswith("@") or any(char.isspace() for char in value):
        return []
    validated = _validate(value)
    if validated is None:
        return []
    result, public = validated
    notes: list[str] = []
    facts = domain_facts(result.ascii_domain)
    if not public:
        notes.append(
            "The domain is not an Internet domain, so the address cannot receive mail from outside."
        )
    if display:
        notes.append("The display name was removed.")
    notes.append("Compared without regard to letter case, as nearly all mail systems do.")
    details: dict[str, object] = {
        "local_part": result.local_part,
        "domain": result.ascii_domain,
        "registrable_domain": facts.registrable if facts else None,
    }
    if result.domain != result.ascii_domain:
        details["unicode_domain"] = result.domain
    return [
        candidate(
            IndicatorType.EMAIL,
            f"{result.local_part.lower()}@{result.ascii_domain}",
            display=result.normalized,
            rank="strong" if public else "weak",
            reason="A valid email address.",
            notes=notes,
            details=details,
        )
    ]
