# Developer guide

Read [ARCHITECTURE.md](ARCHITECTURE.md) first. This guide covers the working
setup, conventions and checks.

## Setting up

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m pip install --no-deps -e .
(cd frontend && npm ci)
```

A PostgreSQL server is needed for anything beyond the unit tests. Create a
development database and two test databases (their names must contain `test`
or `e2e`, because the test tools drop their schema):

```sql
CREATE ROLE omniosint LOGIN PASSWORD 'dev-password' CREATEDB;
CREATE DATABASE omniosint OWNER omniosint;
CREATE DATABASE omniosint_test OWNER omniosint;
CREATE DATABASE omniosint_e2e OWNER omniosint;
```

```bash
.venv/bin/omniosint secrets set database.password
.venv/bin/omniosint db upgrade
```

## Running in development

```bash
OMNIOSINT_ENVIRONMENT=development .venv/bin/omniosint serve --reload   # API on :8765, /api/docs enabled
(cd frontend && npm run dev)                                            # interface on :5173
```

The Vite development server forwards `/api` to the backend without changing
the `Host` header, so the backend's host and origin checks pass without extra
configuration.

## Tests

| Suite | Command | Needs |
|---|---|---|
| Backend unit | `pytest tests/unit` | nothing |
| Backend integration, security, lifecycle | `pytest` | `OMNIOSINT_TEST_DATABASE_URL` |
| Database bootstrap | (part of `pytest`) | `OMNIOSINT_TEST_ADMIN_DATABASE_URL`, a role allowed to create roles |
| Redis check | (part of `pytest`) | `OMNIOSINT_TEST_REDIS_URL` (optional) |
| Coverage | `pytest --cov` | as above; measures subprocesses too |
| Frontend | `cd frontend && npm test` | nothing |
| Browser end-to-end | `OMNIOSINT_E2E_DATABASE_URL=... scripts/dev/run-e2e.sh` | a disposable database, Chromium |
| Desktop control library | `cargo test --manifest-path desktop/backend-control/Cargo.toml` | Rust |

Example:

```bash
export OMNIOSINT_TEST_DATABASE_URL=postgresql://omniosint:dev-password@127.0.0.1:5432/omniosint_test
.venv/bin/pytest -q
```

Without the variable, the database tests are skipped and say why.

Test layout:

* `tests/unit` - no external services.
* `tests/integration` - API, services and command line against PostgreSQL.
* `tests/security` - host and origin checks, CSRF, injection, traversal,
  secret leakage, body limits.
* `tests/end_to_end` - starts and stops the real processes.
* `frontend/src/**/*.test.tsx` - components and routing with a mocked API.
* `frontend/e2e` - Playwright journeys against a real backend.

## Checks before committing

```bash
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/mypy
.venv/bin/pytest -q
(cd frontend && npm run lint && npm run typecheck && npm test && npm run build)
python scripts/dev/gen_docs.py --check
```

CI (`.github/workflows/ci.yml`) runs all of these, the browser tests, a Windows
install-and-lifecycle job and a Windows desktop build.

## Conventions

### Backend

* **Layers:** routers -> services -> core -> database. Routers contain no
  business logic. Services take an `AsyncSession` and commit their own unit of
  work, including the audit event.
* **Errors:** raise an `OmniError` subclass with a stable `code`. Never return
  error dictionaries by hand.
* **Permissions:** every protected endpoint declares its permission with
  `require(Permission.X)` and `openapi_extra=permission_doc(...)`. New
  permissions are added to `auth/permissions.py` and to the roles that need
  them; `db upgrade` synchronises the database.
* **Database changes:** change the models, then add an Alembic migration in
  `src/omniosint/database/migrations/versions/`. A test fails if models and
  migrations disagree. Migrations must also downgrade.
* **Time:** timezone-aware UTC only (`core.timeutil.utcnow`).
* **Identifiers:** UUIDv7 (`core.ids.uuid7`) for append-heavy tables.
* **Secrets:** never in settings files, logs, API responses or exceptions.
* **Honesty:** a feature that is not built is reported as planned
  (`NotImplementedYet`, the feature registry), never simulated.

### Frontend

* Server state in TanStack Query (`src/api/queries.ts`), interface state in
  Zustand (`src/stores`). Do not copy server data into stores.
* API types come from the backend: after changing the API run
  `omniosint openapi -o frontend/src/api/openapi.json` and `npm run gen:api`.
  A backend test fails if the copy is stale.
* The navigation is defined once in `src/lib/navigation.ts`; whether a section
  is built comes from `GET /system/features`.
* No inline scripts: the backend's Content-Security-Policy forbids them.
* Design tokens are CSS variables in `src/styles/index.css`; use the Tailwind
  names (`bg-surface`, `text-fg-muted`, ...) rather than raw colours.

### Adding an intelligence module or provider (Phase 2 onward)

Modules contribute knowledge of an indicator type; providers are adapters behind
the provider framework. Neither stores data, calls HTTP or rate-limits on its
own. See [PROVIDERS.md](PROVIDERS.md).

## Dependency management

* Python ranges are in `pyproject.toml`; exact versions with hashes in
  `requirements.txt` (runtime) and `requirements-dev.txt`. Regenerate with:

  ```bash
  uv pip compile pyproject.toml --universal --python-version 3.12 --generate-hashes -o requirements.txt
  uv pip compile pyproject.toml --extra dev --universal --python-version 3.12 --generate-hashes -o requirements-dev.txt
  ```

  Keep the comment header at the top of each file.
* Frontend versions are exact in `frontend/package.json`, locked in
  `package-lock.json`.
* Prefer releases that have been public for at least two weeks.
* `pip-audit` and `npm audit` run in CI.

## Generated documentation

`python scripts/dev/gen_docs.py` regenerates the provider table in
`docs/PROVIDERS.md`, `docs/API_REFERENCE.md` and `docs/DEPENDENCIES.md`. Run it
after changing the provider catalogue, the API or dependencies.
