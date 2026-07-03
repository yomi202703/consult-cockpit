# consult-cockpit

worker との単一エージェント会話 UI。小 context の worker(今はローカル Gemma、任意の
OpenAI 互換 API 可)が repo を自分の履歴に載せずに扱う ── 必要なら自分で読み(fetch)、
頼まれれば reader(今は web ChatGPT)に外注する(consult)。その「誰がどのファイルを
読んだか」は会話内の折り畳みカードとして残る(ChatGPT の「検索しました ▸」式)。

- 会話 = worker との1本のチャット(streaming)。入力もここだけ。
- 🔧 fetch カード = worker が自分で repo を読んだ痕跡(展開で対象とバイト数)
- 🔍 consult カード = reader が repo を探索した痕跡(実行中に展開すると live で
  「今どのファイルを読んでいるか」が見える)
- status pill = 考え中… / repo を読み中… / ChatGPT に質問中… Ns(入力欄の上)

## 走らせる

前提:
- worker エンドポイント(OpenAI 互換)。`.env` に `WORKER_LLM_BASE_URL/_MODEL`、
  API キーは `bash run.sh auth set worker` で macOS キーチェーンへ(推奨。.env でも可)。
- reader は2択(どちらも無ければ worker-only モード):
  - scrape reader(同梱・追加課金ゼロ): 下の「scrape reader のセットアップ」参照
  - API reader: `.env` に `READER_LLM_*` — consult がブラウザ無しで動く(scrape より優先)

## scrape reader のセットアップ(同梱 `scrape/`)

web ChatGPT(無料アカウントでも可)を reader として使う。API 課金なし。

```
python3 scrape/ask.py up      # 専用 Chrome(デバッグポート9333・専用プロファイル)を起動
# → 開いた Chrome で chatgpt.com に一度だけ手でログイン(Cloudflare が出たら手で解く)
bash run.sh doctor            # Chrome:9333 と サインインを確認
```

ログインはプロファイル(`~/.gemini-chrome`)に永続するので初回のみ。Chrome は勝手に
起動しない設計(閉じたら閉じたまま)。再開は `scrape/ask.py up`。

性質を理解して使うこと: これはあなた自身がログインした ChatGPT セッションをあなたの
マシン上で自動化するもの。OpenAI の利用規約上グレーであり、Cloudflare の人間チェックや
UI 変更で壊れることがある(壊れたら Chrome 内で手動対応 → リトライ)。嫌なら API reader を。

```
bash ~/.claude/lib/consult-cockpit/run.sh
# → http://127.0.0.1:8079
```

使い方（入力は1箇所だけ）:
1. ヘッダーの repo 欄に対象 repo を入れ、普通に話す(Enter=send)。
2. repo について聞けば、worker は必要なら自分で repo を読んでから答える
   （🔧 カードが会話に残る。安い・速い）。ボタンは要らない。
3. 強いモデルに読ませたい時は worker に頼む — 「ChatGPTに聞いて」「readerに投げて」。
   worker が consult を発動(🔍 カード。実行中に展開すると reader の探索が live で見える)し、
   回答を踏まえて worker が答える。
   直接聞くなら入力を書いて `ask reader ▶` — 生の回答カードが会話に出て、
   [⇥ worker に渡す] で worker の文脈に入れられる。

リロード時は worker の会話履歴(あなたの発言と最終回答)だけ復元される。tool カードは
その場限りの観測で、正本は履歴のほう。`POST /consult` は API としても残る。

## 設計の肝(死守する不変条件)

repo の本文は worker の会話履歴に絶対に入れない。fetch も consult も各ツールラウンドは
使い捨ての一時 context にだけ入り、履歴に残るのは user turn と最終回答のみ。
`/forward` が渡すのは reader の最終回答テキストのみ(上限8KB)。
これで「repo は一度も worker の永続 context に入らない」= 文脈オフロードを実装で保証する。

## 構成

1プロセス・bare python3(3.9+)・stdlib のみ。`ThreadingHTTPServer` + SSE、
フレームワーク無し。chatgpt-web/scripts(nav/ask/cdp)は在れば sys.path で import
(scrape reader 用・任意)。

- `src/server.py` — SSE ハブ / タブ制御スレッド(CDP は1本に直列化)/ consult ループ / ルート
- `src/llm_client.py` — レーン設定(resolve_lane)＋provider アダプタ＋streaming クライアント(OpenAI 互換)
- `src/secrets_store.py` — API キーの macOS キーチェーン保管(`run.sh auth`)
- `src/repo_fetch.py` — 読み取り専用 repo fetch 層(nav の純粋部分の ownership fork)
- `src/env.py` — .env リーダ(+ from_live_env でキー優先順位を実装)
- `src/static/index.html` — 単一レーン agent chat UI(EventSource + fetch POST、依存なし)
- `scrape/` — scrape reader の実体(nav/ask/cdp、純 stdlib の CDP クライアント同梱)
- `run.sh` — launcher / doctor / auth

## ルート

- `GET /` UI / `GET /events` SSE / `GET /state` 現在の worker 履歴・レーン構成
- `POST /consult {repo,question}` / `POST /worker {message}` / `POST /worker-explore {repo,task}` / `POST /forward`

## テスト

```
python3 -m unittest discover tests   # スモーク + e2e、全部で ~1秒
```

e2e はモック LLM(`tests/mock_llm.py`、決定的・即答の OpenAI 互換サーバ)に両レーンを
向けて、chat / explore / consult / forward / 不変条件を実 HTTP で検証する。
実エンドポイント・キー・ブラウザ不要。

UI を手で触って確認する時もモックが速い(consult が1秒未満で返る):

```
python3 tests/mock_llm.py &          # :8199
WORKER_LLM_BASE_URL=http://127.0.0.1:8199/v1 WORKER_LLM_MODEL=mock \
READER_LLM_BASE_URL=http://127.0.0.1:8199/v1 READER_LLM_MODEL=mock \
COCKPIT_ENV=/dev/null bash run.sh
```

## ライセンス

MIT（`LICENSE`）。

## 検証済み(2026-07-01)

`nav-demo` のバグ入りコピー(`total*(1-percent)` → -18240)で end-to-end:
consult 1ラウンドで ChatGPT が `READ src/{main,discount,inventory}.py` を fetch →
配膳859B → `percent/100` の修正 diff を回答。forward → Gemma が1行要約。
Gemma 履歴に生の repo 本文が入っていないことを確認(不変条件 OK)。
