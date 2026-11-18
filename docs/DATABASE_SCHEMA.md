# Database schema

PostgreSQL 15 or later is the system of record. This document has two parts:

* **Part A** — tables that exist today, exactly as created by the migrations.
* **Part B** — the target model for later phases. It fixes names, ownership and
  the relationships that matter; column detail is finalised by the phase that
  creates each table, in its own migration.

Migrations live in `src/omniosint/database/migrations/versions/` and are applied
with `omniosint db upgrade`. A test fails if the models and the migrations ever
disagree.

## Conventions

| Topic | Rule |
|---|---|
| Primary keys | `uuid`. Version 7 (time-ordered) for append-heavy tables so new rows stay adjacent in the index |
| Timestamps | `timestamptz`, stored in UTC, default `now()` |
| Text identifiers | Normalised before storage (usernames lower-case), enforced by a `CHECK` |
| Provider-specific data | `jsonb`; core entity and evidence fields stay as typed columns |
| Deletion | Soft delete (`deleted_at`) where history matters; hard delete only through retention jobs |
| Constraint names | Generated from one naming convention so migrations are deterministic |
| Enumerations | `text` plus `CHECK`, not PostgreSQL enum types, so values can be added without a table rewrite |
| Extensions | None required so far |

---

## Part A — Implemented (Phases 1 and 2)

```
 users ──< user_roles >── roles ──< role_permissions >── permissions
   │
   ├──< user_sessions
   ├──< search_history, saved_searches
   │
 audit_events          (append-only, no foreign keys by design)
 system_settings       (key/value)
 service_instances     (process heartbeats)

 Phase 2: collection, evidence and scopes

 scopes ──< scope_rules
   │
 collection_requests ──< collection_jobs ──< collection_job_events
                              │
                              ├──< collection_results ──(raw_sha256)── raw_objects
                              │
 entities ──< evidence >── evidence_sources
                 │
                 └── job, collection result, raw response hash, superseded row

 providers ──< provider_usage
```

### users

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| username | text | unique; lower-case; 3 to 64 chars of `a-z 0-9 . _ -` |
| display_name | text | |
| email | text | optional; unique when present (case-insensitive) |
| password_hash | text | Argon2id encoded hash |
| is_active | boolean | inactive users cannot sign in |
| must_change_password | boolean | set when an administrator resets the password |
| failed_login_count | integer | reset on successful sign-in |
| locked_until | timestamptz | temporary lockout after repeated failures |
| last_login_at | timestamptz | |
| password_changed_at | timestamptz | |
| created_at, updated_at | timestamptz | |
| deleted_at | timestamptz | soft delete; the username stays reserved so audit attribution is unambiguous |

### roles, permissions, role_permissions, user_roles

| Table | Columns | Notes |
|---|---|---|
| roles | id, name (unique), description, is_system, created_at | Built-in roles have `is_system = true` and are kept in step with the code on every upgrade |
| permissions | id, code (unique, `resource:action`), description | |
| role_permissions | role_id, permission_id | composite PK, cascade on delete |
| user_roles | user_id, role_id, granted_at, granted_by | composite PK, cascade on delete |

Built-in roles:

| Role | Purpose |
|---|---|
| administrator | Everything, including user management and system settings |
| analyst | Investigation work: search and run collection, read evidence (masked raw responses) and scopes; more permissions as modules land |
| auditor | Read-only access including the audit trail, collection history, evidence and scopes |
| viewer | Read-only access to what they are assigned (cases, from Phase 3) |

### user_sessions

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| user_id | uuid | FK users, cascade |
| token_hash | text | unique; SHA-256 of the session token. The token itself is never stored |
| client_type | text | `web`, `cli`, `desktop` or `api` |
| auth_method | text | `cookie` or `bearer` |
| ip_address | text | as seen by the server |
| user_agent | text | truncated to 255 chars |
| created_at, last_seen_at | timestamptz | |
| expires_at | timestamptz | absolute lifetime |
| revoked_at, revoke_reason | timestamptz, text | |

Indexes: `user_id`, `expires_at`.

### audit_events

Append-only. A trigger rejects `UPDATE` always and `DELETE` unless the session
has set `omniosint.audit_purge = on`, which only the retention job does.
There are deliberately no foreign keys: an audit row must outlive the row it
describes and must never be changed by a cascade.

| Column | Type | Notes |
|---|---|---|
| id | uuid (v7) | PK |
| occurred_at | timestamptz | |
| category | text | `auth`, `authz`, `user`, `system`, `backup`, ... |
| action | text | stable code such as `auth.login.failure` |
| outcome | text | `success`, `failure` or `denied` |
| actor_user_id | uuid | null for anonymous or system actions |
| actor_label | text | username at the time, or `system` / `cli` |
| target_type, target_id | text | what was acted on |
| ip_address, user_agent, request_id | text | |
| details | jsonb | never contains secrets |

Indexes: `(occurred_at desc, id desc)`, `(actor_user_id, occurred_at)`,
`(action, occurred_at)`.

### system_settings

| Column | Type | Notes |
|---|---|---|
| key | text | PK |
| value | jsonb | |
| updated_at | timestamptz | |
| updated_by | uuid | |

Used for the instance identifier and first-run setup state.

### service_instances

One row per running API or worker process, updated by a heartbeat. The health
check reads it to report whether a worker is alive.

| Column | Type |
|---|---|
| id | uuid PK |
| service | text (`api` or `worker`) |
| pid | integer |
| version | text |
| started_at, last_heartbeat_at, stopped_at | timestamptz |
| details | jsonb |

### Phase 2 tables

Migration `0002_intelligence_foundation` creates the collection, evidence and
scope tables. Identifiers are UUIDs (v7 for the append-heavy tables). Every
enumeration is `text` with a `CHECK`.

#### evidence_sources

The source registry: one row per provider adapter and catalogue entry, plus
`omniosint.input` for what an analyst typed. Kept in step with the code and
`config/providers.yaml` on every upgrade.

| Column | Notes |
|---|---|
| id | text PK, the provider id (`simulated`, `shodan`, ...) |
| name, homepage_url, terms_note | |
| kind | `api`, `dataset`, `tool`, `local`, `analyst`, `upload`, `simulated` |
| provider_id | the adapter, when there is one |
| reliability | `unassessed`, `high`, `medium`, `low` (assessed in Phase 7) |
| upstream_source_ids | jsonb array: sources this one derives from, so two reports from the same upstream are not counted as independent |
| is_simulated | true only for the simulated provider |

#### entities

One row per thing observed, shared by everything that refers to it.

| Column | Notes |
|---|---|
| id | uuid PK |
| type | one of 29 entity types (`email`, `domain`, `ip_address`, `network_prefix`, ...) |
| canonical_key | normalised identifier; unique together with `type` |
| display_name, attributes | as first seen; attributes are jsonb |
| first_observed_at, last_observed_at | widened by every observation |
| is_simulated | true while only simulated evidence refers to it; cleared by the first real observation |
| merged_into_id | self reference for entity resolution (Phase 7) |
| deleted_at | soft delete |

Entities are created with `INSERT ... ON CONFLICT (type, canonical_key)`, so two
workers observing the same thing at once get one row.

#### raw_objects

A stored raw response, addressed by the SHA-256 of its content. The bytes live
in the object store under `data/storage/objects`, compressed and encrypted with
AES-256-GCM under a key kept in the secret store (ADR-013).

| Column | Notes |
|---|---|
| sha256 | PK, lower-case hex (checked) |
| size, content_type | |
| encryption | `aes-256-gcm` |
| retain_until | when housekeeping deletes the bytes and this row (`collection.raw_retention_days`, default 90) |

#### evidence

One attributable observation. **Append-only:** triggers reject `UPDATE` and
`TRUNCATE` always, and `DELETE` unless the session has set
`omniosint.evidence_purge = on` (only retention does). A correction is a new
row naming the one it supersedes.

| Column | Notes |
|---|---|
| id | uuid (v7) PK |
| entity_id | FK entities (restrict) |
| source_id | FK evidence_sources (restrict); `provider_id` repeats the adapter |
| job_id, collection_result_id | FK to what produced it (restrict) |
| observation_kind | what was observed (`simulated.attribute`, later `dns.a_record`, ...) |
| source_url, provider_object_id | where the provider says it came from |
| collected_at, observed_at, verified_at | collection time; the time the provider says it was true; verification (Phase 3) |
| normalized | jsonb: attributes and the mentions it carries (candidate relationships, not confirmed links) |
| content_hash | SHA-256 of the canonical JSON of the evidence content; recomputed by the integrity check |
| raw_sha256, raw_pointer | the raw response it was derived from, and the page within it |
| verification_status | `unverified`, `corroborated`, `verified`, `disputed` |
| is_redacted, is_simulated | `is_simulated` comes from the provider's registration, never from the adapter |
| transformation_history | jsonb array of the steps that produced the row (normaliser and version) |
| supersedes_id | self reference for corrections |
| investigation_id, relationship_id | reserved for Phases 3 and 7; no foreign key yet |

#### providers and provider_usage

`providers` holds one row per adapter or catalogue entry: name, category,
adapter version, `enabled`, `priority`, non-secret `config` and the last health
check. `provider_usage` counts requests, failures, cache hits and credits per
provider, capability and day (primary key `(provider_id, day, capability)`).
API keys are never stored in the database; they go to the secret store.

#### scopes and scope_rules

Recorded authorisation for active work. In Phase 2 scopes stand alone; Phase 3
attaches them to cases.

| Column (scopes) | Notes |
|---|---|
| id | uuid PK |
| name, description | |
| mode | `passive`, `authorized_discovery`, `active_assessment` |
| authorized_by, authorization_reference, authorization_note | who gave the written authorisation and where it is; `authorized_by` must not be blank |
| valid_from, valid_until | `valid_until > valid_from` (checked) |
| created_by, approved_by, approved_at | recording a scope requires the authorisation statement and records who made it |
| revoked_at, revoked_by, revoke_reason | scopes are revoked, never deleted, so the jobs that used them stay explained |

`scope_rules` (cascade with their scope): `kind` (`domain`, `wildcard`, `ip`,
`cidr`, `url_prefix`), normalised `value`, `is_exclusion`, `restrictions` (jsonb,
for ports and protocols in later phases). Unique per scope, kind, value and
exclusion flag. Exclusions always win; CIDR rules may be no broader than /8
(IPv4) or /16 (IPv6).

#### collection_requests

One row per plan that was run.

| Column | Notes |
|---|---|
| id | uuid (v7) PK |
| input_text, indicator_type, indicator_value | what the analyst entered and the reading used |
| entity_id | the entity the indicator became |
| mode, strategy | `passive` or `active`; `free_first` or `include_paid` |
| scope_id | the scope chosen for active work (restrict) |
| options, plan | jsonb: the options given and the plan exactly as shown, including the sources that were not used and why |
| status | derived from its jobs: `pending`, `awaiting_approval`, `running`, `completed`, `partial`, `failed`, `cancelled` |
| is_simulated, created_by, created_at, finished_at | |

#### collection_jobs

The queue and its history: one row per provider capability to call.

| Column | Notes |
|---|---|
| id | uuid (v7) PK |
| request_id | FK collection_requests (cascade) |
| indicator_type, indicator_value, entity_id | |
| provider_id, capability | |
| is_active, scope_id | `CHECK (NOT is_active OR scope_id IS NOT NULL)`: an active job cannot exist without a scope |
| is_simulated | |
| status | `queued`, `awaiting_approval`, `running`, `succeeded`, `failed`, `cancelled`, `skipped` |
| priority, attempt, max_attempts, scheduled_at | retries are scheduled with exponential backoff, only for retryable errors |
| lease_owner, lease_expires_at | the worker holding it; an expired lease is recovered |
| started_at, finished_at, cancel_requested_at | |
| options, progress, error, outcome, cost | jsonb; `error` keeps the provider's real code and message |
| cache_key | identifies an identical call, for reuse and joining |
| requested_by, approved_by, approved_at | |

Jobs are leased with `SELECT ... FOR UPDATE SKIP LOCKED`. A partial index on
`(priority, scheduled_at) WHERE status = 'queued'` keeps dequeueing cheap, and
one on `lease_expires_at WHERE status = 'running'` finds abandoned leases.

#### collection_job_events

The job history shown in the interface: `kind` (`created`, `approved`,
`started`, `scope_checked`, `retry_scheduled`, `retry_requested`,
`cancel_requested`, `succeeded`, `failed`, `cancelled`, `skipped`), `message`,
`details` (jsonb), `occurred_at`. Cascade with the job.

#### collection_results

What one call returned, page by page: `raw_sha256`, `raw_size`, `content_type`,
`status_code`, `normalized` (jsonb) and `item_count`, or `normalization_error`
when the response could not be normalised (the raw response is kept for
inspection). `from_cache` and `reused_result_id` record reuse of a fresh earlier
result; `cache_key` with `expires_at` is indexed for that lookup.

#### search_history and saved_searches

Per user (cascade with the user). History keeps the query, the classification
status and the candidate types of the newest 200 searches; saved searches have
a unique name per user, the query, an optional chosen type and options.

---

## Part B — Target model (Phases 3 to 13)

### Investigations (Phase 3)

| Table | Purpose | Key columns |
|---|---|---|
| investigations | A case | id, case_ref (human-readable, unique), title, description, objective, status (`draft`, `planned`, `running`, `paused`, `awaiting_review`, `completed`, `archived`), created_by, assignee_id, tags, created_at, updated_at, archived_at, deleted_at, retention_until |
| investigation_members | Who may see and change a case | investigation_id, user_id, case_role |
| investigation_scopes | Links the Phase 2 `scopes` to cases | investigation_id, scope_id, added_by, added_at; scopes gain an optional authorisation document (upload) |
| indicators | Inputs submitted to a case | id, investigation_id, raw_input, type, normalized_value, candidates (jsonb), created_by; unique per case and normalised value |
| findings | Analyst- or engine-stated conclusions | id, investigation_id, title, summary, category, severity, status, created_by, created_at |
| finding_evidence | Evidence supporting a finding | finding_id, evidence_id |
| analyst_notes | Notes on a case, entity, relationship, evidence item or finding | id, investigation_id, target_type, target_id, author_id, body, created_at, updated_at, deleted_at |

### Providers (Phases 4 to 6)

| Table | Purpose | Key columns |
|---|---|---|
| provider_health | Historical health checks (Phase 2 keeps the latest on `providers`) | provider_id, checked_at, status, latency_ms, detail, quota (jsonb) |

Provider keys stay in the protected secret store, not in the database.

### Entities and graph (Phase 7)

| Table | Purpose | Key columns |
|---|---|---|
| entity_identifiers | Alternative identifiers of an entity | entity_id, id_type, value, normalized_value; unique `(id_type, normalized_value)` |
| investigation_entities | Which entities a case uses | investigation_id, entity_id, added_by, added_at, pinned |
| relationships | Typed edges | id, source_entity_id, target_entity_id, type, status (`observed`, `candidate`, `supported`, `verified`, `conflicting`, `rejected`, `needs_review`), is_inferred, first_observed_at, last_observed_at, attributes (jsonb), created_by |
| relationship_evidence | Evidence behind an edge | relationship_id, evidence_id |
| entity_candidates | Possible same-entity pairs awaiting review | id, entity_a_id, entity_b_id, features (jsonb), status, reviewed_by, reviewed_at, rationale |
| confidence_assessments | One row per dimension per target, with history | id, target_type, target_id, dimension (`source_reliability`, `identity_match`, `relationship`, `factual_verification`, `freshness`, `completeness`), value, status, rationale, method, assessed_by, assessed_at |
| historical_observations | What was seen, when | id (v7), entity_id, kind, value (jsonb), value_hash, source_id, evidence_id, first_seen_at, last_seen_at |
| graph_snapshots | Saved state of a case graph | id, investigation_id, label, created_by, created_at, object_key, stats (jsonb) |

A relationship without at least one `relationship_evidence` row cannot be given
a status above `candidate`; this is enforced in the service and checked by a
constraint trigger.

### Files (Phase 9)

| Table | Key columns |
|---|---|
| uploaded_files | id, investigation_id, original_name, size, sha256, detected_type, object_key, uploaded_by, uploaded_at, deleted_at |
| file_metadata | file_id, extractor, extracted_at, metadata (jsonb) |

### AI (Phase 10)

| Table | Key columns |
|---|---|
| ai_sessions | id, investigation_id, user_id, mode (`local`, `cloud`), provider, model, started_at, ended_at, input_tokens, output_tokens, cached_tokens, cost_estimate |
| ai_messages | id, session_id, seq, role, content (jsonb), created_at |
| agent_runs | id, session_id, agent, parent_run_id, objective, status, plan (jsonb), usage (jsonb), started_at, finished_at |
| ai_tool_calls | id, agent_run_id, tool, arguments (jsonb, redacted), status (`proposed`, `approved`, `denied`, `executed`, `failed`), approved_by, result_ref, started_at, finished_at |

### Monitoring (Phase 11)

| Table | Key columns |
|---|---|
| monitoring_rules | id, name, entity_id, checks (jsonb), schedule, enabled, owner_id, last_run_at, next_run_at |
| alerts | id, rule_id, severity, title, explanation, evidence_id, first_observed_at, last_observed_at, status, acknowledged_by, suppressed_until |

### Workflows (Phase 12)

`workflows`, `workflow_versions`, `workflow_runs`, `workflow_run_steps`.

### Reporting (Phase 13)

| Table | Key columns |
|---|---|
| report_templates | id, name, type, version, body, is_system |
| reports | id, investigation_id, template_id, type, format, status, parameters (jsonb), object_key, content_hash, generated_by, generated_at |

---

## Retention

| Data | Default | Mechanism |
|---|---|---|
| Expired and revoked sessions | 7 days after expiry | Worker housekeeping (implemented) |
| Audit events | Kept; configurable from Phase 13 | Retention job with the purge flag |
| Raw provider responses | 90 days (`collection.raw_retention_days`); kept longer when attached to a finding from Phase 3 | `raw_objects.retain_until`, purged by worker housekeeping (implemented) |
| Cases | Until deleted; optional `retention_until` | Phase 3 |

Raw responses are not kept indefinitely by default: they can contain personal
data and grow without bound. See [PRIVACY](../PRIVACY.md).
