# Interface navigation specification

The navigation structure is fixed by the brief (section 13.2). It is defined
once in `frontend/src/lib/navigation.ts`; availability comes from the backend
feature registry, so the sidebar can never claim more than the backend offers.

## Layout

```
+------------------------------------------------------------------------+
| [logo] OmniOSINT   [ Search or jump to...  Ctrl K ]   [health] [user]  |
+----------------+-------------------------------------------------------+
| Dashboard      |  Page header: title, description, primary actions      |
| Universal ...  |-------------------------------------------------------|
| Investigations |                                                       |
|                |  Page content                                         |
| INTELLIGENCE   |                                                       |
|  Identity      |                                                       |
|  ...           |                                                       |
| ANALYSIS       |                                                       |
| OPERATIONS     |                                                       |
| PLATFORM       |                                                       |
+----------------+-------------------------------------------------------+
```

* Sidebar: 248 px, collapsible to an icon rail; groups collapse individually;
  state is remembered per browser.
* Top bar: command palette trigger, live system-health indicator, user menu
  (account, theme, sign out).
* Dark theme by default, light theme as an alternative. No web fonts or other
  third-party resources are loaded.

## Sections

| # | Section | Group | Route | Feature key | Phase |
|---|---|---|---|---|---|
| 1 | Dashboard | — | `/` | `dashboard` | 1 |
| 2 | Universal Search | — | `/search` | `universal_search` | 2 |
| 3 | Investigations | — | `/investigations` | `investigations` | 3 |
| 4 | Identity Intelligence | Intelligence | `/identity` | `identity` | 4 |
| 5 | Infrastructure Intelligence | Intelligence | `/infrastructure` | `infrastructure` | 4 |
| 6 | Internet Asset Intelligence | Intelligence | `/internet-assets` | `internet_assets` | 5 |
| 7 | Network Topology | Intelligence | `/network-topology` | `network_topology` | 8 |
| 8 | Threat Intelligence | Intelligence | `/threat` | `threat` | 6 |
| 9 | Social and Media Intelligence | Intelligence | `/social-media` | `social_media` | 9 |
| 10 | Image and Document Intelligence | Intelligence | `/image-document` | `image_document` | 9 |
| 11 | Geospatial Intelligence | Intelligence | `/geospatial` | `geospatial` | 9 |
| 12 | Software and Supply Chain | Intelligence | `/software-supply-chain` | `software_supply_chain` | 6 |
| 13 | Vulnerability Intelligence | Intelligence | `/vulnerability` | `vulnerability` | 6 |
| 14 | Relationship Graph | Analysis | `/graph` | `relationship_graph` | 7 |
| 15 | Historical Intelligence | Analysis | `/historical` | `historical` | 11 |
| 16 | AI Investigation Center | Analysis | `/ai` | `ai_investigation` | 10 |
| 17 | Monitoring and Alerts | Operations | `/monitoring` | `monitoring` | 11 |
| 18 | Reports and Evidence | Operations | `/reports` | `reports_evidence` | 13 |
| 19 | Integrations | Platform | `/integrations` | `integrations` | 5 (catalogue: 1; adapters and health checks: 2) |
| 20 | Administration and Settings | Platform | `/admin` | `administration` | 1 |

### Universal Search sub-pages (Phase 2)

| Page | Route | Permission |
|---|---|---|
| Search: classification, plan, run; recent and saved searches | `/search` (`?q=` pre-fills the input) | `collection:read` (running needs `collection:run`) |
| Collection history | `/search/history` | `collection:read` |
| Request: jobs, history, approval, cancel, retry, sources not run | `/search/requests/:id` | `collection:read` (actions need `collection:run` or `collection:approve`) |
| Evidence: observation, provenance, integrity, raw response | `/search/evidence/:id` | `evidence:read` (unmasked raw needs `evidence:read_raw`) |

### Administration and Settings sub-pages

| Page | Route | Permission |
|---|---|---|
| My account (profile, password, sessions, theme) | `/admin/account` | any signed-in user |
| Users | `/admin/users` | `users:read` (changes need `users:manage`) |
| Roles | `/admin/roles` | `roles:read` |
| Scopes | `/admin/scopes` | `scopes:read` (changes need `scopes:manage`) |
| Audit log | `/admin/audit` | `audit:read` |
| System status | `/admin/system` | `system:read` |

Pages a user has no permission for are not shown in the sidebar and return a
"no access" page if opened directly; the API enforces the same rule.

### Outside the shell

| Page | Route | Shown when |
|---|---|---|
| First-run setup | `/setup` | no user exists yet |
| Sign in | `/login` | not signed in |
| Change password | `/change-password` | an administrator reset the password |

## States every page handles

| State | Behaviour |
|---|---|
| Loading | Skeleton placeholders, never spinners that block the whole page |
| Empty | States plainly that there are no records, with the action that creates one |
| Error | Message from the API error envelope, the request id, and a retry action |
| No permission | Explains which permission is missing |
| Planned | "Planned — not yet implemented", the phase, and the planned capabilities |
| Backend unreachable | Banner across the shell; retries automatically |

## Planned pages

A section whose backend does not exist yet renders one shared page that shows:

* the status line **Planned — not yet implemented**,
* the phase that delivers it,
* the capabilities planned for it, taken from the feature registry.

It contains no forms, charts or sample data.

## Keyboard

| Shortcut | Action |
|---|---|
| `Ctrl+K` (`Cmd+K` on macOS) | Open the command palette |
| `Esc` | Close dialogs and the palette |
| `↑` `↓` `Enter` | Move and select inside the palette |

The palette lists every section the user can open, plus actions (toggle theme,
sign out). For a user who may search, it also offers "Search for ..." with the
typed text, which opens Universal Search with that input.

## Investigation workspace (Phase 3)

Tabs, in this order, the same for every case: Overview, Entities, Results,
Graph, Timeline, Evidence, Notes, Tasks, Reports, Activity.

## Result views (Phase 3 onward)

Table, card, graph, timeline, map and evidence views share one toolbar: search,
filter, sort, pagination, column selection, export and comparison.
