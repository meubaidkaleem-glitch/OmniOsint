#!/usr/bin/env bash
# Browser end-to-end tests against a real, freshly started OmniOSINT.
#
#   OMNIOSINT_E2E_DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/omniosint_e2e \
#     scripts/dev/run-e2e.sh [--screenshots DIR] [playwright arguments...]
#
# The database is emptied first: use a disposable one (its name must contain
# "test" or "e2e"). Everything else (data directory, port) is temporary.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
SCREENSHOTS=""
if [[ "${1:-}" == "--screenshots" ]]; then
  SCREENSHOTS="$(mkdir -p "$2" && cd "$2" && pwd)"
  shift 2
fi

: "${OMNIOSINT_E2E_DATABASE_URL:?Set OMNIOSINT_E2E_DATABASE_URL to a disposable database}"

HOME_DIR="$(mktemp -d -t omniosint-e2e-XXXXXX)"
PORT="$("$PYTHON" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
export OMNIOSINT_HOME="$HOME_DIR"
export OMNIOSINT_DATABASE__URL="$OMNIOSINT_E2E_DATABASE_URL"
export OMNIOSINT_SERVER__PORT="$PORT"
# The Phase 2 journey runs collection end to end against the simulated
# provider, which only ever generates documentation-range test data.
export OMNIOSINT_COLLECTION__ENABLE_SIMULATED_PROVIDER="${OMNIOSINT_COLLECTION__ENABLE_SIMULATED_PROVIDER:-true}"

cleanup() {
  "$PYTHON" -m omniosint stop >/dev/null 2>&1 || true
  if [[ "${KEEP_E2E_HOME:-0}" != "1" ]]; then rm -rf "$HOME_DIR"; fi
}
trap cleanup EXIT

echo "==> Building the web interface"
(cd "$ROOT/frontend" && npm run --silent build >/dev/null)

echo "==> Preparing the database"
"$PYTHON" "$ROOT/scripts/dev/reset_test_db.py" "$OMNIOSINT_E2E_DATABASE_URL"
"$PYTHON" -m omniosint db upgrade

echo "==> Starting OmniOSINT on port $PORT"
START_JSON="$("$PYTHON" -m omniosint start --json)"
OMNIOSINT_E2E_BASE_URL="$(printf '%s' "$START_JSON" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["url"])')"
OMNIOSINT_E2E_SETUP_URL="$(printf '%s' "$START_JSON" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["open_url"])')"
export OMNIOSINT_E2E_BASE_URL OMNIOSINT_E2E_SETUP_URL
[[ -n "$SCREENSHOTS" ]] && export OMNIOSINT_E2E_SCREENSHOTS="$SCREENSHOTS"

echo "==> Running browser tests"
cd "$ROOT/frontend"
npx playwright test --trace off "$@"
