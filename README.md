# consult-cockpit

worker × reader の3レーン観測コックピット。小 context の worker(今はローカル Gemma、
任意の OpenAI 互換 API 可)が repo を自分の context に載せずに、reader(今は web
ChatGPT)に「repo を読ませて」cross-file の問題を外注する ── その往復を1画面で可視化する。

- 左 = reader ミラー(本物の signed-in ChatGPT タブを CDP で読む。無ければ disabled)
- 中央 = fetch トラフィック(今どのファイルが読まれているか)= 主役
- 右 = worker free-form チャット(streaming)

## 走らせる

前提:
- worker エンドポイント(OpenAI 互換)。`.env` に `WORKER_LLM_BASE_URL/_MODEL`、
  API キーは `bash run.sh auth set worker` で macOS キーチェーンへ(推奨。.env でも可)。
- reader は2択(どちらも無ければ worker-only モード):
  - API reader: `.env` に `READER_LLM_*` — consult がブラウザ無しで動く(scrape より優先)
  - scrape reader: 専用 Chrome + ChatGPT サインイン済み(`chatgpt-web` スキル、port 9333)

```
bash ~/.claude/lib/consult-cockpit/run.sh
# → http://127.0.0.1:8079
```

使い方:
1. 左下に repo パスと質問を入れて `consult ▶`。中央に fetch が流れ、左に reader が
   repo を読んで答えるのが映る。
2. 回答が出たら右下の `forward ⇥` で reader の回答を worker に手渡す。
3. 右の worker に「これを実装 plan にまとめて」等と依頼。

## 設計の肝(死守する不変条件)

repo の本文は「中央レーン」と「左(reader タブ)」にしか出さない。worker の会話履歴には
絶対に入れない。`/forward` が渡すのは reader の最終回答テキストのみ(上限8KB)。
これで「repo は一度も worker の context に入らない」= 文脈オフロードを実装で保証する。

## 構成

1プロセス・bare python3(3.9+)・stdlib のみ。`ThreadingHTTPServer` + SSE、
フレームワーク無し。chatgpt-web/scripts(nav/ask/cdp)は在れば sys.path で import
(scrape reader 用・任意)。

- `src/server.py` — SSE ハブ / タブ制御スレッド(CDP は1本に直列化)/ consult ループ / ルート
- `src/llm_client.py` — レーン設定(resolve_lane)＋provider アダプタ＋streaming クライアント(OpenAI 互換)
- `src/secrets_store.py` — API キーの macOS キーチェーン保管(`run.sh auth`)
- `src/repo_fetch.py` — 読み取り専用 repo fetch 層(nav の純粋部分の ownership fork)
- `src/env.py` — .env リーダ(+ from_live_env でキー優先順位を実装)
- `src/static/index.html` — 3レーン UI(EventSource + fetch POST、依存なし)
- `run.sh` — launcher / doctor / auth

reader 用に import(書き換えず): `nav.{connect,get_state,find_fetch,send_message,wait_complete,NEWCHAT_JS}`。

## ルート

- `GET /` UI / `GET /events` SSE / `GET /state` 現在の worker 履歴・レーン構成
- `POST /consult {repo,question}` / `POST /worker {message}` / `POST /worker-explore {repo,task}` / `POST /forward`
  (旧 `/gemma`, `/gemma-explore` は互換エイリアス・公開時に削除)

## 検証済み(2026-07-01)

`nav-demo` のバグ入りコピー(`total*(1-percent)` → -18240)で end-to-end:
consult 1ラウンドで ChatGPT が `READ src/{main,discount,inventory}.py` を fetch →
配膳859B → `percent/100` の修正 diff を回答。forward → Gemma が1行要約。
Gemma 履歴に生の repo 本文が入っていないことを確認(不変条件 OK)。
