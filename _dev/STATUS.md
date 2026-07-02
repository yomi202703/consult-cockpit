# STATUS — consult-cockpit

更新: 2026-07-03

構成: ランタイムは `src/`(server / llm_client / secrets_store / repo_fetch / env + static)、
governance は `_dev/`(オーナー規約)。ルートは入口/メタのみ。

P1 実装済み(2026-07-03、decisions 参照):
- any-API worker: 任意の OpenAI 互換エンドポイント。provider アダプタ(4-field table)、
  gemma|ollama|vllm→openai、anthropic は未実装エラー。
- SecretStore: API キーは macOS キーチェーン(`run.sh auth set worker`)。
  優先順位 = 明示 env var ＞ keychain ＞ .env。doctor が key source を表示。
- scrape optional: chatgpt-web 無しでも worker-only モードで起動(/consult は 503)。
  repo_fetch.py(nav 純粋部の fork)が worker レーンを nav から独立させた。
- 改名: worker/reader(wire・UI・ルート)。/gemma* は互換 alias(公開時削除)。
  UI ラベルは /state から動的(worker_model, reader_mode)。

動くもの（検証済み）:
- 3レーン(左 reader ミラー / 中央 fetch トラフィック / 右 worker)。
- consult ▶（reader が repo を読む、~40s）／explore repo ▶（worker が読む、~4–5s）／
  forward ⇥（reader の回答のみを worker へ、上限8KB）／send（worker 雑談）。
- 不変条件: repo 本文は worker の永続履歴に入らない（explore は一時 context のみ）。
- bare python3（venv なし・httpx なし）。doctor は worker-only／通常の両モード緑。

起動:
- `bash ~/.claude/lib/consult-cockpit/run.sh [repo]`（既定 cwd）→ http://127.0.0.1:8079
- 前提: worker エンドポイント(.env + キーは keychain 推奨)。reader(chatgpt-web + Chrome:9333)は任意。
- `run.sh doctor` で確認。Chrome autolaunch は off — 上げるのは `ask.py up`。

次にやること: `_dev/TODO.md`（単一ソース）。

注意:
- サーバは単一インスタンス（1 Chrome タブ共有）。同時起動は :8079 競合 → run.sh は既存を検知しブラウザを開くだけ。
