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
