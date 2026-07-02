# consult-cockpit

Gemma × ChatGPT の3レーン観測コックピット。ローカル Gemma(小 context)が
repo を自分の context に載せずに、ChatGPT に「repo を読ませて」cross-file の問題を
外注する ── その往復を1画面で可視化する。

- 左 = ChatGPT ミラー(本物の signed-in タブを CDP で読む)
- 中央 = fetch トラフィック(今 ChatGPT がどのファイルを読んでいるか)= 主役
- 右 = Gemma free-form チャット(streaming)

## 走らせる

前提:
- 専用 Chrome + ChatGPT サインイン済み(`chatgpt-web` スキルの手順、debug port 9333)。
- Gemma エンドポイント到達可(`~/.claude/lib/improver/.env` の `WORKER_LLM_*`)。

```
bash ~/.claude/lib/consult-cockpit/run.sh
# → http://127.0.0.1:8079
```

使い方:
1. 左下に repo パスと質問を入れて `consult ▶`。中央に fetch が流れ、左に ChatGPT が
   repo を読んで答えるのが映る。
2. 回答が出たら右下の `forward ⇥` で ChatGPT の回答を Gemma に手渡す。
3. 右の Gemma に「これを実装 plan にまとめて」等と依頼。

## 設計の肝(死守する不変条件)

repo の本文は「中央レーン」と「左(ChatGPT タブ)」にしか出さない。Gemma の会話履歴には
絶対に入れない。`/forward` が渡すのは ChatGPT の最終回答テキストのみ(上限8KB)。
これで「repo は一度も Gemma の context に入らない」= 文脈オフロードを実装で保証する。

## 構成

1プロセス。`improver/.venv`(py3.12 + httpx)で起動し、依存ゼロの
`chatgpt-web/scripts`(nav/ask/cdp)を `sys.path` に足して両方 import。
stdlib `ThreadingHTTPServer` + SSE、フレームワーク無し。

- `src/server.py` — SSE ハブ / タブ制御スレッド(CDP は1本に直列化)/ consult ループ / ルート
- `src/gemma_chat.py` — free-form streaming クライアント(env_loader → OpenAI 互換 /chat/completions, stream=True)
- `src/static/index.html` — 3レーン UI(EventSource + fetch POST、依存なし)
- `run.sh` — PYTHONPATH を張って improver venv で src/server.py を exec

再利用(書き換えず import): `nav.{connect,get_state,find_fetch,run_commands,send_message,wait_complete,build_brief,NEWCHAT_JS}`、
`improver.env_loader.load_env`。

## ルート

- `GET /` UI / `GET /events` SSE / `GET /state` 現在の Gemma 履歴
- `POST /consult {repo,question}` / `POST /gemma {message}` / `POST /forward`

## 検証済み(2026-07-01)

`nav-demo` のバグ入りコピー(`total*(1-percent)` → -18240)で end-to-end:
consult 1ラウンドで ChatGPT が `READ src/{main,discount,inventory}.py` を fetch →
配膳859B → `percent/100` の修正 diff を回答。forward → Gemma が1行要約。
Gemma 履歴に生の repo 本文が入っていないことを確認(不変条件 OK)。
