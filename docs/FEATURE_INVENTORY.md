# Feature inventory

Every capability named in the brief, where it will live, the phase that builds
it and its present status. "Planned" means no code exists yet; it never means a
stub is in place. The machine-readable version of the section list is the
feature registry (`src/omniosint/core/features.py`), which the web interface
reads to decide what to show as available.

Status legend: **Available** · **Partial** (some of it works, limits stated) ·
**Planned**.

## Platform

| Feature | Phase | Status | Notes |
|---|---|---|---|
| Layered configuration with validation | 1 | Available | YAML, `.env`, environment; unknown keys rejected |
| Structured logging with redaction | 1 | Available | |
| Consistent error envelope | 1 | Available | |
| PostgreSQL connectivity and migrations | 1 | Available | |
| Authentication, sessions, CSRF | 1 | Available | |
| Role-based access control | 1 | Available | Built-in roles; custom roles planned for Phase 13 |
| Audit trail | 1 | Available | Append-only; viewer in Administration |
| Protected secret storage (DPAPI) | 1 | Available | Used for the database password now, provider keys from Phase 5 |
| Health checks and diagnostics | 1 | Available | `health/live`, `health/ready`, `omniosint doctor` |
| Process lifecycle (start, stop, status) | 1 | Available | |
| Windows install and lifecycle scripts | 1 | Available | Run end to end on every push by the CI `windows` job (Windows Server 2025) |
| Backup and restore | 1 | Partial | Unencrypted archives; encryption in Phase 13 |
| Desktop shell | 1 | Partial | Starts, monitors and stops the backend; its control library is tested against a real Windows installation and the installer is built by CI; the window itself has not been exercised by an automated test; tray mode in Phase 11 |
| Command palette (Ctrl+K) | 1 | Partial | Navigation and actions; indicator search in Phase 2 |
| Redis cache and rate limiting | 2 | Planned | Connection health check exists |
| Collection job queue | 2 | Planned | |
| Scope manager | 2 | Planned | |
| Multi-user refinements, retention policies | 13 | Planned | |

## Universal input engine (brief section 4)

| Feature | Phase | Status |
|---|---|---|
| Type detection for all 24 input types | 2 | Planned |
| Validation and normalisation | 2 | Planned |
| Ambiguity handling (show candidates) | 2 | Planned |
| Collection plan preview and approval | 2 | Planned |
| Search history and saved searches | 2 | Planned |
| Provider selection and advanced options | 2 | Planned |

## Intelligence modules (brief section 5)

| # | Module | Phase | Status | Key constraints carried from the brief |
|---|---|---|---|---|
| 1 | Email | 4 | Planned | No mailbox access, password discovery or account recovery abuse |
| 2 | Phone | 4 | Planned | No subscriber identity, live tracking or private-account access |
| 3 | Username | 4 | Planned | Matches are candidate associations, never proof of identity |
| 4 | Domain | 4 | Planned | |
| 5 | IP | 4 | Planned | Geolocation is an estimate, never a physical address |
| 6 | Internet-wide assets | 5 | Planned | Official APIs only; no invented endpoints; paid features stated |
| 7 | Network topology | 8 | Planned | Internal discovery only inside an approved scope |
| 8 | Social and public profile | 9 | Planned | Official APIs and compliant public collection only |
| 9 | Organisation | 9 | Planned | No ownership or employment inferred from shared contact data |
| 10 | Image | 9 | Planned | Similarity is not proof of identity |
| 11 | Document | 9 | Planned | Safe parsing, size limits |
| 12 | Geospatial | 9 | Planned | No live tracking |
| 13 | Threat | 6 | Planned | Submitted files are never executed |
| 14 | Vulnerability | 6 | Planned | Name similarity is not evidence of vulnerability |
| 15 | Software and supply chain | 6 | Planned | Secret detection only on authorised material; secrets redacted, never used |
| 16 | Brand abuse and impersonation | 11 | Planned | |
| 17 | News and events | 9 | Planned | |
| 18 | Academic and research | 9 | Planned | |
| 19 | Cloud and digital infrastructure | 8 | Planned | No access to private cloud resources |
| 20 | Historical and temporal | 11 | Planned | |

## Shared engines (brief sections 6 to 8)

| Engine | Phase | Status |
|---|---|---|
| Entity registry (28 entity types) | 2 and 7 | Planned |
| Relationship engine (typed, evidence-linked) | 7 | Planned |
| Graph queries, filters, path analysis | 7 | Planned |
| Graph exports: PNG, SVG, JSON, GraphML, CSV | 7 | Planned |
| Entity resolution with analyst review | 7 | Planned |
| Confidence engine, six separate dimensions | 7 | Planned |
| Evidence and provenance engine | 2 | Planned |
| Evidence explorer | 3 | Planned |
| Temporal engine and snapshots | 11 | Planned |

## AI (brief section 9)

| Feature | Phase | Status |
|---|---|---|
| Lead orchestrator and nine specialist agents | 10 | Planned |
| Local and cloud model adapters, fallback | 10 | Planned |
| Permissioned tool registry, approval gates | 10 | Planned |
| Structured output validation | 10 | Planned |
| Token and cost tracking | 10 | Planned |
| Local-only mode | 10 | Planned |

## Providers (brief section 10)

See [PROVIDERS](PROVIDERS.md). No provider integration exists yet; the
catalogue is loaded from `config/providers.yaml` and shown as planned.

## Case management, monitoring, workflows, reporting

| Feature | Phase | Status |
|---|---|---|
| Cases, members, scopes, notes, findings | 3 | Planned |
| Case duplicate, archive, reopen, compare, export | 3 | Planned |
| Watchlists, schedules, change detection, alerts | 11 | Planned |
| Desktop, email and webhook notifications | 11 | Planned (desktop notifications for service state exist) |
| Visual workflow builder | 12 | Planned |
| Advanced analytics | 12 | Planned |
| Report builder and twelve report types | 13 | Planned |
| PDF, HTML, JSON, CSV, STIX 2.1 export | 13 | Planned |
| Digital intelligence twin | 11 | Planned |

## Interface (brief section 13)

| Screen | Phase | Status |
|---|---|---|
| Application shell, navigation, themes | 1 | Available |
| First-run setup, sign-in, account settings | 1 | Available |
| Dashboard | 1 | Partial — system health, module availability and activity; case metrics from Phase 3 |
| Administration: users, roles, audit log, system status | 1 | Available |
| Integrations (provider control centre) | 1 | Partial — catalogue only; health, quota and keys from Phase 5 |
| Universal search | 2 | Planned |
| Investigation workspace | 3 | Planned |
| Module workspaces | 4 to 9 | Planned |
| Relationship graph workspace | 7 | Planned |
| Map workspace | 9 | Planned |
| AI investigation centre | 10 | Planned |
| Monitoring and alerts | 11 | Planned |
| Reports and evidence centre | 3 and 13 | Planned |
