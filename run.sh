#!/usr/bin/env bash
# consult-cockpit launcher — portable, zero-venv.
#
#   bash run.sh [REPO]     launch pointed at REPO (default: current dir), open browser
#   bash run.sh doctor     validate prerequisites and exit
#
# Prerequisites (see `doctor`): python3, the chatgpt-web skill (Chrome/CDP +
# one-time ChatGPT sign-in), and a .env with WORKER_LLM_* (shippable internally).
# Overrides: COCKPIT_PYTHON, COCKPIT_SCRIPTS, COCKPIT_ENV, COCKPIT_PORT.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${COCKPIT_PYTHON:-python3}"
PORT="${COCKPIT_PORT:-8079}"
export COCKPIT_SCRIPTS="${COCKPIT_SCRIPTS:-$HOME/.claude/skills/chatgpt-web/scripts}"

open_url() { command -v open >/dev/null && open "$1" || { command -v xdg-open >/dev/null && xdg-open "$1" || echo "  open: $1"; }; }

if [ "${1:-}" = "doctor" ] || [ "${1:-}" = "--doctor" ]; then
  exec "$PY" "$HERE/src/server.py" doctor
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
