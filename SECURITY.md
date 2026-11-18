# Security

This document describes how OmniOSINT is secured, what it assumes, and how to
report a problem. It covers what is implemented today and marks what is planned.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private
vulnerability reporting on this repository (Security tab, "Report a
vulnerability"). Include the version, the platform, and steps to reproduce.

## Scope and assumptions

OmniOSINT is a **local application**. The supported deployment is one machine,
with the API listening on the loopback interface and the database on the same
machine or a trusted network.

Trusted: the operating-system account that installs and runs OmniOSINT, and the
PostgreSQL server it is configured to use.

Not trusted: web pages open in the user's browser, other devices on the network,
content returned by providers, uploaded files, and (from Phase 10) model output.

Out of scope: an attacker with administrative control of the machine, or with
the OmniOSINT user's own operating-system session.

## Threats and controls

| Threat | Control | Status |
|---|---|---|
| Another device connects to the interface | Binds `127.0.0.1` only. A non-loopback address is refused unless `server.allow_non_loopback` is set, and `omniosint doctor` reports it | Implemented |
| A web page makes the browser talk to the local API by DNS rebinding | Requests whose `Host` header is not on the allow-list are rejected | Implemented |
| A web page submits a cross-site request | `Origin` must match the server; session cookie is `SameSite=Strict` and `HttpOnly`; unsafe requests need a CSRF token; request bodies must be JSON | Implemented |
| Someone creates the first administrator before the owner does | First-run setup needs a token written to a file only the installing user can read | Implemented |
| Password guessing | Argon2id hashes; per-client throttle; account lockout after repeated failures; identical responses for unknown user, wrong password and locked account | Implemented |
| Stolen database dump reveals sessions | Only SHA-256 hashes of session tokens are stored | Implemented |
| Privilege misuse | Every endpoint declares the permission it needs; denials are audited | Implemented |
| Tampering with the audit trail | A database trigger blocks updates and unplanned deletes | Implemented |
| Secrets read from disk | AES-256-GCM with a master key protected by Windows DPAPI (user scope) | Implemented |
| Script injection in the interface | React escaping; strict Content Security Policy with no inline scripts and no third-party origins; `nosniff`; framing denied | Implemented |
| Information leakage in errors and logs | Generic error messages with a request id; stack traces stay in logs; log redaction for credentials | Implemented |
| Oversized requests | Body size limit | Implemented |
| Server-side request forgery | Every provider request goes through one HTTP client: http and https only, no credentials in URLs, no proxy settings from the environment. Each address a name resolves to is checked against a destination policy (no loopback, private, link-local, multicast, reserved or other special-use ranges, including IPv4 embedded in IPv6) and the connection goes to the checked address, so DNS rebinding cannot redirect it; redirects are checked again | Implemented |
| Oversized or hostile provider responses | Response size cap and timeouts; observations validated against a schema; raw responses shown as data, never rendered as HTML | Implemented |
| Active operations outside authorisation | Scope manager: an active job must name a recorded scope (database constraint), and the scope is checked when the plan is made, when the job is approved and again immediately before it runs; every check is in the job history and the audit trail. Active jobs always wait for approval | Implemented |
| Runaway or costly collection | Per-provider rate limits, circuit breaker, bounded retries for retryable errors only, page and result caps, approval for paid calls above a threshold | Implemented |
| Raw responses read from disk | AES-256-GCM under a key held in the secret store; file names are an HMAC of the content hash, so a listing reveals nothing | Implemented |
| Evidence altered after collection | Evidence rows are append-only (database triggers); each carries a hash of its content and of the raw response, and the integrity check recomputes both | Implemented |
| Credentials exposed in raw responses | Credential-like fields are masked in the raw view; the unmasked view needs `evidence:read_raw` and is audited, and a response that cannot be masked is shown only unmasked | Implemented |
| Credentials pasted into a search | Removed from any input before classification (`scheme://user:pass@` forms); never stored in search history | Implemented |
| Test data mistaken for findings | The simulated provider is off by default; whether data is simulated comes from the provider's registration, is stored on every record and shown everywhere; dashboards count it separately | Implemented |
| Malicious files | Type detection, limits, sandboxed parsing, no execution | Planned, Phase 9 |
| Data sent to cloud models | Local-only mode, explicit consent | Planned, Phase 10 |
| Encrypted backups | Passphrase encryption | Planned, Phase 13 |

## Authentication and sessions

* Passwords are hashed with Argon2id (64 MiB, 3 iterations, 4 lanes by default)
  and re-hashed on sign-in if parameters are raised.
* Password rules: at least 12 characters (configurable, never below 8), not
  containing the username or product name, at least five distinct characters.
  No forced composition rules or periodic expiry.
* A session is a random 256-bit token. Browsers receive it in an `HttpOnly`,
  `SameSite=Strict` cookie; the CLI and desktop shell use it as a bearer token.
* Sessions expire after 12 hours, or after 2 hours without activity. Changing a
  password ends the user's other sessions; an administrator reset ends all of
  them and forces a change at next sign-in.
* Users can see and revoke their own sessions.

## Authorisation

Permissions are `resource:action` strings grouped into roles. Built-in roles are
defined in code and synchronised to the database on upgrade. The system refuses
any change that would leave it without an active administrator.

## Secrets

* Never in YAML configuration, logs, API responses or the repository.
* Provided by environment variable, or stored with `omniosint secrets set`.
* The secret store encrypts each value with AES-256-GCM. The master key is
  protected by DPAPI on Windows. On Linux it is a file with owner-only
  permissions, which is weaker and is reported as such by `omniosint doctor`.
* A secret stored on one Windows account cannot be decrypted by another account
  or on another machine. Backups therefore do not carry usable secrets; they
  are re-entered after a restore elsewhere.

## Collection policy

OmniOSINT separates passive collection of public information from active
security testing. The default mode is passive.

Not implemented, and not planned: unauthorised account access, credential theft,
password guessing against third-party accounts, acquisition of private
subscriber records, phone tracking, private-account surveillance, access-control
bypass, destructive testing, malware execution, use or validation of discovered
secrets, circumvention of provider restrictions, and scraping of restricted
information.

Every active operation passes the scope manager (implemented in Phase 2). A
scope is recorded with a statement that written authorisation exists, who gave
it and until when; it lists targets (domains, wildcards, addresses, networks no
broader than /8 or /16, URL prefixes) and exclusions, which always win. The
manager checks that the scope is approved, unrevoked and valid at that moment,
that it permits the kind of operation, and that it covers the whole target and
excludes none of it. It runs when the plan is made, when the job is approved
and again immediately before the job runs, and each decision is recorded in
the job history and the audit trail. Active jobs always need an approval from
someone with `collection:approve`. Scopes are revoked, never deleted, so every
past active job stays explained.

## Development practices

* Dependencies are pinned with hashes; `pip-audit` and `npm audit` run in CI.
* Linting includes security rules (ruff `S` rules).
* Security tests live in `tests/security/` and run with every build.
* Database access uses bound parameters throughout; there is no string-built SQL
  on user input.

## Known limitations

* Backups are not encrypted (Phase 13), and they contain the raw provider
  responses in readable form (the key that protects them on disk cannot leave
  the secret store). Keep backups on an encrypted volume, or leave the raw
  responses out with `omniosint backup create --no-raw-responses`.
* A restore removes stored raw responses that the restored database does not
  refer to, so none escapes its retention period. The automatic pre-restore
  backup keeps them.
* Masking of raw responses is by field name in JSON responses. A credential
  stored under an unexpected name is not recognised.
* The scope manager checks a target as given. No active capability exists yet
  that contacts anything (the simulated probe contacts nothing); when real
  ones arrive (Phases 5 and 8), a domain target's resolved addresses will have
  to pass the scope too.
* Restoring a backup restores its audit trail as well; entries recorded after
  the backup was taken are kept only in the automatic pre-restore backup.
* On Linux the secret store's master key is protected by file permissions only;
  `omniosint doctor` reports this.
* The sign-in throttle is kept in memory by the API. OmniOSINT runs a single API
  process, so it covers every attempt, but it starts empty when the API
  restarts. Account lockout is stored in the database and is not affected.
* TLS is not terminated by OmniOSINT. It is designed for loopback use; anyone
  placing it behind a reverse proxy is responsible for TLS and must set
  `auth.cookie_secure`.
* Interactive API documentation (Swagger UI) loads assets from a public CDN and
  is therefore enabled only in development mode. The OpenAPI document itself is
  always available at `/api/v1/openapi.json`.
