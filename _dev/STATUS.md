# STATUS — consult-cockpit

更新: 2026-07-02

構成: ランタイムは `src/`(server / gemma_chat / env + static)、governance は `_dev/`(オーナー規約)。
ルートは入口/メタのみ。詳細 `_dev/decisions.md` 2026-07-02。

動くもの（検証済み）:
- 3レーン(左 ChatGPT ミラー / 中央 fetch トラフィック / 右 Gemma)。白ベース UI。
- consult ▶（ChatGPT が repo を読む、~40s）／explore repo ▶（Gemma が読む、~4–5s）／
  forward ⇥（ChatGPT の回答のみを Gemma へ、上限8KB）／send（Gemma 雑談）。
- 不変条件: repo 本文は Gemma の永続履歴に入らない（explore は一時 context のみ）。
- 移植版: bare python3（venv なし・improver なし・httpx なし）。`run.sh [repo]` / `run.sh doctor`。
  doctor 6項目パス。任意 repo パスを実行時に受ける（nav-demo に非依存）。

起動:
- `bash ~/.claude/lib/consult-cockpit/run.sh [repo]`（既定 cwd）→ http://127.0.0.1:8079
- 前提: chatgpt-web の専用 Chrome(9333)サインイン済み、.env（WORKER_LLM_*）。`run.sh doctor` で確認。

次にやること: `_dev/TODO.md`（単一ソース）。

注意:
- サーバは単一インスタンス（1 Chrome タブ共有）。同時起動は :8079 競合 → run.sh は既存を検知しブラウザを開くだけ。
