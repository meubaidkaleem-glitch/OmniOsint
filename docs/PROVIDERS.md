# Providers

How OmniOSINT integrates external data sources and tools, and the inventory of
what is planned.

**Current state: no provider integration is implemented.** The catalogue below
is the plan. In the interface and the CLI every entry is shown as
"Planned — integration not yet implemented." until its adapter exists and is
tested. The adapter framework is built in Phase 2 and the first integrations in
Phases 4 to 6.

## Principles

1. **Official access only.** An adapter uses the provider's documented API and
   authentication. A source with no official programmatic access is listed as
   excluded, not scraped.
2. **Nothing is assumed about an account.** Subscription tier, quota and endpoint
   eligibility are discovered at runtime where the provider exposes them, and
   stated as unknown where it does not.
3. **Free first, paid when justified.** The planner prefers free sources and
   cached results, estimates the cost of paid calls where it can, and asks for
   approval above a configured threshold.
4. **Every result is attributable.** The original response is kept, the
   normalised form never discards original values, and observation and
   collection times are recorded separately.
5. **Failure is a normal result.** Timeouts, quota exhaustion and malformed data
   are recorded on the job and shown with their real reason.
6. **Tools are not bundled.** Local tools are detected, version-checked and
   called through an adapter; installing one is always the user's decision.

## Adapter contract (Phase 2)

Each provider is an independent adapter implementing one interface. Intelligence
modules never call a provider API themselves; they ask the provider manager for
a capability.

```python
class IntelligenceProvider(Protocol):
    metadata: ProviderMetadata          # id, category, capabilities, cost model

    async def authenticate(self) -> AuthResult: ...
    async def health_check(self) -> HealthResult: ...
    async def get_quota(self) -> Quota | None: ...       # None when not exposed
    async def investigate(self, indicator: Indicator,
                          context: CollectionContext) -> RawResult: ...
    def normalize(self, raw: RawResult) -> list[Observation]: ...
    async def close(self) -> None: ...
```

`ProviderMetadata` declares, per capability: the indicator types it accepts,
whether the call is passive or active, whether it costs credits, the rate limit
and whether results may be cached and for how long.

What the framework supplies around every adapter, so adapters stay small:

| Concern | Supplied by the framework |
|---|---|
| HTTP client | One shared async client with timeouts and a destination policy (SSRF defence) |
| Rate limiting | Per-provider token bucket; state shared through Redis when configured |
| Retry | Bounded exponential backoff on retryable failures only |
| Circuit breaker | Stops calling a failing provider and reports it as unavailable |
| Pagination | Bounded page iteration with a per-job result cap |
| Cache | Keyed on provider, capability and normalised indicator, with a TTL |
| Query deduplication | Identical requests in flight are joined |
| Quota and cost | Usage recorded per call; estimates before paid calls |
| Credentials | Encrypted at rest; never returned by the API or written to logs |
| Evidence | Raw response stored once, content-addressed; observations linked to it |

## Execution strategy (Phase 2)

* Strategies: free-first (default), paid fallback, user-selected providers,
  explicit priority order.
* Parallel requests only where a provider permits them, within bounded
  concurrency.
* Incremental collection: what is already cached and fresh is not fetched again.
* A plan is shown before it runs. Anything active, or anything above the
  spending threshold, waits for approval.

## Testing (Phases 2, 5, 6)

* Routine tests use recorded responses and cover: valid, invalid, empty and
  partial results, authentication failure, quota exhaustion, rate limiting,
  timeouts, malformed data, pagination and outages.
* Live tests are opt-in and run only when credentials are present. An adapter
  that has only been tested against recordings is labelled "not verified live".

## Status texts

| Situation | Text shown |
|---|---|
| Adapter not written | Planned — integration not yet implemented. |
| Adapter exists, no credentials | Not configured — API credentials required. |
| Adapter configured but failing | The actual failure reason, where safe to show |

## Catalogue

Generated from `config/providers.yaml` by `scripts/dev/gen_docs.py`. Do not edit
the table by hand. Access notes describe publicly documented terms as understood
when the file was written; each entry is re-verified against official
documentation when its adapter is built.

<!-- BEGIN GENERATED: provider-catalogue -->
79 entries: 0 available, 75 planned, 4 excluded.

### Internet asset intelligence

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [Shodan](https://developer.shodan.io/api) | Limited free tier | api key | 5 | Planned | Free accounts have little or no search quota; search filters and bulk access need a paid plan. Plan and remaining credits are read from the account information endpoint. |
| [Shodan InternetDB](https://internetdb.shodan.io/) | Free | none | 5 | Planned | Keyless per-IP summary (ports, hostnames, product identifiers, vulnerability identifiers). Intended for non-commercial use. Preferred free-first source before spending Shodan credits. |
| [Censys](https://docs.censys.com/) | Limited free tier | token | 5 | Planned | Two API generations exist (legacy Search and the Censys Platform) with different authentication. The adapter must detect which one the account can use instead of assuming either. |
| [FOFA](https://en.fofa.info/api) | Paid | api key | 5 | Planned | Result fields and volumes depend on membership level and points. Free accounts have very limited API access. |
| [ZoomEye](https://www.zoomeye.ai/) | Limited free tier | api key | 5 | Planned | Credit-based quota. API host and version have changed over time. |
| [Netlas](https://docs.netlas.io/) | Limited free tier | api key | 5 | Planned | Community tier has a small daily request allowance. |
| [ONYPHE](https://search.onyphe.io/docs/) | Limited free tier | api key | 5 | Planned | Available data categories depend on the subscription. |

### Threat intelligence

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [VirusTotal](https://docs.virustotal.com/reference/overview) | Limited free tier | api key | 6 | Planned | The public API is rate-limited and for non-commercial use. Lookups by hash, domain, IP and URL only; files are never uploaded without explicit approval because submitted samples are shared with other subscribers. |
| [AbuseIPDB](https://docs.abuseipdb.com/) | Limited free tier | api key | 6 | Planned | Daily check allowance depends on the plan. |
| [GreyNoise](https://docs.greynoise.io/) | Limited free tier | api key | 6 | Planned | The community endpoint returns a reduced record; full context is paid. |
| [AlienVault OTX](https://otx.alienvault.com/api) | Free, key required | api key | 6 | Planned | Free registration required. |
| [URLhaus (abuse.ch)](https://urlhaus-api.abuse.ch/) | Free, key required | api key | 6 | Planned | abuse.ch services require a free authentication key. |
| [ThreatFox (abuse.ch)](https://threatfox.abuse.ch/api/) | Free, key required | api key | 6 | Planned | abuse.ch services require a free authentication key. |
| [MalwareBazaar (abuse.ch)](https://bazaar.abuse.ch/api/) | Free, key required | api key | 6 | Planned | Metadata lookups by hash only. Samples are never downloaded or executed. |
| [Spamhaus](https://docs.spamhaus.com/) | Limited free tier | api key | 6 | Planned | Blocklist lookups need a registered query key; the intelligence API is a paid product. |
| [Cisco Talos](https://talosintelligence.com/) | No official API | none | 6 | Excluded | No official public API for reputation lookups. Not integrated unless licensed access is supplied; the website is not scraped. |
| [MISP](https://www.misp-project.org/documentation/) | Your own instance | api key | 6 | Planned | Connects to an instance the user operates or is authorised to use. |
| [OpenCTI](https://docs.opencti.io/) | Your own instance | token | 6 | Planned | Connects to an instance the user operates or is authorised to use. |

### DNS and domains

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [DNS resolution](https://www.dnspython.org/) | Built in (offline) | none | 4 | Planned | Standard record lookups through the configured resolver. |
| [RDAP and WHOIS](https://about.rdap.org/) | Free | none | 4 | Planned | Registries rate-limit and many redact registrant data. Results are whatever the registry publishes. |
| [crt.sh](https://crt.sh/) | Free | none | 4 | Planned | Community service with no availability guarantee; often slow. Queried sparingly and cached. |
| [Cert Spotter](https://sslmate.com/help/reference/ct_search_api_v1) | Limited free tier | api key | 4 | Planned | Limited unauthenticated use; a key raises limits. |
| [SecurityTrails](https://docs.securitytrails.com/) | Limited free tier | api key | 5 | Planned | Small monthly free allowance; historical DNS depends on the plan. |
| [DNSDumpster](https://dnsdumpster.com/developer/) | Limited free tier | api key | 5 | Planned | Official API with a key; the free tier is rate-limited. |
| [ViewDNS.info](https://viewdns.info/api/) | Limited free tier | api key | 5 | Planned | Small free allowance. |
| [WhoisXML API](https://www.whoisxmlapi.com/) | Limited free tier | api key | 5 | Planned | Trial credits, then paid. |
| [RapidDNS](https://rapiddns.io/) | No official API | none | 5 | Excluded | No documented official API. Excluded unless official programmatic access is offered; the website is not scraped. |
| [DNSlytics](https://dnslytics.com/) | Paid | api key | 5 | Planned | Paid API. |

### Web intelligence

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [urlscan.io](https://urlscan.io/docs/api/) | Limited free tier | api key | 5 | Planned | Searching existing scans is passive. Submitting a URL is an active operation that discloses the target to a third party and needs approval. |
| [Wayback Machine](https://archive.org/help/wayback_api.php) | Free | none | 4 | Planned | Rate-limited public service. |
| [Common Crawl](https://commoncrawl.org/) | Free | none | 9 | Planned | Index server is heavily rate-limited. |
| [BuiltWith](https://api.builtwith.com/) | Limited free tier | api key | 5 | Planned | The free API returns only summary counts; detail is paid. |
| [Wappalyzer](https://www.wappalyzer.com/api/) | Paid | api key | 5 | Planned | Paid API. |
| [PublicWWW](https://publicwww.com/) | Paid | api key | 9 | Planned | Paid API. |

### Public code

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [GitHub](https://docs.github.com/en/rest) | Free, key required | token | 6 | Planned | Unauthenticated use is tightly limited; code search has its own limit. |
| [GitLab](https://docs.gitlab.com/api/rest/) | Free, key required | token | 6 | Planned | Works with gitlab.com or a self-managed instance. |
| [grep.app](https://grep.app/) | No official API | none | 6 | Excluded | No documented, stable public API. Excluded until one is documented. |
| [Gitleaks](https://github.com/gitleaks/gitleaks) | Tool you install | none | 6 | Planned | MIT licence. Run only on authorised repositories or supplied material. Findings are redacted; secrets are never used. |
| [TruffleHog](https://github.com/trufflesecurity/trufflehog) | Tool you install | none | 6 | Planned | AGPL-3.0 licence, so it is never bundled. Verification against live services is disabled: a detected secret is never sent anywhere. |

### Vulnerability and software

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [NVD](https://nvd.nist.gov/developers) | Free | api key | 6 | Planned | A free key is optional and raises the rate limit. |
| [CISA Known Exploited Vulnerabilities](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) | Free | none | 6 | Planned | Published as a downloadable feed. |
| [FIRST EPSS](https://api.first.org/epss/) | Free | none | 6 | Planned | Probability scores; not a statement that a system is exploitable. |
| [MITRE CWE](https://cwe.mitre.org/) | Free | none | 6 | Planned | Weakness catalogue, downloaded and cached locally. |
| [OSV](https://google.github.io/osv.dev/) | Free | none | 6 | Planned | Package-version vulnerability queries. |
| [GitHub Advisory Database](https://docs.github.com/en/rest/security-advisories/global-advisories) | Free, key required | token | 6 | Planned | Uses the GitHub credential. |
| [Package registries (PyPI, npm and others)](https://docs.pypi.org/api/json/) | Free | none | 6 | Planned | Public package metadata; each registry is a separate small adapter. |

### Network and IP data

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [RIPEstat](https://stat.ripe.net/docs/data-api/ripestat-data-api) | Free | none | 4 | Planned | Routing, prefix and ASN data. |
| BGPView | Free | none | 4 | Excluded | The public service did not respond when this catalogue was written and appears to have been discontinued. RIPEstat covers the same routing data. Re-checked if the service returns. |
| [IPinfo](https://ipinfo.io/developers) | Limited free tier | token | 4 | Planned | Free tier is country and ASN level; finer data is paid. |
| [MaxMind GeoLite2](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data/) | Free, key required | account | 4 | Planned | Local database downloaded with a free account. Licence requires keeping it current. Locations are estimates, never addresses. |

### Geospatial

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [OpenStreetMap Nominatim](https://nominatim.org/release-docs/latest/api/Overview/) | Free | none | 9 | Planned | The public instance has a strict usage policy (low request rate, identifying user agent, no bulk use). Heavy use needs a self-hosted or commercial instance. |
| [Map tiles (configurable source)](https://operations.osmfoundation.org/policies/tiles/) | Free | none | 9 | Planned | The tile source is a setting. The public OpenStreetMap tile servers are not meant for heavy application use; attribution is always required. |

### Corporate records

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [OpenCorporates](https://api.opencorporates.com/) | Paid | api key | 9 | Planned | Paid, with free access by application for qualifying open-data use. |
| [UK Companies House](https://developer.company-information.service.gov.uk/) | Free, key required | api key | 9 | Planned | Example of an official registry; others are added per jurisdiction. |
| [SEC EDGAR](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Free | none | 9 | Planned | Requires a declared user agent and has a request-rate limit. |
| [GLEIF LEI](https://www.gleif.org/en/lei-data/gleif-api) | Free | none | 9 | Planned | Legal entity identifiers and published ownership relationships. |

### Research

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | Free | none | 9 | Planned | Asks callers to identify themselves for the polite pool. |
| [OpenAlex](https://docs.openalex.org/) | Free | none | 9 | Planned | Key and usage policy to be confirmed at integration time. |
| [Semantic Scholar](https://www.semanticscholar.org/product/api) | Free, key required | api key | 9 | Planned | A key is recommended; the shared pool is heavily limited. |

### Phone

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [libphonenumber](https://github.com/google/libphonenumber) | Built in (offline) | none | 4 | Planned | Offline validation, region and number type. Carrier data reflects the original allocation of a number range, not the current operator, and never identifies a subscriber. |
| [Authorised carrier lookup](https://www.twilio.com/docs/lookup) | Paid | api key | 4 | Planned | Line type and current carrier from a commercial lookup service (Twilio Lookup is the reference adapter). Paid per query. No subscriber identity. |

### Email

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [Have I Been Pwned](https://haveibeenpwned.com/API/v3) | Paid | api key | 4 | Planned | Breached-account search needs a paid key. Domain search needs verified control of the domain. Passwords are never handled. |
| [EmailRep](https://emailrep.io/) | Free, key required | api key | 4 | Planned | Keys are issued on request; availability to be confirmed. |

### Username

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [Sherlock](https://github.com/sherlock-project/sherlock) | Tool you install | none | 4 | Planned | MIT licence. Checks public profile URLs. Results are candidate associations and include false positives. |
| [Maigret](https://github.com/soxoj/maigret) | Tool you install | none | 4 | Planned | MIT licence. Same caveats as Sherlock. |

### Social and news

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| Official social platform APIs | Limited free tier | token | 9 | Planned | Each platform is evaluated separately and gets its own adapter. Many are paid or restricted. Nothing behind a login or privacy setting is collected. |
| [GDELT](https://www.gdeltproject.org/) | Free | none | 9 | Planned | Global news index. |
| Public RSS and Atom feeds | Free | none | 9 | Planned | User-configured feeds. |
| Licensed web search API | Paid | api key | 9 | Planned | Provider to be selected when the first module needs it. Search engines are used only through a licensed API, never by scraping result pages. |

### Authorised network discovery tools

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| [Nmap](https://nmap.org/book/man.html) | Tool you install | none | 8 | Planned | Nmap Public Source License; never bundled. Active scanning runs only inside an approved scope. |
| [arp-scan](https://github.com/royhills/arp-scan) | Tool you install | none | 8 | Planned | GPL-3.0. Local network only, inside an approved scope. |
| [Netdiscover](https://github.com/netdiscover-scanner/netdiscover) | Tool you install | none | 8 | Planned | GPL-3.0. Local network only, inside an approved scope. |
| [SNMP tools](http://www.net-snmp.org/) | Tool you install | none | 8 | Planned | Reads devices the user administers, with credentials they supply. |
| LLDP and CDP data ingestion | Tool you install | none | 8 | Planned | Imports neighbour tables exported from authorised devices. |
| Traceroute | Tool you install | none | 8 | Planned | A hop is an observation of a path, not proof of a physical connection. |
| [Wireshark (tshark)](https://www.wireshark.org/docs/) | Tool you install | none | 8 | Planned | GPL-2.0. Reads captures the user supplies. |
| [Zeek](https://docs.zeek.org/) | Tool you install | none | 8 | Planned | BSD licence. Imports logs the user supplies. |

### AI models

| Provider | Access | Auth | Phase | Status | Notes |
|---|---|---|---|---|---|
| Cloud language models | Paid | api key | 10 | Planned | Reached through each vendor's official SDK behind one interface. No vendor or model is hard-coded. Disabled entirely in local-only mode. |
| Local language models | Your own instance | none | 10 | Planned | Any local server with an OpenAI-compatible API (for example Ollama, llama.cpp or LM Studio). Case data stays on the machine. |
<!-- END GENERATED: provider-catalogue -->
