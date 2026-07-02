#!/usr/bin/env bash
# consult-cockpit launcher — portable, zero-venv.
#
#   bash run.sh [REPO]                    launch pointed at REPO (default: current dir)
#   bash run.sh doctor                    validate prerequisites and exit
#   bash run.sh auth set|get|delete LANE  API key in the macOS keychain (LANE: worker|reader)
#
# Prerequisites (see `doctor`): python3 and a worker LLM endpoint (WORKER_LLM_*
# in .env; the API key may live in the keychain instead — `auth set worker`).
# The chatgpt-web skill (Chrome/CDP + ChatGPT sign-in) is optional: without it
# the cockpit runs worker-only.
# Overrides: COCKPIT_PYTHON, COCKPIT_SCRIPTS, COCKPIT_ENV, COCKPIT_PORT.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${COCKPIT_PYTHON:-python3}"
PORT="${COCKPIT_PORT:-8079}"
# scrape reader scripts: vendored scrape/ ships with the repo; override with COCKPIT_SCRIPTS
if [ -z "${COCKPIT_SCRIPTS:-}" ] && [ -d "$HERE/scrape" ]; then
  export COCKPIT_SCRIPTS="$HERE/scrape"
fi

open_url() { command -v open >/dev/null && open "$1" || { command -v xdg-open >/dev/null && xdg-open "$1" || echo "  open: $1"; }; }

if [ "${1:-}" = "doctor" ] || [ "${1:-}" = "--doctor" ]; then
  exec "$PY" "$HERE/src/server.py" doctor
fi

if [ "${1:-}" = "auth" ]; then
  shift
  exec "$PY" "$HERE/src/secrets_store.py" auth-lane "$@"
fi

# already running? just open the browser for the live instance.
if curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  echo "[cockpit] already running on :$PORT (repo field is editable in the UI)"
  open_url "http://127.0.0.1:$PORT/"
  exit 0
fi

REPO="${1:-$PWD}"
REPO="$(cd "$REPO" 2>/dev/null && pwd || echo "$REPO")"
export COCKPIT_REPO="$REPO"

( sleep 1.2; open_url "http://127.0.0.1:$PORT/" ) &
exec "$PY" "$HERE/src/server.py"
