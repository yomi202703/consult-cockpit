# STATUS — consult-cockpit

更新: 2026-07-03 (深夜) — UI を3レーンから単一エージェント会話に刷新

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
- API reader 配線済み: READER_LLM_* 設定で consult がブラウザ無しの API ループに切替
  (scrape より優先)。両レーン API で scrape 完全不要 = 公開版の形が完成。
- 公開済み(2026-07-03): github.com/yomi202703/consult-cockpit (public, MIT)。
  内部資産スクラブ・/gemma* alias 削除・tests/ スモーク12本。.env はローカル src/.env(gitignore)。
- scrape reader を `scrape/` に vendor(2026-07-03): 無課金 reader が唯一解と確定したため
  主役復帰。clone → `scrape/ask.py up` → ChatGPT 手動ログイン1回 → consult 可。
  解決順 $COCKPIT_SCRIPTS → <repo>/scrape → chatgpt-web スキル。上流で直してから再コピーの運用。

動くもの（検証済み）:
- 単一レーン agent chat（2026-07-03、grill-me 決着 → narrative/decision-collapse-lanes.html）:
  worker との1会話。🔧 fetch カード（worker 自律読み）／🔍 consult カード（実行中に展開で
  live mirror）／ask reader ▶ → inline 回答カード＋[⇥ worker に渡す]／status pill
  （考え中… / repo を読み中… / ChatGPT に質問中… Ns）。
- worker 2ツール: fetch=自律（安い）／consult=明示のみ（~40s）。不変条件: repo 本文は
  worker の永続履歴に入らない（全ツールラウンド transient、残るのは user turn＋最終回答）。
- consult 中 live mirror: vendored nav.wait_complete に on_poll callback を追加、
  ~2s 毎に waiting{secs}＋mirror{turns} を配信（cdp.py WS はスレッド非安全のため
  controller スレッド上で実行。実機で交互配信を確認）。
- consult の対話向け堅牢化: 上限150s、空応答は error 化。リロードは worker 履歴のみ復元
  （tool カードはその場の観測）。
- bare python3（venv なし・httpx なし）。doctor は worker-only／通常の両モード緑。

起動:
- `bash ~/Projects/consult-cockpit/run.sh [repo]`（既定 cwd）→ http://127.0.0.1:8079
  （2026-07-03 に ~/.claude/lib から ~/Projects へ移設。外部参照なし・履歴/リモートは無傷）
- 前提: worker エンドポイント(.env + キーは keychain 推奨)。reader(chatgpt-web + Chrome:9333)は任意。
- `run.sh doctor` で確認。Chrome autolaunch は off — 上げるのは `ask.py up`。

次にやること: `_dev/TODO.md`（単一ソース）。

注意:
- サーバは単一インスタンス（1 Chrome タブ共有）。同時起動は :8079 競合 → run.sh は既存を検知しブラウザを開くだけ。
