# OmniOSINT

An evidence-driven OSINT and intelligence investigation platform: collect from
lawful public and authorised sources, normalise everything into one entity and
relationship graph, keep the evidence behind every claim, and report it.

Windows 10/11 is the primary platform; Linux (including WSL2) is supported.

> **Project status: early development.** Phase 0 (architecture) is complete and
> Phase 1 (project foundation) is in progress. No intelligence module or
> provider integration exists yet. See [docs/ROADMAP.md](docs/ROADMAP.md) for
> the plan and [docs/FEATURE_INVENTORY.md](docs/FEATURE_INVENTORY.md) for the
> exact state of every feature.

## Principles

* **Evidence before conclusions.** Every finding links to a stored, attributable
  observation. Observed facts, inferred relationships and AI summaries are kept
  apart.
* **Safe by default.** Passive collection unless you define a scope and approve
  an active operation. The interface listens on the local machine only.
* **Honest about coverage.** A source that is not configured, not implemented or
  failing is shown as exactly that. No sample data is presented as a result.

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design and the decisions behind it |
| [docs/ROADMAP.md](docs/ROADMAP.md) | The fifteen phases and their acceptance criteria |
| [docs/FEATURE_INVENTORY.md](docs/FEATURE_INVENTORY.md) | Every feature, its phase and its status |
| [docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md) | Data model |
| [docs/PROVIDERS.md](docs/PROVIDERS.md) | Provider framework and catalogue |
| [docs/UI_NAVIGATION.md](docs/UI_NAVIGATION.md) | Interface structure |
| [docs/RISK_REGISTER.md](docs/RISK_REGISTER.md) | Known risks and mitigations |
| [SECURITY.md](SECURITY.md) | Security design and reporting |
| [PRIVACY.md](PRIVACY.md) | What is stored, where, and what leaves the machine |

## Responsible use

OmniOSINT is for lawful research and authorised security work. It does not
implement unauthorised account access, credential attacks, acquisition of
private subscriber records, tracking of people or phones, access-control bypass
or destructive testing, and it will not. You are responsible for having a
lawful basis and, for anything active, written authorisation.

## Licence

No licence has been chosen yet. Until the owner adds one, all rights are
reserved.
