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
| Accounts, sessions, audit trail, and (from Phase 3) cases and evidence | The PostgreSQL database you configure |
| Configuration, logs, backups, secret store | The data directory: `%LOCALAPPDATA%\OmniOSINT` on Windows, `~/.local/share/OmniOSINT` on Linux |
| Raw provider responses and uploaded files (from Phase 2) | The data directory, encrypted at rest |

OmniOSINT has no telemetry, analytics or update check. It does not contact any
server operated by the project.

## What leaves the machine

Only what an investigation requires, and only to the provider that serves it:

* **Today (Phase 1): nothing.** No provider integration exists yet.
* **From Phase 2:** the indicator being investigated (for example a domain or an
  IP address) is sent to each provider selected in the collection plan. The plan
  is shown before it runs.
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
6. **Sensitive values are redacted by default** in views, exports and logs
   (from Phase 2 for evidence; credentials already).
7. **AI output is never evidence.** Summaries link to the evidence they rest on,
   and unsupported statements are flagged.

## Retention and deletion

| Data | Default |
|---|---|
| Expired sessions | Removed 7 days after expiry |
| Audit trail | Kept; retention configurable from Phase 13 |
| Raw provider responses | 90 days unless attached to a finding (Phase 2) |
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

Backups contain the whole database, including password hashes and case data, and
are **not encrypted** in this phase. Store them on an encrypted volume and
control who can read them. Encrypted backups are planned for Phase 13.
