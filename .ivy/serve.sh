#!/bin/sh
# Ivy view server の起動口 — cwd を .ivy に固定してから立てる(ROOT ずれ防止)。
# この repo の割当ポート = 8080(規約: :8090=ivy 本体 / :8077〜=各 repo。cockpit アプリ本体は :8079 なので不可)。
cd "$(dirname "$0")"
PORT=${1:-8080}
echo "open http://localhost:$PORT/  — 停止: lsof -ti:$PORT | xargs kill"
exec python3 "$HOME/.claude/skills/ivy/templates/ivy-serve.py" "$PORT"
