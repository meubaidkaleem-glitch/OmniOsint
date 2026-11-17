# OmniOSINT architecture

Status of this document: Phase 0 deliverable, kept current as phases land.
Each section is tagged **[Implemented]** (code exists and is tested) or
**[Design]** (agreed target, built in the phase named).

Related documents: [ROADMAP](ROADMAP.md) · [FEATURE_INVENTORY](FEATURE_INVENTORY.md) ·
[DATABASE_SCHEMA](DATABASE_SCHEMA.md) · [PROVIDERS](PROVIDERS.md) ·
[UI_NAVIGATION](UI_NAVIGATION.md) · [RISK_REGISTER](RISK_REGISTER.md) ·
[SECURITY](../SECURITY.md) · [PRIVACY](../PRIVACY.md)

---

## 1. What OmniOSINT is

OmniOSINT is a local-first intelligence investigation platform. It collects
information from lawful public and authorised sources, normalises it into one
entity-and-relationship model, keeps the evidence for every claim, and helps an
analyst correlate, verify, visualise and report it.

Three properties drive most design choices:

1. **Evidence before conclusions.** Nothing is shown as a finding without a
   stored, attributable observation behind it. Observed facts, inferred
   relationships and AI summaries are different record types and never share a
   visual style.
2. **Safe by default.** Collection is passive unless the analyst defines a scope
   and approves an active operation. The interface listens on the loopback
   address only.
3. **Honest about coverage.** A provider that is not configured, not
   implemented or failing is shown as exactly that. No sample data is ever
   presented as a result.

## 2. System context and process model

```
  +---------------------+            +------------------------+
  |  Desktop shell      |            |  Browser               |
  |  (Tauri / WebView2) |            |  (local web interface) |
  +----------+----------+            +-----------+------------+
             | runs `omniosint start|status|stop`|
             | and shows the same web UI         | HTTP, loopback only
             v                                   v
  +-----------------------------------------------------------+
  |  API process  (FastAPI on uvicorn)                        |
  |    /api/v1/*   REST + OpenAPI                             |
  |    /           built React application (same origin)      |
  +-------+---------------------------------------+-----------+
          |                                       |
          v                                       v
  +----------------------+            +--------------------------+
  |  PostgreSQL          | <--------> |  Worker process          |
  |  system of record,   |            |  heartbeat, housekeeping |
  |  job queue, graph    |            |  (collection jobs and    |
  +----------------------+            |   scheduler from Phase 2)|
          ^                           +------------+-------------+
          |                                        |
  +----------------------+            +------------v-------------+
  |  Redis (optional)    |            |  Provider adapters       |
  |  cache, rate limits, |            |  -> external APIs and    |
  |  pub/sub             |            |     local tools          |
  +----------------------+            +--------------------------+
```

**[Implemented]** Two long-running processes, both started and stopped by one
supervisor implemented in Python (`omniosint start` / `stop` / `status`):

| Process | Command | Responsibility |
|---|---|---|
| API | `omniosint serve` | REST API, authentication, serves the built web UI |
| Worker | `omniosint worker` | Heartbeat and housekeeping today; collection jobs, monitoring schedules and report rendering in later phases |

The Windows `.bat` scripts and the desktop shell do not contain lifecycle logic
of their own. They call the same CLI commands, so there is one implementation
to test (ADR-010).

## 3. Repository layout

**[Implemented]**

```
omniosint/
├── src/omniosint/           Python package (backend, engine, CLI)
│   ├── api/                 FastAPI application, middleware, v1 routers, schemas
│   ├── auth/                passwords, sessions, CSRF, permissions, throttling
│   ├── audit/               audit trail service
│   ├── backup/              backup and restore (pg_dump / pg_restore)
│   ├── cli/                 Typer command-line interface
│   ├── core/                configuration, paths, logging, errors, ids, crypto,
│   │                        secret store, feature registry
│   ├── database/            SQLAlchemy models, engine, Alembic migrations, seeds
│   ├── providers/           provider catalogue (adapters arrive in Phase 2+)
│   ├── runtime/             process supervisor, shutdown signalling, server runner
│   ├── system/              health checks, diagnostics (`doctor`)
│   ├── users/               user administration service
│   └── workers/             worker process and housekeeping tasks
├── tests/                   unit/, integration/, security/, end_to_end/
├── frontend/                React + TypeScript + Vite web interface
├── desktop/                 Tauri desktop shell
├── config/                  settings.yaml, logging.yaml, providers.yaml (defaults)
├── scripts/                 windows/*.ps1, linux/*.sh, dev/ tooling
├── docs/                    this documentation
├── *.bat, setup.ps1         Windows entry points (thin wrappers)
└── docker-compose.yml       optional local PostgreSQL / Redis
```

### Mapping from the structure proposed in the brief

The brief proposed many top-level directories (`core/`, `providers/`,
`database/`, `ai/`, `cli/`, ...). As importable Python packages those names
collide easily with other distributions and cannot be installed safely into a
shared environment. They are kept as **subpackages of one distribution**,
which preserves the separation and makes imports unambiguous (ADR-001).

| Brief | Here |
|---|---|
| `backend/api`, `apps/api` | `src/omniosint/api` |
| `backend/authentication`, `backend/authorization` | `src/omniosint/auth` |
| `core/*` | `src/omniosint/core`, plus dedicated packages as each engine lands |
| `providers/*` | `src/omniosint/providers/<provider>` |
| `intelligence/*` | `src/omniosint/intelligence/<module>` (Phase 4+) |
| `graph_engine/` | `src/omniosint/graph_engine` (Phase 7) |
| `ai/` | `src/omniosint/ai` (Phase 10) |
| `database/` | `src/omniosint/database` |
| `workers/` | `src/omniosint/workers` |
| `cli/` | `src/omniosint/cli` |
| `frontend/`, `apps/web` | `frontend/` |
| `desktop/`, `apps/desktop` | `desktop/` |
| `reports/templates` | `src/omniosint/reporting/templates` (Phase 13) |

Packages for later phases are created when their first real code lands, not as
empty placeholders.

## 4. Backend architecture

**[Implemented]** Four layers; dependencies point downward only.

```
  api/            HTTP concerns only: routing, request/response schemas,
                  authentication dependencies, error mapping
     |
  services        auth.service, users.service, audit.service, backup.service,
                  system.health - business rules, transactions, audit events
     |
  core/           configuration, errors, ids, crypto, feature registry
     |
  database/       models, engine, migrations
```

Rules that keep this maintainable:

* Routers contain no business logic. They validate input, call a service and
  shape the response.
* Services take an `AsyncSession` and are used unchanged by the API and the CLI
  ("the CLI must use the same backend services and collection policies").
* Every mutating service call writes its audit event in the same transaction.
* Errors are raised as `OmniError` subclasses carrying a stable machine code;
  one handler turns them into the JSON error envelope.

### Request path

```
client -> RequestContext (request id, access log)
       -> HostValidation (DNS-rebinding defence)
       -> SecurityHeaders (CSP, nosniff, frame denial)
       -> BodySizeLimit
       -> OriginGuard (cross-site request defence)
       -> router -> dependency: principal (session + CSRF) -> permission check
       -> service -> database
```

### Error envelope

```json
{ "error": { "code": "permission_denied",
             "message": "You do not have permission to perform this action.",
             "details": [],
             "request_id": "0195c2f0-..." } }
```

Codes are stable identifiers the UI and CLI branch on. Messages are for people.
Stack traces never leave the process.

## 5. Shared intelligence foundation

**[Design — Phases 2 to 7]** One pipeline serves every module. Modules
contribute knowledge about an indicator type; they do not own storage, HTTP,
rate limiting or graph logic.

```
 input ─► classifier ─► planner ─► scope manager ─► job queue ─► provider adapters
                                       (approval)                      │
                                                                       v
 report ◄─ findings ◄─ confidence ◄─ entity resolution ◄─ normaliser ◄─ raw result
                          │                  │                │
                          └──── evidence and provenance ──────┘
                                         │
                                 entity / relationship graph
```

| Component | Responsibility | Phase |
|---|---|---|
| Classifier | Detect type(s) of an input, validate, normalise. Returns every plausible classification with a reason; never guesses silently | 2 |
| Planner | Turn (indicator, objective, mode) into an ordered collection plan with provider choice, cost estimate and approval needs | 2 |
| Scope manager | Single gate for every active operation: approved targets, exclusions, expiry, operation restrictions | 2 |
| Provider framework | Adapter contract, registry, health, quota, rate limit, retry, circuit breaker, cache | 2 |
| Normaliser | Provider output to common observation records without discarding original values | 2 |
| Evidence manager | Immutable evidence records, raw response references, hashes, transformation history | 2 |
| Entity registry | One canonical entity per normalised identifier, shared by all modules | 2, 7 |
| Relationship engine | Typed, evidence-linked edges with status (observed, candidate, supported, verified, conflicting, rejected) | 7 |
| Entity resolution | Candidate matching with analyst review; never merges on name, username, avatar or location alone | 7 |
| Confidence engine | Six separate dimensions, each with a stored rationale; no single blended score | 7 |
| Temporal engine | First seen, last seen, change detection, snapshots | 11 |

Design rules fixed now because changing them later is expensive:

* **Entities are global, cases reference them.** An IP address is one entity
  however many investigations touch it. Case membership is a join table with
  permission checks. This is what makes a unified cross-investigation graph
  possible without duplicating nodes.
* **Evidence is append-only.** Corrections are new records that supersede old
  ones; the history stays.
* **Source independence is modelled.** The source registry records upstream
  lineage, so two providers that resell the same dataset do not count as
  independent corroboration.
* **Raw responses are stored once**, content-addressed by SHA-256, with a
  retention period. Evidence rows point to them.

## 6. Data architecture

| Concern | Choice | Status |
|---|---|---|
| Structured records | PostgreSQL 15+ (asyncpg driver, SQLAlchemy 2, Alembic) | **Implemented** |
| Job queue | PostgreSQL table with `FOR UPDATE SKIP LOCKED` leases, asyncio workers | Design, Phase 2 (ADR-004) |
| Cache, rate-limit state, pub/sub | Redis when configured, in-process fallback otherwise | Health check implemented; use from Phase 2 |
| Graph | PostgreSQL is the system of record; `GraphStore` interface with a PostgreSQL implementation and an optional Neo4j projection | Design, Phase 7 (ADR-005) |
| Search | PostgreSQL full-text and trigram indexes first; OpenSearch optional at scale | Design, Phase 12 (ADR-012) |
| Object storage | Local content-addressed store under the data directory, encrypted at rest; S3-compatible later | Design, Phase 2 (ADR-013) |
| Secrets | AES-256-GCM envelope, master key protected by Windows DPAPI | **Implemented** (ADR-011) |

The full data model is in [DATABASE_SCHEMA](DATABASE_SCHEMA.md).

## 7. Frontend architecture

**[Implemented]** React + TypeScript, built with Vite, styled with Tailwind
CSS, served by the API process from the same origin.

```
frontend/src/
├── app/            router, providers (query client, theme), route guards
├── api/            typed client generated from the OpenAPI schema, query hooks
├── components/ui/  design-system primitives (button, input, table, dialog, ...)
├── components/     application pieces (shell, sidebar, command palette, ...)
├── pages/          one directory per navigation section
├── stores/         Zustand stores for UI state (theme, sidebar)
├── lib/            navigation spec, formatting, utilities
└── styles/         design tokens (dark default, light alternative)
```

* **Server state** lives in TanStack Query; **UI state** in small Zustand
  stores. Nothing is duplicated between them.
* **The API contract is generated.** `npm run gen:api` produces TypeScript
  types from the backend OpenAPI document, so a backend change that breaks the
  UI fails type-checking.
* **Navigation is data.** The 20 sections of the brief are one specification
  (`lib/navigation.ts`); availability comes from the backend feature registry
  (`GET /api/v1/system/features`). A section that is not built renders a
  "Planned — not yet implemented" page naming its phase. No control exists
  that does nothing.
* **Dashboard numbers are database records.** A metric whose module does not
  exist yet is shown as unavailable, not as zero.

Libraries added only when the feature that needs them lands: Cytoscape.js
(Phase 7), Leaflet (Phase 9), React Flow (Phase 12), Recharts (Phase 12).

## 8. Desktop shell

**[Implemented — basic]** A Tauri 2 application (ADR-009). It:

1. shows a local status page while it runs `omniosint start`,
2. loads the local web interface from `http://127.0.0.1:<port>` once the
   backend reports ready,
3. polls `omniosint status` and raises a system notification if the backend
   stops,
4. stops the backend on quit if it was the one that started it.

The remote page gets no access to Tauri commands; only the bundled status page
does. Background/tray operation arrives with monitoring in Phase 11.

## 9. AI investigation system

**[Design — Phase 10]**

```
 user request ─► Lead orchestrator ─► plan (structured) ─► approval gate
                       │
        ┌──────────────┼──────────────────────────────┐
        v              v                              v
  specialist agent  specialist agent  ...      verification agent
        │              │                              │
        └────── tool registry (permissioned) ─────────┘
                       │
        same services, scope manager and job queue as the UI and CLI
```

* **Model access goes through one interface**, `LLMProvider`, with adapters
  for a cloud provider's official SDK and for local OpenAI-compatible servers
  (Ollama, llama.cpp, LM Studio). No provider is hard-coded.
* **Nothing about a model is hard-coded**: model identifiers, context limits,
  prices, reasoning settings and sampling parameters are configuration or are
  discovered from the provider at runtime. Newer cloud models reject sampling
  parameters and forced tool choice outright, so the interface exposes
  capabilities instead of assuming them.
* **The tool loop is ours.** Every tool call is proposed, checked against
  permissions and scope, optionally approved by the analyst, executed by the
  same service layer the UI uses, and recorded in `ai_tool_calls`. Agents have
  no shell and no direct network access.
* **Structured output is validated.** Plans and findings are schema-checked
  (strict tool schemas or structured-output mode where available, Pydantic
  validation always). A claim without an evidence reference is flagged, not
  shown as a finding.
* **Stop reasons are handled explicitly**, including refusals and truncation.
* **Usage is recorded per call** (input, output and cached tokens as reported
  by the provider) and priced from a configurable table.
* **Local-only mode** blocks every cloud adapter. Sending case data to a cloud
  model requires explicit configuration and per-case consent, and the provider's
  data-retention terms are shown before it is enabled.

## 10. Security architecture

Summary only; the full design and threat model are in [SECURITY](../SECURITY.md).

| Control | Mechanism | Status |
|---|---|---|
| Local-only exposure | Binds `127.0.0.1`; refuses non-loopback unless explicitly enabled | Implemented |
| DNS-rebinding defence | `Host` header validated against an allow-list | Implemented |
| Authentication | Argon2id password hashes; opaque server-side sessions stored hashed | Implemented |
| CSRF | Token derived from the session, required on unsafe cookie-authenticated requests, plus `Origin` check | Implemented |
| First run | One-time local setup token; no default credentials | Implemented |
| Authorisation | Role-based permissions checked per endpoint; denials audited | Implemented |
| Brute force | Per-client throttle and account lockout | Implemented |
| Audit trail | Append-only table enforced by a database trigger | Implemented |
| Secrets at rest | AES-256-GCM envelope; master key under Windows DPAPI | Implemented |
| Browser hardening | Strict CSP, no third-party origins, frame denial | Implemented |
| Active-operation gate | Scope manager | Design, Phase 2 |
| Outbound request safety (SSRF) | Central HTTP client with destination policy | Design, Phase 2 |
| File handling | Size limits, type detection, sandboxed parsing | Design, Phase 9 |

## 11. Configuration

**[Implemented]** Sources, highest priority first:

1. environment variables (`OMNIOSINT_SERVER__PORT=9000`)
2. `.env` in the project directory or the data directory
3. user settings: `<data dir>/config/settings.yaml`
4. shipped defaults: `config/settings.yaml` and `config/logging.yaml`

Unknown keys are rejected with a message naming the key. Secrets never go in
YAML; they come from the environment or the protected secret store
(`omniosint secrets set database.password`).

The data directory is `%LOCALAPPDATA%\OmniOSINT` on Windows and
`~/.local/share/OmniOSINT` on Linux, overridable with `OMNIOSINT_HOME`. Program
files and user data are separate, so updating or reinstalling the program does
not touch investigations.

## 12. Observability

**[Implemented]**

* **Logs**: structured (structlog), JSON lines to rotating files per process,
  readable console output in a terminal. Every line carries the request id.
  A redaction step masks values of keys such as `password`, `token`,
  `authorization` and `api_key`.
* **Audit**: security-relevant actions in `audit_events`, queryable from the
  Administration section.
* **Health**: `GET /api/v1/system/health/live` (process is up) and `/ready`
  (database reachable and schema current). `omniosint doctor` checks the whole
  installation.

## 13. Testing strategy

| Layer | Tooling | What it proves |
|---|---|---|
| Unit | pytest | Pure logic: configuration, crypto, password policy, tokens, pagination, process state |
| Integration | pytest + real PostgreSQL | Migrations, authentication flows, RBAC, audit, health, backup round trip |
| Security | pytest | Headers, host and origin validation, CSRF, lockout, injection attempts, traversal |
| Frontend | Vitest + Testing Library | Navigation, forms, guards, error states |
| End to end | Playwright + real backend | First-run setup, sign-in, administration, sign-out in a real browser |
| Lifecycle | pytest, real processes | `start`, health, `stop` leave no stray processes |
| Windows | GitHub Actions `windows-latest` | Install, start, health check and stop through the `.bat` scripts |

Integration tests use PostgreSQL, never a substitute database: the schema relies
on PostgreSQL behaviour (JSONB, triggers, row locking).

## 14. Dependency map

What must exist before what. An arrow means "is required by".

```
 Phase 1 foundation (config, auth, DB, API, UI shell, lifecycle)
   └─► Phase 2 core engine (classifier, providers, evidence, scope, jobs)
         ├─► Phase 3 case management
         │     └─► Phase 4 first modules (domain, IP, email, phone, username)
         │           ├─► Phase 5 internet asset providers
         │           ├─► Phase 6 threat, vulnerability, software
         │           └─► Phase 7 graph engine, resolution, confidence
         │                 ├─► Phase 8 network topology, cloud
         │                 ├─► Phase 9 social, organisation, image, document, geo, news
         │                 └─► Phase 10 AI investigation
         │                       └─► Phase 11 history, monitoring, brand
         │                             └─► Phase 12 analytics, workflows
         │                                   └─► Phase 13 reporting, enterprise
         │                                         └─► Phase 14 hardening, release
```

Decisions in Phase 1 that later phases depend on, and where rework would be
expensive if they were wrong: the driver and event-loop choice (ADR-003), the
job-queue design (ADR-004), global entities with case references (section 5),
the session and CSRF model (ADR-006), and the single lifecycle implementation
(ADR-010).

## 15. Architecture decision records

Each record states the decision, the alternatives considered and the reason.

### ADR-001 One Python distribution with subpackages
*Decision.* All backend code lives in `src/omniosint/`.
*Alternatives.* Separate top-level packages as sketched in the brief.
*Reason.* Names like `core`, `database` and `cli` collide with other packages
and make installation into a shared environment unsafe. Subpackages keep the
same separation with unambiguous imports and one version number.

### ADR-002 PostgreSQL only; no SQLite fallback
*Decision.* PostgreSQL is the only relational database supported, in tests too.
*Alternatives.* SQLite for zero-install use, with PostgreSQL optional.
*Reason.* The design relies on JSONB, triggers and `SKIP LOCKED`. Supporting two
dialects would double migration and test effort and hide PostgreSQL-only bugs.
*Consequence.* PostgreSQL must be installed (native installer, `winget`, or
Docker). A managed portable PostgreSQL for the packaged installer is a Phase 14
item.

### ADR-003 asyncpg as the database driver
*Decision.* SQLAlchemy async engine on asyncpg, including for migrations.
*Alternatives.* psycopg 3.
*Reason.* On Windows, psycopg's async mode needs the selector event loop, but
running external tools as subprocesses (Nmap, Sherlock and others, Phase 4+)
needs the proactor event loop. asyncpg works on the proactor loop, so one
process can do both.

### ADR-004 Durable job queue in PostgreSQL, asyncio workers
*Decision.* Jobs are rows leased with `FOR UPDATE SKIP LOCKED` and executed by
asyncio workers. Redis is an optional accelerator for cache, rate-limit state
and progress fan-out.
*Alternatives.* Celery, Dramatiq, ARQ, Taskiq with Redis as broker.
*Reason.* Celery does not officially support Windows, the primary platform.
Collection work is I/O-bound and suits asyncio. Job state has to be in
PostgreSQL anyway for history, cancellation, approval gates and progress, and
enqueueing in the same transaction as the case change removes a class of
consistency bugs. The brief allows "Redis or supported queue alternative".
*Consequence.* We own roughly a few hundred lines of queue code and its tests.

### ADR-005 PostgreSQL as graph system of record, Neo4j optional
*Decision.* Entities and relationships are relational tables. A `GraphStore`
interface offers neighbourhood and path queries; the first implementation uses
recursive SQL and in-memory algorithms on case-sized subgraphs. Neo4j is an
optional projection, decided at a Phase 7 gate using measured graph sizes.
*Alternatives.* Neo4j as a required second database.
*Reason.* Evidence, permissions and graph must stay transactionally consistent.
A required second database would double installation and backup complexity on a
desktop. The brief says "Neo4j ... where justified".

### ADR-006 Server-side opaque sessions
*Decision.* A random 256-bit token per session, stored only as a SHA-256 hash.
Browsers get it in an `HttpOnly`, `SameSite=Strict` cookie; the CLI and desktop
shell use it as a bearer token. The CSRF token is an HMAC of the session token.
*Alternatives.* JWT access and refresh tokens.
*Reason.* Sessions can be listed, revoked and expired server-side at once, which
JWTs cannot do without a server-side list anyway. No signing key to protect.

### ADR-007 First run protected by a local setup token
*Decision.* While no user exists, the API accepts one administrator-creation
request, and only with a token written to a user-only file in the data
directory. The CLI can also create the first user directly.
*Alternatives.* Default credentials; an open bootstrap endpoint.
*Reason.* Default credentials are a known failure. An open endpoint could be
called by any web page the user visits during the first-run window.

### ADR-008 The API serves the web UI from the same origin
*Decision.* FastAPI serves the built single-page application.
*Alternatives.* A separate static server or the Vite dev server in production.
*Reason.* One port, no CORS in production, a strict content security policy,
and `SameSite=Strict` cookies work without exceptions.

### ADR-009 Tauri for the desktop shell
*Decision.* Tauri 2.
*Alternatives.* Electron.
*Reason.* The brief prefers a lightweight shell. Tauri uses the system WebView2
(present on Windows 11 and current Windows 10) and has a capability model that
keeps the remote page away from native commands.
*Cost.* Building it needs the Rust toolchain and MSVC build tools.

### ADR-010 One lifecycle implementation, file-based shutdown request
*Decision.* `omniosint start|stop|status|restart` implement process control.
Graceful shutdown is requested by writing a file in the run directory that both
processes watch; forced termination is the fallback.
*Alternatives.* Lifecycle logic in batch/PowerShell; POSIX signals.
*Reason.* Windows has no reliable equivalent of SIGTERM for a detached process
without a console. A file request behaves the same on every platform and can be
tested on Linux and Windows alike.

### ADR-011 Envelope encryption with a platform-protected master key
*Decision.* Secrets are encrypted with AES-256-GCM under a master key. On
Windows the master key is protected by DPAPI for the current user; elsewhere it
is a file readable only by the owner.
*Alternatives.* Plain `.env` files; a third-party keyring library.
*Reason.* The brief requires DPAPI or equivalent. One encryption format
everywhere, with only the key protection being platform-specific, keeps the
code small. The same key will protect provider credentials (Phase 5) and stored
evidence (Phase 2).

### ADR-012 PostgreSQL search first, OpenSearch optional
*Decision.* Full-text and trigram indexes in PostgreSQL until measurements show
they are insufficient.
*Reason.* A desktop installation should not need a JVM search cluster. The
search service sits behind an interface so the engine can change.

### ADR-013 Local content-addressed object store
*Decision.* Raw provider responses and uploaded files are stored under the data
directory by SHA-256, encrypted at rest, with retention metadata in PostgreSQL.
*Reason.* Deduplication and integrity checking come for free, and large blobs
stay out of the database.

### ADR-014 OpenAPI is the contract
*Decision.* The backend's OpenAPI document is the source of truth; frontend
types and the API reference are generated from it and checked in CI.

### ADR-015 Providers are adapters behind a registry
*Decision.* Intelligence modules never call a provider API directly. They ask
the provider manager for a capability; adapters declare capabilities, cost,
eligibility and rate limits as metadata.
*Reason.* Required by the brief, and it is what makes free-first routing, cost
approval and caching possible in one place.

### ADR-016 Third-party tools are detected, not bundled
*Decision.* Tools such as Nmap, Sherlock, Maigret, Gitleaks and TruffleHog are
optional, user-installed, version-checked and called through adapters.
*Reason.* Several have licences that restrict redistribution (Nmap's NPSL,
TruffleHog's AGPL), and the brief forbids installing software silently.

### ADR-017 Provider-neutral model interface with our own tool loop
*Decision.* See section 9.
*Alternatives.* A vendor's agent runner; a third-party agent framework.
*Reason.* Every tool call must pass our permission, scope and approval gates
and be recorded as evidence-linked history, across cloud and local models.

## 16. Runtime dependencies

The exact, hash-pinned set is in `requirements.txt` (backend) and
`frontend/package-lock.json` (frontend). A generated inventory with licences is
in [DEPENDENCIES](DEPENDENCIES.md).

| Area | Dependency | Purpose |
|---|---|---|
| API | FastAPI, uvicorn, Pydantic | HTTP API, validation, OpenAPI |
| Data | SQLAlchemy, asyncpg, Alembic | ORM, driver, migrations |
| Cache | redis | Optional Redis client |
| Security | argon2-cffi, cryptography | Password hashing, authenticated encryption |
| Configuration | pydantic-settings, PyYAML, platformdirs | Layered settings, data directory |
| Operations | structlog, psutil, httpx | Logging, process control, health checks |
| CLI | Typer | Command-line interface |
| Web UI | React, React Router, TanStack Query, Zustand, Tailwind CSS, Radix UI primitives | Interface |
| Desktop | Tauri | Desktop shell |

Tenacity, Celery, Neo4j drivers, OpenSearch clients and the visualisation
libraries named in the brief are deliberately not installed yet; each is added
by the phase that first uses it.
