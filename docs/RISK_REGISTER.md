# Risk register

Likelihood and impact are rated Low, Medium or High. "Owner phase" is where the
mitigation is built or the risk is re-examined. Reviewed at the end of every
phase.

## Technical risks

| ID | Risk | L | I | Mitigation | Owner phase | State |
|---|---|---|---|---|---|---|
| T-01 | Windows behaviour differs from the Linux build environment (process control, paths, DPAPI, event loop) | High | High | One lifecycle implementation in Python with no reliance on POSIX signals; Windows job in CI that installs, starts, health-checks, backs up, restores and stops the app and runs the test suite; DPAPI round-trip test that runs only on Windows | 1 | **Open** — Windows scripts reviewed and type-checked but not executed by the developer; confirm with the CI `windows` job |
| T-02 | PostgreSQL is a heavy prerequisite for a desktop user | Medium | Medium | Installer detects an existing server, offers `winget` or Docker with consent; managed portable PostgreSQL considered for the packaged installer | 1, 14 | Open |
| T-03 | No official Redis build for Windows | High | Low | Redis is optional; in-process fallbacks for cache and rate limiting; job queue lives in PostgreSQL | 1, 2 | Mitigated by design |
| T-04 | Celery is unsupported on Windows | High | Medium | PostgreSQL-backed queue with asyncio workers (ADR-004) | 2 | Mitigated by design |
| T-05 | Async database driver conflicts with subprocess support on Windows | Medium | High | asyncpg, which works on the proactor loop (ADR-003) | 1 | Mitigated |
| T-06 | Provider APIs change, restrict free tiers or shut down | High | Medium | Adapter per provider behind one contract; capability and eligibility discovered at runtime; recorded fixtures for tests; graceful degradation | 5, 6 | Open |
| T-07 | Rate limits and quotas exhausted by an investigation or a monitor | Medium | Medium | Central rate limiter, cache reuse, query deduplication, cost estimates and approval thresholds | 2, 11 | Open |
| T-08 | Entity resolution merges different real-world entities | Medium | High | Candidate matching with analyst review; never merge on name, username, avatar or location alone; merges are reversible | 7 | Open |
| T-09 | Graph outgrows relational queries | Low | Medium | `GraphStore` interface; Neo4j projection as an option decided on measurements | 7 | Open |
| T-10 | Unbounded growth of raw responses and observations | Medium | Medium | Content-addressed storage, retention periods, partitioning of observation tables | 2, 11 | Open |
| T-11 | New Python or Node releases lack binary wheels or break builds | Medium | Medium | Supported version range checked by the installer; hash-pinned lock files; CI matrix | 1 | Open |
| T-12 | Desktop shell cannot be built on a user machine without Rust and MSVC | High | Low | The web interface works without the shell; CI builds the installer as a downloadable artifact; signed release installer in Phase 14 | 1, 14 | Accepted |
| T-13 | Tauri depends on WebView2, missing on some Windows 10 machines | Low | Low | Installer bundle includes the WebView2 bootstrapper (Phase 14) | 14 | Open |
| T-14 | Dependency versions move faster than documentation or prior knowledge | Medium | Medium | Behaviour verified by tests against the pinned versions, not assumed | all | Ongoing |
| T-15 | Long-running collection blocks the interface | Medium | Medium | All collection is a background job with progress events; request handlers never call providers | 2 | Open |

## Security and privacy risks

| ID | Risk | L | I | Mitigation | Owner phase | State |
|---|---|---|---|---|---|---|
| S-01 | The local API is reached by a malicious web page (DNS rebinding, cross-site requests) | Medium | High | Host allow-list, origin check, `SameSite=Strict` cookies, CSRF token, JSON-only bodies | 1 | Mitigated; covered by tests |
| S-02 | First-run takeover before an administrator exists | Low | High | Local setup token (ADR-007) | 1 | Mitigated; covered by tests |
| S-03 | Interface exposed to a network | Low | High | Loopback binding enforced; non-loopback needs an explicit setting and is reported by `doctor` | 1 | Mitigated |
| S-04 | Server-side request forgery through user-supplied URLs | Medium | High | Central HTTP client that resolves and checks destinations, blocks private ranges unless in scope, limits redirects | 2 | Open |
| S-05 | Malicious uploaded documents or images | Medium | High | Size limits, type detection, sandboxed parsing, no execution, no macro processing | 9 | Open |
| S-06 | Leakage of provider API keys | Medium | High | Encrypted at rest under DPAPI; never returned by the API; redacted in logs | 1, 5 | Foundation in place |
| S-07 | Case data sent to a cloud model without intent | Medium | High | Local-only mode; explicit per-case consent; redaction before sending | 10 | Open |
| S-08 | Prompt injection through collected content | High | Medium | Collected text is data, never instructions; tools are permissioned; plans need approval for anything active | 10 | Open |
| S-09 | Unencrypted backups contain password hashes and case data | Medium | Medium | Documented; passphrase-encrypted backups in Phase 13 | 1, 13 | Open — known limitation |
| S-10 | Secret-scanning tools verify found secrets against live services | Medium | High | Verification disabled in the adapters; secrets redacted and never used | 6 | Open |
| S-11 | Vulnerable dependencies | Medium | Medium | `pip-audit` and `npm audit` in CI; pinned versions | 1 | In place |

## Legal, ethical and product risks

| ID | Risk | L | I | Mitigation | Owner phase | State |
|---|---|---|---|---|---|---|
| L-01 | Use against people or systems without authorisation | Medium | High | Passive by default; scope manager and written-authorisation fields for active work; restricted operations are not implemented at all (brief section 17.2); audit trail | 2, 3 | Open |
| L-02 | Collection breaches a provider's terms of service | Medium | Medium | Official APIs only; no scraping behind logins or anti-abuse controls; providers without an official API are excluded | 4 to 9 | Open |
| L-03 | Personal data regulation (GDPR and similar) | Medium | High | Data minimisation, retention periods, redaction by default, deletion workflows, local storage | 2, 13 | Open |
| L-04 | Results overstated: estimates presented as facts | Medium | High | Separate confidence dimensions with rationale; geolocation, carrier and username caveats built into the result types | 4, 7 | Open |
| L-05 | Third-party tool licences (NPSL, GPL, AGPL) | Medium | Medium | Tools are never bundled; called as separate user-installed programs (ADR-016) | 4 to 8 | Mitigated by design |
| L-06 | The project has no licence yet | High | Medium | Owner decision required before others can legally use or contribute | — | **Needs owner decision** |
| P-01 | Scope too broad to finish | High | High | Phased delivery with acceptance gates; definition of done; no phase started early | all | Ongoing |
| P-02 | Paid providers cannot be tested without credentials | High | Medium | Recorded mock responses for routine tests; live tests opt-in and skipped without credentials; status clearly "not verified live" | 5, 6 | Open |
