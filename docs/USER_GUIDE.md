# User guide

This guide covers what OmniOSINT can do today (Phase 1). Intelligence features
are added phase by phase; until then their sections in the interface say
**Planned — not yet implemented** and name the phase that delivers them.

## Signing in

Open the address printed by `start.bat` (normally <http://127.0.0.1:8765>).

* **First run.** The first start opens the setup page with a one-time token.
  Create the first administrator account there. If you lost the link, run
  `omniosint admin setup-token` on the same computer.
* **Sign-in.** Use your username and password. After five wrong passwords in a
  row the account is locked for 15 minutes; an administrator can unlock it
  earlier.
* **Temporary passwords.** If an administrator created your account or reset
  your password, you are asked to choose a new one before anything else.

Passwords need at least 12 characters, at least five different characters, and
must not contain your username. Several unrelated words make a good password.

Sessions end after 2 hours without activity, or 12 hours after sign-in.

## The interface

* **Sidebar.** The twenty sections of OmniOSINT, grouped into Intelligence,
  Analysis, Operations and Platform. Sections not built yet are dimmed and show
  their phase (for example `P5`). Groups can be collapsed; the sidebar becomes
  an icon rail on narrow windows.
* **Command palette.** Press **Ctrl+K** (Cmd+K on a Mac) to jump to any section
  or run an action (switch theme, sign out).
* **Status indicator.** The dot in the top bar shows the overall system status.
* **Account menu.** Your account, the theme (dark or light) and sign-out.

If the OmniOSINT service stops while the page is open, a red banner says so and
the page reconnects automatically once it is running again.

## Dashboard

* Counts from the database: your active sessions, and for administrators active
  accounts and sign-ins in the last 24 hours.
* **System health**: database, Redis, background worker, data folder and web
  interface.
* **Recent activity** from the audit log (everyone's for auditors and
  administrators, only your own otherwise).
* **Platform coverage**: how many sections and provider integrations exist.
* **Not yet available**: figures such as investigations or alerts that need
  modules not built yet. They are listed with their phase and never shown as
  zero.

## Integrations

The catalogue of data sources and tools OmniOSINT is designed to use (Shodan,
Censys, VirusTotal, NVD and many more), with each one's access model, the phase
that integrates it, and notes about tiers and limits. Filter by category,
status or text.

No provider can be configured or queried yet; credentials, health checks and
quotas arrive with the first integrations.

## Administration and Settings

What you see depends on your role.

| Page | Who | What |
|---|---|---|
| My account | Everyone | Profile, permissions, password change, theme, active sessions (end any of them) |
| Users | `users:read`; changes need `users:manage` | Create, edit, deactivate, delete, reset passwords, clear lockouts |
| Roles | `roles:read` | The built-in roles and their permissions |
| Audit log | `audit:read` | Every security-relevant action; filter and open an entry for its details |
| System status | `system:read` | Component checks, version, runtime and data folder |

Built-in roles:

| Role | Purpose |
|---|---|
| administrator | Everything, including user management |
| auditor | Read-only, including the audit log and system status |
| analyst | Investigation work (permissions arrive with the intelligence modules) |
| viewer | Read-only access to what they are assigned |

OmniOSINT never lets the last active administrator be deactivated, demoted or
deleted. A deleted account cannot sign in again and its username cannot be
reused, so the audit log stays unambiguous.

## Command line

Everything the scripts do is available as `omniosint` (inside `.venv`):

```text
omniosint start | stop | restart | status
omniosint doctor
omniosint db check | upgrade | current | bootstrap
omniosint admin create-user | list-users | reset-password | setup-token
omniosint secrets set | list | delete
omniosint config show | paths | validate | set | unset
omniosint backup create | list | verify | restore
omniosint providers list | test
omniosint openapi
```

Commands for features that are not built (`search`, `investigate`, `cases`,
`graph`, `report`, `reports`, `monitoring`) say so and exit with status 2.
`omniosint providers test` lists the providers without testing any, because no
integration exists yet, and also exits with status 2 so scripts cannot mistake
it for a successful check.
