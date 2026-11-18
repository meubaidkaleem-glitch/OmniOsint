# Changelog

All notable changes to OmniOSINT. Each phase ends with the report the
development brief asks for (section 29).

## [0.2.0] - Unreleased - Phase 2: core intelligence foundation

### Added

* **Universal input classifier** (`indicators/`): 24 input types with
  validation and normalisation, using the Public Suffix List for domains and
  libphonenumber for phone numbers. Ambiguous input returns every reading with
  its strength and reason, never a guess. Defanged indicators are restored;
  credentials in URLs are removed from any input; invisible and direction
  characters are removed with a note; control characters are refused. Files
  are recognised from their first bytes, not their extension.
* **Provider framework** (`providers/`): the adapter contract (capabilities
  with accepted types, passive or active operation, cost, cache lifetime,
  limits), a registry that reports each source as available, not configured,
  disabled, planned or excluded, and a manager that applies a circuit
  breaker, a token-bucket rate limit (shared through Redis when configured),
  credentials from the secret store, timeouts, joining of identical calls and
  schema validation of every observation. Typed errors carry the provider's
  real reason and whether a retry can help.
* **Simulated provider**, off by default, to exercise the pipeline before real
  providers exist: it contacts nothing, generates data only in documentation
  ranges, is marked simulated by its registration, and can be told to fail
  (timeout, outage, rate limit, quota, refused credentials, malformed,
  partial, flaky, slow).
* **Outbound HTTP client** (`net/`): http and https only, no credentials in
  URLs, size and time limits, no proxy settings from the environment; every
  resolved address is checked against the special-use ranges (including IPv4
  carried inside IPv6) and the connection goes to the checked address, so DNS
  rebinding cannot redirect it; redirects are checked again.
* **Evidence store** (`evidence/`): append-only evidence rows (database
  triggers) linked to their entity, source, job, raw response and
  transformation history, with content and raw-response hashes and an
  integrity check; an entity registry (one row per type and canonical key,
  upserted safely under concurrency); a source registry with upstream lineage;
  raw responses stored once by SHA-256, compressed and encrypted with
  AES-256-GCM under a key in the secret store, with opaque file names and a
  retention period enforced by the worker.
* **Scope manager** (`scopes/`): recorded scopes of written authorisation
  (mode, who authorised it, reference, validity, targets and exclusions);
  checked when a plan is made, when a job is approved and immediately before
  it runs; revoked, never deleted.
* **Collection** (`collection/`): the planner (every source with its status and
  reason, cache reuse, cost, approval needs), a PostgreSQL job queue with
  leases, retries with backoff for retryable errors only, cancellation,
  approval, recovery of jobs whose worker was lost, and a job history; the
  worker runs the jobs.
* **Database**: migration `0002_intelligence_foundation` with 14 tables
  (evidence, entities, sources, raw objects, providers and usage, scopes and
  rules, collection requests, jobs, job events and results, search history,
  saved searches).
* **HTTP API**: `/search` (classify, types, history, saved searches),
  `/collection` (plan, requests, jobs and their actions), `/evidence`,
  `/entities`, `/sources`, `/scopes`, `/providers/adapters` and provider
  health checks. New permissions: `collection:read|run|approve`,
  `evidence:read|read_raw`, `scopes:read|manage`.
* **Command line**: `classify`, `search` and `investigate` (no longer planned
  stubs), `jobs list|show|approve|cancel|retry`, `evidence list|show`,
  `scopes list|create|revoke`; `providers list` shows the adapters and
  `providers test` runs their health checks.
* **Web interface**: Universal Search (classification, choice between
  readings, collection plan with options, run), collection history, request
  pages with job history and actions, evidence pages with provenance,
  integrity and the masked raw response, scope administration, adapters and
  health checks on the Integrations page, "Search for ..." in the command
  palette, and collection figures on the dashboard. Simulated data is labelled
  wherever it appears.
* **Backups** now include the raw responses (archive format 2), exported
  decrypted and encrypted again under the local key on restore;
  `--no-raw-responses` leaves them out. Phase 1 archives still restore.
* **Browser journey** for Phase 2 against a running worker: search, plan, run,
  evidence, a visible provider failure, and an active job that needs a scope
  and an approval.

### Changed

* Analysts may search, run collection and read evidence and scopes; auditors
  may read collection history, evidence and scopes. Approving active jobs,
  recording scopes and viewing raw responses unmasked stay with
  administrators.
* The dashboard counts collection requests, failed jobs, evidence and
  entities; simulated evidence is counted separately and only shown when there
  is some.
* The Phase 1 note that the sign-in throttle would move to Redis was
  corrected: OmniOSINT runs one API process, so the in-memory throttle already
  covers every attempt (SECURITY.md).
* A backup's partial archive is created readable only by its owner before
  anything is written to it.

### Phase 2 report

```
PHASE:            2 - Core intelligence foundation
STATUS:           Complete. Every acceptance criterion is met (docs/ROADMAP.md, Phase 2);
                  verified on Linux and, by the CI windows job, on Windows Server 2025.
FILES CREATED:    71 files, in summary:
                    src/omniosint/indicators/   classifier and parsers (14 files)
                    src/omniosint/providers/    contract, errors, registry, manager, rate
                                                limits, circuit breaker, simulated provider
                    src/omniosint/collection/   planner, queue, executor, runtime, service,
                                                input resolution
                    src/omniosint/evidence/     evidence, entities, sources, object store
                    src/omniosint/scopes/       rules, scope manager, service
                    src/omniosint/net/          address classification, guarded HTTP client
                    src/omniosint/database/     models (collection, intel, scope, search),
                                                migration 0002
                    src/omniosint/api/          search, collection, evidence and scope
                                                routers; schemas
                    src/omniosint/cli/          collection commands; core/filelock.py
                    tests/                      9 test modules (unit, integration, security)
                    frontend/                   search, request, evidence and scope pages,
                                                collection helpers, their tests
                    docs/images/                universal-search.png, collection-request.png
FILES MODIFIED:   76 files: API app, context, dependencies, dashboard and provider
                  routers; permissions; settings; secret store; paths; feature registry;
                  sign-in throttle notes; backup service and commands; CLI entry point
                  and provider commands; provider catalogue; worker and housekeeping;
                  seeds; test helpers and existing tests; frontend router, navigation,
                  palette, top bar, integrations and admin layout; e2e journey and its
                  runner; Python and npm lock files; version 0.2.0 across the Python
                  package, web interface and desktop shell; README, CHANGELOG, SECURITY,
                  PRIVACY and every guide in docs/.
FEATURES IMPLEMENTED:
                  Universal input classifier; indicator validation and normalisation;
                  provider base class and registry; normalisation; evidence manager;
                  source registry; rate limiter; cache; collection job system; scope
                  manager. Around them: guarded outbound HTTP, encrypted raw-response
                  store with retention, entity registry, simulated provider, API, CLI,
                  web interface, and backups that include raw responses.
TESTS EXECUTED:   Backend:  ruff, ruff format, mypy --strict, pytest (unit, PostgreSQL
                            integration, security, process lifecycle) with coverage,
                            pip-audit
                  Frontend: eslint, tsc, vitest, production build, npm audit
                  Browser:  Playwright, 10 journeys (6 from Phase 1, 4 new) against a
                            freshly started instance with its worker
                  Desktop:  cargo test of the control library on Linux, and on Windows
                            against the CI installation; the CI desktop job builds the
                            0.2.0 installer
                  Windows:  the CI windows job on Windows Server 2025: install.bat,
                            start.bat, health-check.bat, readiness, stop.bat, backup.bat
                            and restore.bat with the new archive format, doctor, pytest
                            on Windows (including DPAPI), uninstall.bat
TEST RESULTS:     Backend   501 passed, 1 skipped (Windows-only DPAPI test) on Linux,
                            86% line coverage including subprocesses; 498 passed,
                            4 skipped (Redis not configured there, POSIX-only checks)
                            on Windows; lint and types clean; no known vulnerabilities
                            in the pinned dependencies
                  Frontend  37 passed; lint and types clean; 0 runtime vulnerabilities
                  Browser   10 passed
                  Desktop   6 passed on Linux and on Windows; installer built
                  Windows   every step of the CI job passed; doctor 14 ok / 0 warnings
                            / 0 failures with the application running
                  CI        all five jobs passed on the final code
                            (https://github.com/meubaidkaleem-glitch/OmniOsint/actions/runs/44351392905)
KNOWN LIMITATIONS:
                  * No real provider is integrated: collection works end to end only with
                    the simulated provider. The first integrations arrive in Phases 4 to 6.
                  * Scopes stand alone; they are attached to investigations in Phase 3.
                  * The scope manager checks a target as given. No active capability that
                    contacts anything exists yet; when one does (Phases 5 and 8), a domain
                    target's resolved addresses must pass the scope too.
                  * Raw-response masking works on field names in JSON; other content is
                    only shown unmasked, to holders of evidence:read_raw.
                  * Files are classified from the command line only (uploads: Phase 9);
                    questions are recognised but answered from Phase 10.
                  * Provider restriction in a plan is available in the API and CLI, not
                    yet in the web interface.
                  * Backups are not encrypted (Phase 13) and now also hold raw responses
                    in readable form, unless created with --no-raw-responses.
                  * Windows is verified on Windows Server 2025 in CI, not on a Windows 10
                    or 11 desktop.
                  * The project has no licence yet (owner decision).
SECURITY CONSIDERATIONS:
                  Outbound requests cannot reach internal addresses (checked and pinned
                  per connection, IPv4 inside IPv6 included, redirects re-checked). No
                  active job can exist without a scope (database constraint); the scope is
                  checked three times and every active job is approved by a person, all
                  audited. Evidence is append-only and hashed; raw responses are encrypted
                  at rest and expire. Credential-like fields are masked in raw views;
                  unmasked views need a separate permission and are audited, and content
                  that cannot be masked is never shown as masked. Credentials typed into a
                  search are removed before storage. Simulated data cannot pass for real
                  data: its flag comes from the provider's registration and is shown
                  everywhere. Details in SECURITY.md.
NEXT PHASE:       3 - Investigation management: cases, workspaces, notes, findings,
                  activity log, case status, scope management (attaching the Phase 2
                  scopes to cases), case export.
```

During the phase, walking through the interface in a browser found a
truncated selector, acronyms written in lower case ("an ipv4 address"),
singular and plural mismatches, and an inaccurate notice on failed requests;
all were fixed. Writing the security notes found two real gaps, also fixed: a
masked raw view could show a non-JSON response in full, and 6to4 and Teredo
addresses leading to internal IPv4 addresses were treated as public.

## [0.1.0] - Unreleased - Phase 1: project foundation

### Added

* **Backend** (Python 3.12+, FastAPI, SQLAlchemy 2 on asyncpg, Alembic):
  layered settings with validation; structured JSON logging with credential
  redaction; one error envelope with stable codes; AES-256-GCM secret store
  with a DPAPI-protected master key on Windows; first-run setup protected by a
  one-time local token; Argon2id passwords; server-side sessions (cookie with
  CSRF token for browsers, bearer for the CLI and desktop); sign-in throttling
  and account lockout; role-based permissions with four built-in roles;
  append-only audit trail enforced by database triggers; user administration
  that never removes the last administrator; health checks; feature registry;
  provider catalogue (79 sources, all planned or excluded); dashboard built
  only from database records.
* **HTTP hardening**: loopback-only binding by default, Host allow-list
  (DNS-rebinding defence), origin and `Sec-Fetch-Site` checks, JSON-only
  request bodies, body size limit, strict Content-Security-Policy and other
  security headers, sanitised request ids.
* **Processes**: API and background worker started detached by one supervisor
  (`omniosint start|stop|restart|status`), graceful shutdown through a request
  file that works the same on Windows and Linux, heartbeats in the database.
* **Command line** (`omniosint`): `start`, `stop`, `restart`, `status`,
  `serve`, `worker`, `doctor`, `openapi`, `db check|wait|upgrade|current|bootstrap`,
  `admin create-user|list-users|reset-password|setup-token`,
  `secrets set|list|delete`, `config show|paths|validate|set|unset`,
  `backup create|list|verify|restore`, `providers list|test`. Commands for
  later phases exist only to say they are planned and exit with status 2.
* **Backup and restore**: zip archive with a PostgreSQL dump, user settings and
  checksums; atomic restore with an automatic safety backup.
* **Web interface** (React 19, TypeScript, Tailwind CSS 4, TanStack Query,
  React Router, Zustand, Radix UI, cmdk): first-run setup, sign-in, forced
  password change, application shell with the twenty sections of the brief,
  dashboard, provider catalogue, administration (users, roles, audit log,
  system status, my account), Ctrl+K command palette, dark and light themes,
  icon-rail sidebar on narrow windows.
* **Windows**: `install.bat` / `setup.ps1`, `start.bat`, `stop.bat`,
  `restart.bat`, `health-check.bat`, `update.bat`, `backup.bat`, `restore.bat`,
  `uninstall.bat`. Nothing is installed system-wide without consent.
* **Linux**: `scripts/linux/install.sh`; optional `docker-compose.yml` for
  PostgreSQL and Redis.
* **Desktop shell** (Tauri 2.12): starts, monitors and stops the backend and
  shows the interface; lifecycle in a separately tested Rust library.
* **CI** (`.github/workflows/ci.yml`): Linux lint, types, tests and dependency
  audits; browser tests; a Windows job that installs, starts, health-checks,
  backs up, restores, stops and uninstalls through the `.bat` scripts and runs
  the test suite on Windows; a Windows desktop build.
* **Documentation**: installation, user, administrator and developer guides,
  generated API reference and dependency inventory.

### Phase 1 report

```
PHASE:            1 - Project foundation
STATUS:           Complete. Verified on Linux, and on Windows (Windows Server 2025)
                  by the CI windows job; see "Windows verification" below.
FILES CREATED:    240 files, in summary:
                    src/omniosint/        80 files (api, auth, audit, backup, cli, core,
                                          database + migration 0001, providers, runtime,
                                          system, users, workers)
                    tests/                26 files (unit, integration, security, end_to_end)
                    frontend/             web interface, 29 component tests, Playwright journey
                    desktop/              backend-control library, Tauri app, status page, icons
                    scripts/              windows/ helpers, linux/install.sh, dev/ tools
                    *.bat, setup.ps1      Windows entry points
                    docs/                 INSTALLATION, USER_GUIDE, ADMIN_GUIDE,
                                          DEVELOPER_GUIDE, API_REFERENCE, DEPENDENCIES
                    .github/workflows/ci.yml, docker-compose.yml, .env.example,
                    requirements.txt, requirements-dev.txt, pyproject.toml, CHANGELOG.md
FILES MODIFIED:   README.md, SECURITY.md, .gitignore, docs/ARCHITECTURE.md,
                  docs/ROADMAP.md, docs/FEATURE_INVENTORY.md, docs/RISK_REGISTER.md
FEATURES IMPLEMENTED:
                  Repository structure; Python backend; React frontend; database
                  connectivity and migrations; configuration system; logging; error
                  handling; authentication and RBAC foundation; audit trail; health
                  checks; process lifecycle; CLI; backup/restore; Windows and Linux
                  scripts; basic desktop shell.
TESTS EXECUTED:   Backend:  ruff, ruff format, mypy --strict, pytest (unit, PostgreSQL
                            integration, security, process lifecycle), pip-audit
                  Frontend: eslint, tsc, vitest, production build, npm audit
                  Browser:  Playwright, 6 journeys against a freshly started instance
                  Desktop:  cargo test (incl. start/probe/stop of a real installation),
                            clippy -D warnings, cargo check for x86_64-pc-windows-gnu
                  Scripts:  shellcheck; fresh-clone install with scripts/linux/install.sh
                            followed by start, readiness, interface and stop;
                            static checks of the Windows scripts
                  Windows:  CI job on Windows Server 2025: install.bat (non-interactive,
                            creates role and database), start.bat, health-check.bat,
                            readiness over HTTP, stop.bat, no processes left, desktop
                            control library against the installation, backup.bat and
                            restore.bat, pytest on Windows (incl. DPAPI), uninstall.bat
TEST RESULTS:     Backend   287 passed, 1 skipped (Windows-only DPAPI test) on Linux,
                            85% line coverage including subprocesses; 284 passed,
                            4 skipped (Redis not configured, POSIX-only checks) on
                            Windows; lint and types clean; no known vulnerabilities
                            in the pinned dependencies
                  Frontend  29 passed; lint and types clean; 0 runtime vulnerabilities
                  Browser   6 passed
                  Desktop   6 passed; clippy clean; Windows type-check clean
                  Install   Linux: fresh clone installed in 80 s, doctor 12 ok /
                            1 warning (secret store on Linux uses file permissions,
                            not DPAPI) / 0 failures; started healthy, served the
                            interface, stopped with no processes left
                  Windows   every step of the CI job passed; doctor 14 ok / 0 warnings
                            / 0 failures with the application running
KNOWN LIMITATIONS:
                  * Windows is verified on Windows Server 2025 in CI, not on a Windows 10
                    or 11 desktop. The interactive prompts of install.bat (as opposed to
                    -NonInteractive) and the winget installs have not been run.
                  * The Tauri window has not been exercised by an automated test; its
                    control library is tested against a real installation and the CI
                    "desktop" job builds the installer.
                  * Backups are not encrypted (Phase 13).
                  * Restoring a backup also restores its audit trail; later entries survive
                    only in the automatic pre-restore backup.
                  * The sign-in throttle is per process and in memory.
                  * Redis is only health-checked; it is used from Phase 2.
                  * No provider integration and no intelligence module exists yet; the
                    interface marks those sections as planned.
                  * The project has no licence yet (owner decision).
SECURITY CONSIDERATIONS:
                  Loopback-only by default; Host, Origin and CSRF defences; no default
                  credentials; one-time setup token kept out of logs and URLs sent to the
                  server; Argon2id; hashed session tokens; append-only audit trail;
                  secrets encrypted at rest (DPAPI on Windows); strict CSP with no inline
                  scripts; hash-pinned dependencies; the desktop shell grants IPC only to
                  its bundled page. Details in SECURITY.md.
NEXT PHASE:       2 - Core intelligence foundation: input classifier, provider framework,
                  normalisation, evidence manager, source registry, rate limiter, cache,
                  job queue, scope manager.
```

### Windows verification

The CI `windows` job runs the lifecycle on Windows Server 2025 on every push
([passing run](https://github.com/meubaidkaleem-glitch/OmniOsint/actions/runs/44283837382)).
Its first runs found two Windows-only defects, both fixed:

* `install.bat -NonInteractive` waited for a typed password: `common.ps1`,
  dot-sourced into the caller's scope, reset a variable that had the same name
  as the caller's `-NonInteractive` switch. The run hung until GitHub's
  six-hour limit. Every CI job now has a time limit, and static tests guard
  against the collision and against unguarded prompts.
* `omniosint doctor` printed WSL's UTF-16 output as `D e f a u l t` and called
  Windows Server "Windows 11".

Two tests also assumed Linux timing: Windows reports a refused connection only
after about two seconds of retries.

## [0.0.0] - Phase 0: requirements and architecture

### Phase 0 report

```
PHASE:            0 - Requirements and architecture
STATUS:           Complete
FILES CREATED:    docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/FEATURE_INVENTORY.md,
                  docs/DATABASE_SCHEMA.md, docs/PROVIDERS.md, docs/UI_NAVIGATION.md,
                  docs/RISK_REGISTER.md, config/providers.yaml, SECURITY.md,
                  PRIVACY.md, README.md, .gitignore, .gitattributes, .editorconfig
FILES MODIFIED:   none (empty repository)
FEATURES IMPLEMENTED:
                  Architecture with 17 decision records, roadmap and acceptance
                  criteria for fifteen phases, feature inventory, data model, provider
                  inventory of 79 sources and tools, security and privacy design,
                  navigation specification, risk register, dependency map.
TESTS EXECUTED:   Every provider documentation link fetched; broken or moved links
                  corrected; one provider without a reachable service excluded.
TEST RESULTS:     All catalogue links resolve except: GitHub-hosted pages (not
                  reachable from this build environment), crt.sh (timed out; the
                  service is often slow) and grep.app (rate-limited; excluded anyway
                  for lack of an official API).
KNOWN LIMITATIONS:
                  Provider access terms reflect public documentation at the time of
                  writing and are re-verified when each adapter is built.
SECURITY CONSIDERATIONS:
                  Threat model and controls in SECURITY.md; restricted operations of
                  brief section 17.2 are excluded by design.
NEXT PHASE:       1 - Project foundation.
```
