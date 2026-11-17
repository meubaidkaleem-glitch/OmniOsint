#!/usr/bin/env bash
# Installs or updates OmniOSINT on Linux (including WSL2).
#
#   scripts/linux/install.sh [--update] [--skip-frontend] [--python PATH]
#                            [--database ask|bootstrap|existing|docker|skip]
#                            [--pg-admin-user NAME] [--non-interactive]
#
# For --database bootstrap in non-interactive mode, put the administrator
# password in OMNIOSINT_PG_ADMIN_PASSWORD.
#
# Creates .venv, installs the hash-pinned dependencies, builds the web
# interface (needs Node.js 22.22+), prepares the database and runs the
# diagnostics. Installs no system packages; it tells you what is missing.
# Afterwards use:  .venv/bin/omniosint start | status | stop
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
UPDATE=0
SKIP_FRONTEND=0
DATABASE="ask"
PYTHON_BIN=""
PG_ADMIN_USER="postgres"
[[ -t 0 ]] && INTERACTIVE=1 || INTERACTIVE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --update) UPDATE=1 ;;
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --database) DATABASE="$2"; shift ;;
    --python) PYTHON_BIN="$2"; shift ;;
    --pg-admin-user) PG_ADMIN_USER="$2"; shift ;;
    --non-interactive) INTERACTIVE=0 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok() { printf '    \033[32m[ok]\033[0m %s\n' "$1"; }
warn() { printf '    \033[33m[!]\033[0m  %s\n' "$1"; }
die() { printf '    \033[31m[x]\033[0m  %s\n' "$1" >&2; [[ -n "${2:-}" ]] && printf '    %s\n' "$2" >&2; exit 1; }
omni() { "$PY" -m omniosint "$@"; }
version_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]; }

step "Looking for Python 3.12 or later"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.12 python3.13 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      v="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
      if [[ -n "$v" ]] && version_ge "$v" "3.12"; then PYTHON_BIN="$(command -v "$candidate")"; break; fi
    fi
  done
fi
[[ -n "$PYTHON_BIN" ]] || die "Python 3.12 or later is required." "Install it with your package manager (for example: sudo apt install python3.12 python3.12-venv)."
ok "$("$PYTHON_BIN" --version) ($PYTHON_BIN)"

step "Preparing the Python environment"
if [[ ! -x "$PY" ]]; then
  "$PYTHON_BIN" -m venv "$VENV" || die "Could not create the virtual environment." "On Debian/Ubuntu install the python3.12-venv package."
  ok "Created $VENV"
else
  ok "Using the existing environment in $VENV"
fi
"$PY" -m pip --disable-pip-version-check install --quiet --upgrade pip
"$PY" -m pip --disable-pip-version-check install --quiet --require-hashes -r "$ROOT/requirements.txt"
"$PY" -m pip --disable-pip-version-check install --quiet --no-deps --editable "$ROOT"
ok "$(omni --version)"

step "Building the web interface"
if [[ "$SKIP_FRONTEND" == 1 ]]; then
  warn "Skipped (--skip-frontend)."
elif [[ -f "$ROOT/frontend/dist/index.html" && "$UPDATE" == 0 ]]; then
  ok "Already built. Use --update to rebuild."
elif command -v node >/dev/null 2>&1 && version_ge "$(node --version | tr -d v)" "22.22.0"; then
  (cd "$ROOT/frontend" && npm ci --no-audit --no-fund --loglevel=error && npm run --silent build >/dev/null)
  ok "Built with Node.js $(node --version)"
else
  warn "Node.js 22.22 or later was not found; the web interface was not built."
  warn "OmniOSINT runs, but the browser shows instructions instead of the interface."
fi

step "Preparing the database"
set +e
omni db check >/dev/null 2>&1
check=$?
set -e
if [[ $check == 3 ]]; then
  die "The configuration is invalid." "Run: .venv/bin/omniosint config validate"
fi
if [[ $check == 4 ]]; then
  warn "OmniOSINT cannot reach a database yet."
  mode="$DATABASE"
  if [[ "$mode" == "ask" ]]; then
    if [[ "$INTERACTIVE" == 1 ]]; then
      echo "    [1] Create the role and database with a PostgreSQL administrator account"
      echo "    [2] Use an existing database (enter its connection details)"
      echo "    [3] Run PostgreSQL with Docker"
      echo "    [4] Skip for now"
      read -r -p "    Choice (default 1): " choice
      case "${choice:-1}" in 1) mode=bootstrap ;; 2) mode=existing ;; 3) mode=docker ;; *) mode=skip ;; esac
    else
      mode=skip
    fi
  fi
  case "$mode" in
    bootstrap)
      echo "    On a local server you can also create them by hand instead:"
      echo "      sudo -u postgres createuser --pwprompt omniosint && sudo -u postgres createdb -O omniosint omniosint"
      if [[ -n "${OMNIOSINT_PG_ADMIN_PASSWORD:-}" ]]; then
        printf '%s\n' "$OMNIOSINT_PG_ADMIN_PASSWORD" | omni db bootstrap --admin-user "$PG_ADMIN_USER" --admin-password-stdin
      else
        omni db bootstrap --admin-user "$PG_ADMIN_USER"
      fi ;;
    existing)
      read -r -p "    Host [127.0.0.1]: " host; omni config set database.host "${host:-127.0.0.1}" >/dev/null
      read -r -p "    Port [5432]: " port; omni config set database.port "${port:-5432}" >/dev/null
      read -r -p "    Database [omniosint]: " name; omni config set database.name "${name:-omniosint}" >/dev/null
      read -r -p "    User [omniosint]: " user; omni config set database.user "${user:-omniosint}" >/dev/null
      omni secrets set database.password ;;
    docker)
      command -v docker >/dev/null 2>&1 || die "Docker was not found."
      envfile="$ROOT/.env.docker"
      if [[ ! -f "$envfile" ]]; then
        umask 077
        printf 'OMNIOSINT_DB_PASSWORD=%s\n' "$("$PY" -c 'import secrets; print(secrets.token_urlsafe(24))')" > "$envfile"
      fi
      (cd "$ROOT" && docker compose --env-file "$envfile" up --detach --wait postgres)
      omni config set database.host 127.0.0.1 >/dev/null
      omni config set database.port 5433 >/dev/null
      grep '^OMNIOSINT_DB_PASSWORD=' "$envfile" | cut -d= -f2- | omni secrets set database.password --stdin ;;
    *)
      warn "Database not configured. OmniOSINT will not start until it is; run this script again when ready."
      omni doctor || true
      exit 2 ;;
  esac
fi
omni db upgrade

# Lets the desktop shell find this program folder from anywhere.
"$PY" - "$ROOT" "$PY" <<'PYEOF'
import datetime, json, sys
from omniosint.core.paths import AppPaths
paths = AppPaths.resolve()
paths.ensure()
record = {"root": sys.argv[1], "python": sys.argv[2],
          "installed_at": datetime.datetime.now(datetime.UTC).isoformat()}
paths.install_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
PYEOF

step "Running the installation diagnostics"
omni doctor || warn "Some checks failed; see above."

printf '\n    \033[32mOmniOSINT is installed.\033[0m Start it with:  %s start --open\n' ".venv/bin/omniosint"
