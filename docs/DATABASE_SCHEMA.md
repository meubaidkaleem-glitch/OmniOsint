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

## Part A — Implemented (Phase 1)

```
 users ──< user_roles >── roles ──< role_permissions >── permissions
   │
   └──< user_sessions

 audit_events          (append-only, no foreign keys by design)
 system_settings       (key/value)
 service_instances     (process heartbeats)
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
| analyst | Investigation work (permissions added as modules land) |
| auditor | Read-only access including the audit trail |
| viewer | Read-only access to what they are assigned |

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

---

## Part B — Target model (Phases 2 to 13)

### Investigations (Phase 3)

| Table | Purpose | Key columns |
|---|---|---|
| investigations | A case | id, case_ref (human-readable, unique), title, description, objective, status (`draft`, `planned`, `running`, `paused`, `awaiting_review`, `completed`, `archived`), created_by, assignee_id, tags, created_at, updated_at, archived_at, deleted_at, retention_until |
| investigation_members | Who may see and change a case | investigation_id, user_id, case_role |
| investigation_scopes | Authorisation for active work | id, investigation_id, mode (`passive`, `authorized_discovery`, `active_assessment`), authorization_note, authorization_evidence_file_id, valid_from, valid_until, approved_by |
| scope_rules | Individual targets and exclusions | scope_id, kind (`domain`, `wildcard`, `ip`, `cidr`, `url`, `port`, `protocol`), value, is_exclusion, restrictions (jsonb) |
| indicators | Inputs submitted to a case | id, investigation_id, raw_input, type, normalized_value, candidates (jsonb), created_by; unique per case and normalised value |
| findings | Analyst- or engine-stated conclusions | id, investigation_id, title, summary, category, severity, status, created_by, created_at |
| finding_evidence | Evidence supporting a finding | finding_id, evidence_id |
| analyst_notes | Notes on a case, entity, relationship, evidence item or finding | id, investigation_id, target_type, target_id, author_id, body, created_at, updated_at, deleted_at |
| saved_searches, search_history | Universal search | user_id, query, filters, created_at |

### Collection and providers (Phases 2 and 5)

| Table | Purpose | Key columns |
|---|---|---|
| providers | Registered adapters | id (slug), name, category, adapter_version, enabled, config (jsonb, non-secret), priority |
| provider_credentials | API keys, encrypted | id, provider_id, label, ciphertext, key_id, created_at, last_validated_at, status |
| provider_health | Latest and historical checks | provider_id, checked_at, status, latency_ms, detail, quota (jsonb) |
| provider_usage | Requests and cost per day | provider_id, day, endpoint, requests, credits, cost_estimate |
| evidence_sources | The source registry | id, slug, name, kind (`api`, `public_record`, `tool`, `upload`, `analyst`), provider_id, reliability, upstream_source_ids (lineage for independence analysis), terms_note |
| collection_jobs | The job queue and its history | id, investigation_id, indicator_id, module, provider_id, operation, status (`queued`, `awaiting_approval`, `running`, `succeeded`, `failed`, `cancelled`, `skipped`), priority, attempt, max_attempts, scheduled_at, started_at, finished_at, lease_owner, lease_expires_at, progress (jsonb), error (jsonb), requested_by, approved_by, cost_estimate, parent_job_id, dedup_key |
| collection_results | What a job returned | id, job_id, raw_object_key, raw_sha256, raw_size, content_type, normalized (jsonb), item_count, from_cache, received_at, expires_at |

`collection_jobs` is leased with `SELECT ... FOR UPDATE SKIP LOCKED`. A partial
index on `(priority, scheduled_at) WHERE status = 'queued'` keeps dequeueing
cheap however large the history grows.

### Evidence (Phase 2)

| Table | Purpose | Key columns |
|---|---|---|
| evidence | One attributable observation | id (v7), investigation_id, entity_id, relationship_id, source_id, provider_id, source_url, provider_object_id, collected_at, observed_at, verified_at, collection_result_id, normalized (jsonb), content_hash, verification_status, is_redacted, transformation_history (jsonb), created_at |

Evidence rows are never updated in place. A correction is a new row that
references the one it supersedes.

### Entities and graph (Phases 2 and 7)

| Table | Purpose | Key columns |
|---|---|---|
| entities | One row per real-world thing, shared by all cases | id, type (28 types from the brief), canonical_key, display_name, attributes (jsonb), first_observed_at, last_observed_at, merged_into_id, deleted_at; unique `(type, canonical_key)` |
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
| Raw provider responses | 90 days unless attached to a finding | `collection_results.expires_at` (Phase 2) |
| Cases | Until deleted; optional `retention_until` | Phase 3 |

Raw responses are not kept indefinitely by default: they can contain personal
data and grow without bound. See [PRIVACY](../PRIVACY.md).
