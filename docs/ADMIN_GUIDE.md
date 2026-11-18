# Administrator guide

For whoever installs and looks after an OmniOSINT installation. Installation
itself is in [INSTALLATION.md](INSTALLATION.md).

## Processes

`start` launches two background processes and records them in
`run/state.json` in the data folder:

| Process | Command | Logs |
|---|---|---|
| API and web interface | `omniosint serve` | `logs/api.log`, `logs/api.out.log` |
| Background worker | `omniosint worker` | `logs/worker.log`, `logs/worker.out.log` |

`stop` asks both to shut down through a request file in `run/`, waits up to
`runtime.shutdown_timeout_seconds` (30 s by default), and only then terminates
what is left. `status` checks the recorded processes (by PID and creation time,
so a reused PID is never mistaken for OmniOSINT) and queries the readiness
endpoint.

Both processes write a heartbeat to the database; the system status page shows
whether the worker is alive. The worker runs collection jobs, and its
housekeeping removes expired sessions (kept for
`worker.session_retention_days` after they end, 7 by default) and raw provider
responses past their retention period.

**Collection needs the worker.** The API only plans and queues; if the worker
is not running, jobs stay queued. A job whose worker disappears (crash, power
loss) is recovered when its lease expires (`collection.job_lease_seconds`) and
retried or failed with the reason "worker lost".

## Health endpoints

| Endpoint | Meaning |
|---|---|
| `GET /api/v1/system/health/live` | The API process is running |
| `GET /api/v1/system/health/ready` | 200 when the database is usable (`ok` or `degraded`), 503 otherwise |
| `GET /api/v1/system/status` | Details; needs `system:read` |

`degraded` means an optional component (Redis, worker, web interface) is
unavailable or disk space is low.

## Accounts

* Create the first administrator through first-run setup, or with
  `omniosint admin create-user NAME` (no running server needed).
* Lost the only administrator password: `omniosint admin reset-password NAME`
  on the machine itself. It ends the user's sessions and clears any lockout.
* Sign-in lockout: `auth.max_failed_logins` (5) failures lock the account for
  `auth.lockout_minutes` (15). Sign-in attempts are also limited per address and
  username (`auth.login_rate_limit_per_minute`, 10).

## Collection

### The simulated provider

`collection.enable_simulated_provider: true` adds the simulated provider to
plans, for trying the pipeline before real providers exist (Phases 4 to 6). It
contacts nothing and generates data in documentation ranges only. Everything it
touches is stored with a simulated flag and labelled in the interface, the
command line and the API; the dashboard counts it apart from real records.
Leave it off on an installation used for real work, so plans are not cluttered
with test steps. Turning it off later does not delete what it produced; that
data stays labelled.

### Scopes and approvals

Active operations need a scope and an approval:

* **Recording a scope** (`scopes:manage`, administrators): name, mode
  (authorised discovery, or active assessment, which also permits assessment),
  who authorised it, a reference, validity (at most a year), targets and
  exclusions, and the statement that written authorisation exists for every
  target. In the interface: **Administration > Scopes**; on the command line:
  `omniosint scopes create --name ... --authorized-by ... --rule cidr=198.51.100.0/24
  --exclude ip=198.51.100.66 --confirm-authorization`.
* Targets: `domain` (the domain and its subdomains), `wildcard` (`*.example.com`,
  subdomains only), `ip`, `cidr` (no broader than /8 for IPv4 or /16 for IPv6)
  and `url_prefix`. Exclusions always win.
* **Revoking** a scope stops every job that depends on it at its next check.
  Scopes cannot be deleted, so past active jobs stay explained.
* **Approving** an active job (`collection:approve`) is a separate, audited
  step. The scope is checked when the plan is made, when the job is approved
  and immediately before it runs.

### Collection settings

| Setting | Default | Notes |
|---|---|---|
| `collection.enable_simulated_provider` | false | See above |
| `collection.default_phone_region` | unset | ISO 3166 code (`GB`) assumed for phone numbers without a country code |
| `collection.raw_retention_days` | 90 | Raw responses are deleted after this; evidence keeps their hashes |
| `collection.max_concurrent_jobs` | 4 | Jobs one worker runs at a time |
| `collection.max_attempts` | 3 | Attempts for retryable failures |
| `collection.retry_base_seconds` / `retry_max_seconds` | 5 / 300 | Exponential backoff with jitter; a provider's Retry-After is respected |
| `collection.approval_credit_threshold` | 0 | Paid calls estimated above this many credits wait for approval (0: all of them) |
| `collection.rate_limit_max_wait_seconds` | 30 | Longest wait for a provider's rate limit before the call fails as rate limited |
| `collection.http_timeout_seconds` / `http_max_response_bytes` | 30 / 10 MiB | Limits of the outbound HTTP client |

Outbound provider requests never go to loopback, private, link-local or other
special-use addresses, whatever a name resolves to. This is not configurable in
Phase 2; authorised internal discovery arrives with Phase 8.

## Audit trail

Security-relevant actions are recorded in the `audit_events` table: sign-ins
(successful, failed, throttled), setup, logouts, session revocations, password
changes and resets, user creation, changes, lockouts and deletions, permission
denials, backups and restores, collection requests, approvals, cancellations
and retries, scope creation, rule changes, checks and revocations, and every
unmasked view of a raw response. The table is append-only: database triggers
reject updates, deletes and truncation. Entries never contain passwords,
tokens or secrets.

A restore replaces the audit trail with the one in the backup (see
[INSTALLATION.md](INSTALLATION.md#backup-and-restore)).

## Configuration reference

All settings with their defaults are in `config/settings.yaml` and
`config/logging.yaml`; `omniosint config show` prints the effective values with
secrets masked. Notable ones:

| Setting | Default | Notes |
|---|---|---|
| `server.host` | `127.0.0.1` | Non-loopback addresses are refused unless `server.allow_non_loopback` is true |
| `server.port` | `8765` | |
| `server.allowed_hosts` | `127.0.0.1, localhost, ::1` | Host header allow-list (DNS-rebinding defence) |
| `server.cors_origins` | empty | Extra browser origins; only for development |
| `database.*` | local `omniosint` database | Password through the secret store or environment |
| `database.pg_bin_dir` | auto-detected | Folder of `pg_dump`, `pg_restore`, `psql` |
| `redis.url` | unset | Optional. When set, provider rate limits are shared through it |
| `auth.session_ttl_hours` / `auth.session_idle_minutes` | 12 / 120 | |
| `auth.cookie_secure` | false | Set to true only behind an HTTPS reverse proxy |
| `logging.level` | `INFO` | |

### Exposing the interface to other machines

Not recommended, and off by default. OmniOSINT has no TLS of its own. If you
must, put it behind a reverse proxy that terminates TLS, and set
`server.host`, `server.allow_non_loopback: true`, `server.allowed_hosts` (the
public host name) and `auth.cookie_secure: true`. `omniosint doctor` warns about
this configuration.

## Database maintenance

* `omniosint db current` shows the schema revision; `omniosint db upgrade`
  applies migrations and refreshes built-in roles and permissions. Run it after
  every update (`update.bat` does).
* Regular backups: schedule `backup.bat` (Windows Task Scheduler) or
  `omniosint backup create` (cron). Archives are not encrypted, and they
  include the raw provider responses in readable form; add
  `--no-raw-responses` to leave those out. A restore writes the raw responses
  back encrypted under the local key and removes stored ones the restored
  database does not refer to.

## Exit codes of the command line

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | The operation failed |
| 2 | Usage error, or the feature is not implemented yet |
| 3 | Invalid configuration |
| 4 | A required service (the database) is unavailable |
| 130 | Interrupted |
