# API reference

Generated from the OpenAPI document by `scripts/dev/gen_docs.py`. Do not edit by
hand. The live document is served at `/api/v1/openapi.json`; interactive
documentation is available at `/api/docs` in development mode.

API version: `0.1.0`

## Conventions

* Base path: `/api/v1`. All request and response bodies are JSON.
* **Authentication**: a session cookie (browsers) or
  `Authorization: Bearer <token>` (CLI, desktop, scripts). Obtain either from
  `POST /api/v1/auth/login`.
* **CSRF**: cookie-authenticated `POST`, `PUT`, `PATCH` and `DELETE` requests
  must send the `X-CSRF-Token` header with the value returned by login or
  `GET /api/v1/auth/me`. Bearer-authenticated requests do not need it.
* **Errors** use one envelope:

  ```json
  { "error": { "code": "permission_denied", "message": "...",
               "details": [], "request_id": "..." } }
  ```

  `code` is stable and safe to branch on; `message` is for people.
* **Pagination**: list endpoints take `limit` (1 to 200, default 50) and an
  opaque `cursor`, and return `items` and `next_cursor` (null on the last page).
* Every response carries an `X-Request-ID` header; quote it when reporting a
  problem.

## auth

First-run setup, sign-in and the caller's own account.

### `GET /api/v1/auth/setup-status`

**Whether first-run setup is still needed**

No authentication required.

Responses: `200` `SetupStatus`

### `POST /api/v1/auth/setup`

**Create the first administrator**

Works exactly once, while no user exists, and only with the setup token that OmniOSINT wrote to a file readable by the installing user.

No authentication required.

Request body: `SetupRequest`

Responses: `201` `SetupResponse`, `403` `ErrorResponse`, `409` `ErrorResponse`, `429` `ErrorResponse`

### `POST /api/v1/auth/login`

**Sign in**

No authentication required.

Request body: `LoginRequest`

Responses: `200` `LoginResponse`, `401` `ErrorResponse`, `429` `ErrorResponse`

### `POST /api/v1/auth/logout`

**Sign out**

Requires a signed-in user.

Responses: `204`, `401` `ErrorResponse`

### `GET /api/v1/auth/me`

**The signed-in user, their permissions and CSRF token**

Requires a signed-in user.

Responses: `200` `AuthState`, `401` `ErrorResponse`

### `POST /api/v1/auth/change-password`

**Change your password**

Ends every other session of the same user.

Requires a signed-in user.

Request body: `ChangePasswordRequest`

Responses: `200` `ChangePasswordResponse`, `401` `ErrorResponse`

### `GET /api/v1/auth/sessions`

**Your active sessions**

Requires a signed-in user.

Responses: `200` `SessionList`, `401` `ErrorResponse`

### `DELETE /api/v1/auth/sessions/{session_id}`

**End one of your sessions**

Requires a signed-in user.

| Parameter | In | Required | Description |
|---|---|---|---|
| `session_id` | path | yes |  |

Responses: `204`, `401` `ErrorResponse`, `404` `ErrorResponse`

## admin

User accounts, roles and the audit trail.

### `GET /api/v1/admin/users`

**List users**

Requires permission: `users:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `limit` | query | no | Maximum number of items to return. |
| `cursor` | query | no | Opaque cursor from a previous page's `next_cursor`. |
| `search` | query | no | Matches username, display name or email. |

Responses: `200` `UserList`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `POST /api/v1/admin/users`

**Create a user**

Requires permission: `users:manage`

Request body: `UserCreate`

Responses: `201` `UserOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `409` `ErrorResponse`

### `GET /api/v1/admin/users/{user_id}`

**Get a user**

Requires permission: `users:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `user_id` | path | yes |  |

Responses: `200` `UserOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`

### `PATCH /api/v1/admin/users/{user_id}`

**Change a user**

Only the fields sent are changed. A change that would leave no active administrator is refused.

Requires permission: `users:manage`

| Parameter | In | Required | Description |
|---|---|---|---|
| `user_id` | path | yes |  |

Request body: `UserUpdate`

Responses: `200` `UserOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`

### `DELETE /api/v1/admin/users/{user_id}`

**Delete a user**

The account is deactivated and can no longer sign in. Its username stays reserved so that earlier audit entries remain unambiguous.

Requires permission: `users:manage`

| Parameter | In | Required | Description |
|---|---|---|---|
| `user_id` | path | yes |  |

Responses: `204`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`

### `POST /api/v1/admin/users/{user_id}/reset-password`

**Set a new password for a user**

Ends all of the user's sessions and clears any lockout.

Requires permission: `users:manage`

| Parameter | In | Required | Description |
|---|---|---|---|
| `user_id` | path | yes |  |

Request body: `PasswordReset`

Responses: `200` `UserOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`

### `POST /api/v1/admin/users/{user_id}/unlock`

**Clear a sign-in lockout**

Requires permission: `users:manage`

| Parameter | In | Required | Description |
|---|---|---|---|
| `user_id` | path | yes |  |

Responses: `200` `UserOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`

### `GET /api/v1/admin/roles`

**List roles and their permissions**

Requires permission: `roles:read`

Responses: `200` `RoleList`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `GET /api/v1/admin/audit-events`

**Read the audit trail**

Newest first.

Requires permission: `audit:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `limit` | query | no | Maximum number of items to return. |
| `cursor` | query | no | Opaque cursor from a previous page's `next_cursor`. |
| `category` | query | no |  |
| `action` | query | no |  |
| `outcome` | query | no |  |
| `actor_user_id` | query | no |  |
| `since` | query | no | Inclusive lower bound. |
| `until` | query | no | Exclusive upper bound. |

Responses: `200` `AuditEventList`, `401` `ErrorResponse`, `403` `ErrorResponse`

## system

Health, version, the feature registry and system status.

### `GET /api/v1/system/health/live`

**Liveness: the API process is running**

No authentication required.

Responses: `200` `LiveResponse`

### `GET /api/v1/system/health/ready`

**Readiness: the API can serve requests**

Returns 200 when the database is reachable and its schema is current (status `ok` or `degraded`), otherwise 503. Component names and states only; details are in `/system/status`.

No authentication required.

Responses: `200` `ReadyResponse`, `503` `ReadyResponse`

### `GET /api/v1/system/info`

**Service name, version and whether first-run setup is pending**

No authentication required.

Responses: `200` `SystemInfo`

### `GET /api/v1/system/features`

**What is available and what is planned**

The feature registry. The interface uses it to show unbuilt sections as planned instead of presenting controls that do nothing.

Requires a signed-in user.

Responses: `200` `FeatureList`, `401` `ErrorResponse`

### `GET /api/v1/system/status`

**Detailed system and service status**

Requires permission: `system:read`

Responses: `200` `SystemStatus`, `401` `ErrorResponse`, `403` `ErrorResponse`

## dashboard

Dashboard data. Every number is a database record.

### `GET /api/v1/dashboard`

**Dashboard data**

Requires a signed-in user.

Responses: `200` `DashboardResponse`, `401` `ErrorResponse`

## providers

The provider catalogue. Read-only: no provider integration is implemented yet.

### `GET /api/v1/providers`

**List the provider catalogue**

The inventory of data sources and tools the platform is designed to integrate, each with its real status. `counts` and `categories` describe the whole catalogue, not only the filtered items.

Requires a signed-in user.

| Parameter | In | Required | Description |
|---|---|---|---|
| `category` | query | no |  |
| `status` | query | no |  |
| `q` | query | no | Matches name, identifier or notes. |

Responses: `200` `ProviderList`, `401` `ErrorResponse`

### `GET /api/v1/providers/adapters`

**List installed adapters and their state**

Adapters are the code that can collect. Each has its real status, circuit breaker state, capabilities and today's usage.

Requires permission: `collection:read`

Responses: `200` `AdapterList`, `401` `ErrorResponse`, `403` `ErrorResponse`, `503` `ErrorResponse`

### `POST /api/v1/providers/{provider_id}/health`

**Run a provider's health check**

Only adapters can be checked; catalogue entries report their planned status.

Requires permission: `collection:run`

| Parameter | In | Required | Description |
|---|---|---|---|
| `provider_id` | path | yes |  |

Responses: `200` `HealthOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `503` `ErrorResponse`

### `GET /api/v1/providers/{provider_id}`

**Get one catalogue entry**

Requires a signed-in user.

| Parameter | In | Required | Description |
|---|---|---|---|
| `provider_id` | path | yes |  |

Responses: `200` `ProviderOut`, `401` `ErrorResponse`, `404` `ErrorResponse`

## collection

### `POST /api/v1/collection/plan`

**Preview a collection plan**

What would run for the input, and why each provider would or would not be used. Nothing is collected. An ambiguous input needs `type`.

Requires permission: `collection:read`

Request body: `PlanRequest`

Responses: `200` `PlanOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `503` `ErrorResponse`

### `POST /api/v1/collection/requests`

**Submit a collection request**

Computes the plan again and queues every step that can run. Active operations and paid calls above the threshold wait for approval.

Requires permission: `collection:run`

Request body: `PlanRequest`

Responses: `201` `RequestOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `503` `ErrorResponse`

### `GET /api/v1/collection/requests`

**List collection requests**

Requires permission: `collection:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `limit` | query | no |  |
| `cursor` | query | no |  |

Responses: `200` `RequestList`, `401` `ErrorResponse`, `403` `ErrorResponse`, `503` `ErrorResponse`

### `GET /api/v1/collection/requests/{request_id}`

**Get a collection request, its plan and its jobs**

Requires permission: `collection:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `request_id` | path | yes |  |

Responses: `200` `RequestDetailOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `503` `ErrorResponse`

### `POST /api/v1/collection/requests/{request_id}/cancel`

**Cancel every unfinished job of a request**

Requires permission: `collection:run`

| Parameter | In | Required | Description |
|---|---|---|---|
| `request_id` | path | yes |  |

Responses: `200` `RequestOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`, `503` `ErrorResponse`

### `GET /api/v1/collection/jobs`

**List jobs (the job history)**

Requires permission: `collection:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `status` | query | no |  |
| `provider` | query | no |  |
| `limit` | query | no |  |
| `cursor` | query | no |  |

Responses: `200` `JobList`, `401` `ErrorResponse`, `403` `ErrorResponse`, `503` `ErrorResponse`

### `GET /api/v1/collection/jobs/{job_id}`

**Get a job with its history and results**

Requires permission: `collection:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `job_id` | path | yes |  |

Responses: `200` `JobDetailOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `503` `ErrorResponse`

### `POST /api/v1/collection/jobs/{job_id}/approve`

**Approve a job that waits for approval**

Active operations are checked against their scope again before approval.

Requires permission: `collection:approve`

| Parameter | In | Required | Description |
|---|---|---|---|
| `job_id` | path | yes |  |

Responses: `200` `JobOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`, `503` `ErrorResponse`

### `POST /api/v1/collection/jobs/{job_id}/cancel`

**Cancel a job**

Requires permission: `collection:run`

| Parameter | In | Required | Description |
|---|---|---|---|
| `job_id` | path | yes |  |

Responses: `200` `JobOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`, `503` `ErrorResponse`

### `POST /api/v1/collection/jobs/{job_id}/retry`

**Retry a failed or cancelled job**

An active operation goes back to waiting for approval.

Requires permission: `collection:run`

| Parameter | In | Required | Description |
|---|---|---|---|
| `job_id` | path | yes |  |

Responses: `200` `JobOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`, `503` `ErrorResponse`

## evidence

### `GET /api/v1/evidence`

**List evidence**

Newest first. Simulated evidence is included and flagged unless excluded.

Requires permission: `evidence:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `entity_id` | query | no |  |
| `job_id` | query | no |  |
| `include_simulated` | query | no |  |
| `limit` | query | no |  |
| `cursor` | query | no |  |

Responses: `200` `EvidenceList`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `GET /api/v1/evidence/{evidence_id}`

**Get evidence with its entity, source and integrity**

Requires permission: `evidence:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `evidence_id` | path | yes |  |

Responses: `200` `EvidenceDetailOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`

### `GET /api/v1/evidence/{evidence_id}/raw`

**The raw response behind evidence**

Credential-like fields are masked. `unmasked=true` needs the `evidence:read_raw` permission and is recorded in the audit trail. A response that is not JSON cannot be masked, so it is shown only unmasked (409 `raw_not_maskable` otherwise).

Requires permission: `evidence:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `evidence_id` | path | yes |  |
| `unmasked` | query | no |  |

Responses: `200` `RawOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`

### `GET /api/v1/entities`

**List entities**

Requires permission: `evidence:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `type` | query | no |  |
| `search` | query | no |  |
| `limit` | query | no |  |
| `cursor` | query | no |  |

Responses: `200` `EntityList`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `GET /api/v1/entities/{entity_id}`

**Get an entity**

Requires permission: `evidence:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `entity_id` | path | yes |  |

Responses: `200` `EntityOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`

### `GET /api/v1/sources`

**The source registry**

Every source evidence can be attributed to, with its lineage.

Requires permission: `evidence:read`

Responses: `200` `SourceList`, `401` `ErrorResponse`, `403` `ErrorResponse`

## scopes

### `GET /api/v1/scopes`

**List scopes**

Requires permission: `scopes:read`

Responses: `200` `ScopeList`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `POST /api/v1/scopes`

**Record a scope of written authorisation**

Creating a scope states that written authorisation exists for every target it lists (`authorization_confirmed` must be true). It is recorded in the audit trail.

Requires permission: `scopes:manage`

Request body: `ScopeIn`

Responses: `201` `ScopeDetailOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`

### `GET /api/v1/scopes/{scope_id}`

**Get a scope and its rules**

Requires permission: `scopes:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `scope_id` | path | yes |  |

Responses: `200` `ScopeDetailOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`

### `POST /api/v1/scopes/{scope_id}/rules`

**Add a target or an exclusion**

Requires permission: `scopes:manage`

| Parameter | In | Required | Description |
|---|---|---|---|
| `scope_id` | path | yes |  |

Request body: `ScopeRuleIn`

Responses: `201` `ScopeDetailOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`

### `DELETE /api/v1/scopes/{scope_id}/rules/{rule_id}`

**Remove a rule**

Requires permission: `scopes:manage`

| Parameter | In | Required | Description |
|---|---|---|---|
| `scope_id` | path | yes |  |
| `rule_id` | path | yes |  |

Responses: `200` `ScopeDetailOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`

### `POST /api/v1/scopes/{scope_id}/revoke`

**Revoke a scope**

Scopes are never deleted, so the authority behind past operations stays on record.

Requires permission: `scopes:manage`

| Parameter | In | Required | Description |
|---|---|---|---|
| `scope_id` | path | yes |  |

Request body: `RevokeIn`

Responses: `200` `ScopeDetailOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`, `409` `ErrorResponse`

### `POST /api/v1/scopes/{scope_id}/check`

**Check whether a target is in scope**

Answers what the scope manager would decide now. Nothing is run.

Requires permission: `scopes:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `scope_id` | path | yes |  |

Request body: `ScopeCheckIn`

Responses: `200` `ScopeDecisionOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`

## search

### `POST /api/v1/search/classify`

**Classify an input**

Detects which of the 24 input types the input is, validates and normalises it. An ambiguous input returns every reading with `status` = `ambiguous`; nothing is guessed. Nothing is collected and no provider is contacted.

Requires permission: `collection:read`

Request body: `ClassifyRequest`

Responses: `200` `ClassificationOut`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `GET /api/v1/search/types`

**List the supported input types**

Requires permission: `collection:read`

Responses: `200` `InputTypeList`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `GET /api/v1/search/history`

**Your search history**

Requires permission: `collection:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `limit` | query | no |  |

Responses: `200` `HistoryList`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `DELETE /api/v1/search/history`

**Clear your search history**

Requires permission: `collection:read`

Responses: `204`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `GET /api/v1/search/saved`

**Your saved searches**

Requires permission: `collection:read`

Responses: `200` `SavedSearchList`, `401` `ErrorResponse`, `403` `ErrorResponse`

### `POST /api/v1/search/saved`

**Save a search**

Requires permission: `collection:read`

Request body: `SavedSearchIn`

Responses: `201` `SavedSearchOut`, `401` `ErrorResponse`, `403` `ErrorResponse`, `409` `ErrorResponse`

### `DELETE /api/v1/search/saved/{saved_id}`

**Delete a saved search**

Requires permission: `collection:read`

| Parameter | In | Required | Description |
|---|---|---|---|
| `saved_id` | path | yes |  |

Responses: `204`, `401` `ErrorResponse`, `403` `ErrorResponse`, `404` `ErrorResponse`
