# OmniOSINT roadmap and acceptance criteria

The platform is built in fifteen phases (0 to 14). A phase starts only when the
previous one meets its acceptance criteria. The current state of each phase is
recorded here; the detail of what exists is in [CHANGELOG](../CHANGELOG.md).

| Phase | Title | Status |
|---|---|---|
| 0 | Requirements and architecture | Complete |
| 1 | Project foundation | Complete |
| 2 | Core intelligence foundation | Not started |
| 3 | Investigation management | Not started |
| 4 | First intelligence modules | Not started |
| 5 | Internet asset providers | Not started |
| 6 | Threat, vulnerability and software intelligence | Not started |
| 7 | Universal graph engine | Not started |
| 8 | Network topology and cloud infrastructure | Not started |
| 9 | Social, organisation, image, document, geospatial, news, research | Not started |
| 10 | AI investigation engine | Not started |
| 11 | Historical intelligence, monitoring, brand protection | Not started |
| 12 | Advanced analytics and workflow builder | Not started |
| 13 | Reporting and enterprise capabilities | Not started |
| 14 | Hardening and release | Not started |

## Definition of done

A feature is complete only when all of these hold:

1. Its purpose is documented.
2. Its architecture is defined.
3. Its implementation exists.
4. Its interface is functional.
5. Its API is functional where applicable.
6. Its database integration works.
7. Its validation works.
8. Its error handling works.
9. Its permissions are enforced.
10. Its evidence and provenance are preserved.
11. Its tests pass.
12. Its documentation is updated.
13. Its limitations are documented.

A screen without a working backend, a provider placeholder, or a command that
runs a tool without normalising its output and keeping evidence is not complete.

## Where the brief leaves a module unassigned

The brief's phase list does not place every module. These are allocated as
follows, and can be moved without architectural cost:

| Module | Phase | Why |
|---|---|---|
| 9 Organisation intelligence | 9 | Mostly public-records and news sources, same collection style as the Phase 9 group |
| 15 Software and supply chain | 6 | Shares OSV, advisories and vulnerability mapping with Phase 6 |
| 16 Brand abuse and impersonation | 11 | Is monitoring at heart: lookalike domains and certificate watches |
| 17 News and events | 9 | Named in the Phase 9 scope |
| 18 Academic and research | 9 | Public bibliographic APIs, low risk, no dependencies beyond Phase 2 |
| 19 Cloud infrastructure | 8 | Builds on the public infrastructure graph of Phase 8 |
| 20 Historical intelligence | 11 | Named in the Phase 11 scope |

---

## Phase 0 — Requirements and architecture

**Deliverables.** Architecture document, feature inventory, dependency map, data
model, provider inventory, security design, navigation specification, roadmap,
risk register, acceptance criteria.

**Acceptance.** Every deliverable exists in `docs/`; decisions that would be
expensive to reverse are recorded with alternatives (ARCHITECTURE section 15).

**Status: complete.**

## Phase 1 — Project foundation

**Deliverables.** Repository structure, Python backend, React frontend, database
connectivity, configuration system, logging, error handling, authentication
foundation, health checks, Windows installation scripts, basic desktop shell.

**Acceptance.**

| # | Criterion | How it is verified |
|---|---|---|
| 1 | Application installs | Install script run from a clean checkout |
| 2 | Application starts | `start` brings up API and worker; readiness reports ok |
| 3 | Application stops cleanly | `stop` ends both processes; none left running |
| 4 | Backend health endpoint works | `GET /api/v1/system/health/ready` |
| 5 | Frontend loads | Browser test against the running application |
| 6 | Database connectivity is verified | Readiness check and `omniosint doctor` |
| 7 | Tests pass | Backend, frontend and end-to-end suites |

**Status.** Every criterion is met on Linux and on Windows.

* Linux: a fresh clone installs with `scripts/linux/install.sh`, starts,
  reports ready, serves the interface, passes the browser journeys and stops
  with no processes left.
* Windows (CI, Windows Server 2025): `install.bat` installs non-interactively
  and creates the database; `start.bat`, `health-check.bat`, readiness over
  HTTP, `stop.bat` with no processes left, the desktop control library against
  that installation, `backup.bat` and `restore.bat`, the test suite on Windows
  (including DPAPI) and `uninstall.bat` all pass. The desktop installer is
  built by the `desktop` job.

Details in the Phase 1 report in [CHANGELOG](../CHANGELOG.md).

## Phase 2 — Core intelligence foundation

**Build.** Universal input classifier, indicator validation, provider base class
and registry, normalisation, evidence manager, source registry, rate limiter,
cache, collection job system, scope manager.

**Acceptance.**
* A sample indicator of every supported type is classified; ambiguous input
  returns every candidate instead of a guess.
* A mock provider returns structured data through the real pipeline.
* Results are normalised and stored; evidence stays linked to its source.
* Failed provider operations (timeout, quota, malformed data) are handled and
  visible in job history.
* No active operation runs without passing the scope manager.

## Phase 3 — Investigation management

**Build.** Cases, workspaces, notes, findings, activity log, case status, scope
management, case export.

**Acceptance.** Create and reopen cases; attach evidence; search investigations;
collection history is preserved; case permissions are enforced.

## Phase 4 — First intelligence modules

**Build, in order.** Domain, IP, email, phone, username.

**Acceptance.** Each module works on its own; all use the shared foundation; no
module keeps its own evidence system. Phone and username results carry the
caveats the brief requires (no subscriber identity from carrier metadata;
matching usernames are candidates, not proof).

## Phase 5 — Internet asset providers

**Build.** Shodan, Censys, FOFA, ZoomEye, Netlas, ONYPHE; key configuration,
health, quota, normalisation, provider comparison, asset relationships,
historical observations where the provider offers them.

**Acceptance.** Providers are configured independently; missing credentials give
a useful status; mock tests pass; live tests run only with eligible credentials.

## Phase 6 — Threat, vulnerability and software intelligence

**Build.** VirusTotal, AbuseIPDB, GreyNoise, OTX, URLhaus, ThreatFox,
MalwareBazaar, NVD, CISA KEV, EPSS, CWE, OSV; SBOM ingestion and dependency
mapping.

**Acceptance.** IOC enrichment works; vulnerability information is source-linked;
findings distinguish "product observed" from "vulnerability verified".

## Phase 7 — Universal graph engine

**Build.** Entity registry, relationship engine, graph builder and queries,
deduplication, entity resolution, filters, evidence-linked edges, exports.

**Acceptance.** Email, phone, IP, domain and organisation entities coexist in one
graph; every relationship has provenance; candidate and confirmed relationships
look different.

## Phase 8 — Network topology and cloud infrastructure

**Build.** Public infrastructure graph; authorised internal discovery adapters
(Nmap, SNMP, LLDP/CDP ingestion); inventory; topology view; cloud attribution.

**Acceptance.** Public assets are never confused with private devices; active
discovery is scope-gated; edges represent supported observations only.

## Phase 9 — Social, organisation, image, document, geospatial, news, research

**Acceptance.** Every module uses common entities and evidence; no unsupported
identification claim is generated; uploads are parsed safely within limits.

## Phase 10 — AI investigation engine

**Build.** Lead orchestrator, specialist agents, local and cloud model
integration, tool registry, planning, structured results, verification,
summaries.

**Acceptance.** The AI prepares and executes permitted plans; every result links
to evidence; unsupported claims are flagged; tool permissions are enforced;
local-only mode sends nothing to a cloud model.

## Phase 11 — Historical intelligence, monitoring, brand protection

**Acceptance.** An earlier observation can be compared with a newer one; changes
show source and timestamp; scheduled jobs respect quotas and rate limits.

## Phase 12 — Advanced analytics and workflow builder

**Acceptance.** Saved workflows run and can be inspected; each stage records its
execution and output; failed stages retry safely.

## Phase 13 — Reporting and enterprise capabilities

**Build.** PDF, HTML, CSV, JSON and STIX exports; graph exports; multi-user
refinements; audit trail views; encrypted backup and restore; retention.

**Acceptance.** Reports include evidence references; permissions are enforced;
backups restore; audit events are available.

## Phase 14 — Hardening and release

**Perform.** Regression, security review, performance, dependency audit, Windows
compatibility, migration, restore and installation testing, documentation review.

**Produce.** Stable release, versioned installer, user, administrator and
developer guides, API documentation, provider guide, security documentation,
release notes.
