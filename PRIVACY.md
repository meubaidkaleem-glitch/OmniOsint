# Privacy

OmniOSINT processes information about organisations, infrastructure and,
sometimes, people. This document states what the software stores, where, what
leaves the machine, and the rules built into it. It describes the software; it
is not legal advice, and whoever operates OmniOSINT is responsible for having a
lawful basis for each investigation.

## Where data lives

Everything is stored locally, under the control of the person running it:

| Data | Location |
|---|---|
| Accounts, sessions, audit trail, search history, collection requests and jobs, evidence and entities, scopes; (from Phase 3) cases | The PostgreSQL database you configure |
| Configuration, logs, backups, secret store | The data directory: `%LOCALAPPDATA%\OmniOSINT` on Windows, `~/.local/share/OmniOSINT` on Linux |
| Raw provider responses (Phase 2) and uploaded files (Phase 9) | The data directory (`data/storage/objects`), encrypted at rest with AES-256-GCM under a key in the secret store |

OmniOSINT has no telemetry, analytics or update check. It does not contact any
server operated by the project.

## What leaves the machine

Only what an investigation requires, and only to the provider that serves it:

* **Today (Phase 2): nothing.** The collection pipeline exists, but no real
  provider is integrated, and the simulated provider contacts nothing.
  Classification always happens locally.
* **From Phase 4:** the indicator being investigated (for example a domain or
  an IP address) is sent to each provider selected in the collection plan, and
  to nobody else. The plan is shown before it runs and names every provider.
* **Some lookups disclose the target to third parties by their nature.**
  Submitting a URL to a scanning service, for instance, makes that service fetch
  it and may publish the result. Such operations are treated as active, shown as
  such, and need approval.
* **Cloud AI models (Phase 10)** receive case content only when a cloud model is
  configured and the analyst has consented for that case. A local-only mode
  prevents it entirely. Provider data-retention terms are shown before enabling.

## Rules built into the software

1. **Public and authorised sources only.** No access to private accounts,
   mailboxes, subscriber records or anything behind a login or access control.
2. **People are evidence-backed public references, not inferred identities.** A
   person entity exists only because a public source names them, and links to
   that source.
3. **Matches are candidates.** The same username, name, avatar or location never
   merges two records automatically. An analyst decides.
4. **Estimates are labelled.** IP geolocation is shown as approximate and never
   as an address. Carrier data is shown as range allocation, not subscriber
   identity.
5. **No tracking.** There is no live location tracking of people or phones.
6. **Sensitive values are redacted by default** in views, exports and logs.
   Credential-like fields in raw responses are masked; seeing them needs a
   separate permission and is audited. Credentials typed into a search are
   removed before anything is stored.
7. **AI output is never evidence.** Summaries link to the evidence they rest on,
   and unsupported statements are flagged.

## Retention and deletion

| Data | Default |
|---|---|
| Expired sessions | Removed 7 days after expiry |
| Audit trail | Kept; retention configurable from Phase 13 |
| Search history | The newest 200 searches per user; users can clear their own |
| Raw provider responses | 90 days (`collection.raw_retention_days`), then deleted; the evidence keeps their hash. Longer when attached to a finding, from Phase 3 |
| Cases | Until deleted; optional retention date (Phase 3) |

Deleting a user deactivates the account and keeps the username reserved, so
earlier audit entries remain attributable. Erasure of personal data inside cases
and secure deletion workflows arrive with case management (Phase 3) and
retention policies (Phase 13).

## Account data

For each user account OmniOSINT stores a username, a display name, an optional
email address, a password hash, sign-in timestamps, and for each session the IP
address and browser user agent as seen by the local server. Audit entries record
who did what and when.

## Backups

Backups contain the whole database, including password hashes and case data,
and, unless created with `--no-raw-responses`, the raw provider responses in
readable form. They are **not encrypted** in this phase. Store them on an
encrypted volume and control who can read them. Encrypted backups are planned
for Phase 13.
