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
whether the worker is alive. The worker also removes expired sessions (kept for
`worker.session_retention_days` after they end, 7 by default).

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

## Audit trail

Security-relevant actions are recorded in the `audit_events` table: sign-ins
(successful, failed, throttled), setup, logouts, session revocations, password
changes and resets, user creation, changes, lockouts and deletions, permission
denials, backups and restores. The table is append-only: database triggers
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
| `redis.url` | unset | Optional |
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
  `omniosint backup create` (cron). Archives are not encrypted.

## Exit codes of the command line

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | The operation failed |
| 2 | Usage error, or the feature is not implemented yet |
| 3 | Invalid configuration |
| 4 | A required service (the database) is unavailable |
| 130 | Interrupted |
