# Changelog

All notable changes to OmniOSINT. Each phase ends with the report the
development brief asks for (section 29).

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
STATUS:           Complete and verified on Linux. Windows-specific paths written,
                  reviewed and type-checked, but not yet executed on Windows
                  (see "Windows verification" below).
FILES CREATED:    239 files, in summary:
                    src/omniosint/        80 files (api, auth, audit, backup, cli, core,
                                          database + migration 0001, providers, runtime,
                                          system, users, workers)
                    tests/                25 files (unit, integration, security, end_to_end)
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
                            followed by start, readiness, interface and stop
TEST RESULTS:     Backend   257 passed, 1 skipped (Windows-only DPAPI test), 85% line
                            coverage including subprocesses; lint and types clean;
                            no known vulnerabilities in the pinned dependencies
                  Frontend  29 passed; lint and types clean; 0 runtime vulnerabilities
                  Browser   6 passed
                  Desktop   6 passed; clippy clean; Windows type-check clean
                  Install   fresh clone installed in 80 s, doctor 12 ok / 1 warning
                            (secret store on Linux uses file permissions, not DPAPI) /
                            0 failures; started healthy, served the interface, stopped
                            with no processes left
KNOWN LIMITATIONS:
                  * Windows verification: no Windows machine was available, and running
                    PowerShell in the build environment was not permitted. setup.ps1 and
                    the .bat files were reviewed line by line for Windows PowerShell 5.1,
                    are ASCII-only, and the winget package IDs were checked against the
                    current winget index. The CI "windows" job exercises them on every
                    push; its result has to be checked in the repository's Actions tab.
                  * The Tauri application was type-checked for Windows but not compiled or
                    run here (no WebView libraries); the CI "desktop" job builds it and
                    uploads the installer.
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

What was done in place of running on Windows:

| Item | Check |
|---|---|
| `setup.ps1`, `scripts/windows/*.ps1` | Line-by-line review for Windows PowerShell 5.1 (no PowerShell 7-only syntax, no classes across dot-sourcing, native output kept out of function return values, `$null` not passed through `[string]` parameters); ASCII-only |
| `.bat`, `.cmd` | Review; CRLF line endings enforced by `.gitattributes` |
| winget package IDs | `Python.Python.3.12`, `OpenJS.NodeJS.LTS`, `PostgreSQL.PostgreSQL.16` found in the current winget index |
| Process control | Uses only cross-platform mechanisms (detached processes with `CREATE_NO_WINDOW`, a shutdown request file, PID plus creation time) |
| DPAPI | Implemented with ctypes; a Windows-only test exists and runs in CI |
| Desktop shell | `cargo check` and `clippy` for `x86_64-pc-windows-gnu` |

Until the CI run is green, treat the Windows path as unverified.

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
