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

## 対応環境

Python 3.9+ のみ。venv 不要・pip install 不要（`requirements.txt` は「依存ゼロ」の宣言）。

| 機能 | macOS | Windows | Linux |
|---|---|---|---|
| worker チャット / fetch / auto-compact | ✓ | ✓ | ✓ |
| API reader（`READER_LLM_*`） | ✓ | ✓ | ✓ |
| scrape reader（web ChatGPT） | ✓ | ✓（Chrome 自動検出） | ✓ |
| API キーの keychain 保管 | ✓ | —（`.env` に書く） | —（`.env` に書く） |
| 📁 ネイティブフォルダ選択 | ✓ | —（パス入力欄が出る） | —（パス入力欄が出る） |

keychain と 📁 picker は無い環境では自動でフォールバックする（機能が減るだけで壊れない）。

## セットアップ

1. clone して `.env` を作る（`cp .env.example .env`）:
   - `WORKER_LLM_BASE_URL` / `WORKER_LLM_MODEL` — OpenAI 互換エンドポイント（必須）
   - API キー: macOS は `bash run.sh auth set worker` でキーチェーンへ（推奨）。
     Windows / Linux は `.env` の `WORKER_LLM_API_KEY=` に書く。
2. reader は2択（どちらも無ければ worker-only モード）:
   - scrape reader（同梱・追加課金ゼロ）: 下のセットアップ参照
   - API reader: `.env` に `READER_LLM_*` — consult がブラウザ無しで動く（scrape より優先）
3. 起動:

```
# macOS / Linux
bash run.sh          # → http://127.0.0.1:8079
bash run.sh doctor   # 前提チェックだけして終了

# Windows
run.bat
run.bat doctor
```

## scrape reader のセットアップ(同梱 `scrape/`)

web ChatGPT(無料アカウントでも可)を reader として使う。API 課金なし。全OS対応
（Chrome の実行ファイルは Mac/Windows/Linux の定位置から自動検出）。

```
python3 scrape/ask.py up      # 専用 Chrome(デバッグポート9333・専用プロファイル)を起動
                              # Windows は: py -3 scrape\ask.py up
# → 開いた Chrome で chatgpt.com に一度だけ手でログイン(Cloudflare が出たら手で解く)
bash run.sh doctor            # Chrome:9333 と サインインを確認 (Windows: run.bat doctor)
```

ログインはプロファイル(`~/.gemini-chrome`)に永続するので初回のみ。Chrome は勝手に
起動しない設計(閉じたら閉じたまま)。再開は `scrape/ask.py up`。

性質を理解して使うこと: これはあなた自身がログインした ChatGPT セッションをあなたの
マシン上で自動化するもの。OpenAI の利用規約上グレーであり、Cloudflare の人間チェックや
UI 変更で壊れることがある(壊れたら Chrome 内で手動対応 → リトライ)。嫌なら API reader を。

使い方（入力は1箇所だけ）:
1. 最初に repo を選ぶ（Claude Code と同じモデル: 会話は1つの repo についてのもの）。
   📁 でネイティブのフォルダ選択、またはパス入力。セッション中は固定。
   左サイドバーに過去のセッションが並び、クリックで履歴ごと復元・
   「＋ 新規セッション」で別の repo と新しい会話を開始。あとは普通に話す(Enter=send)。
   セッションは `~/.consult-cockpit/sessions/` に json で永続（`COCKPIT_STATE` で変更可）。
2. repo について聞けば、worker は必要なら自分で repo を読んでから答える
   （🔧 カードが会話に残る。安い・速い）。ボタンは要らない。
3. 強いモデルに読ませたい時は worker に頼む — 「ChatGPTに聞いて」「readerに投げて」。
   worker が consult を発動(🔍 カード。実行中に展開すると reader の探索が live で見える)し、
   回答を踏まえて worker が答える。
   直接聞くなら入力を書いて `ask reader ▶` — 生の回答カードが会話に出て、
   [⇥ worker に渡す] で worker の文脈に入れられる。

リロード時は worker の会話履歴(あなたの発言と最終回答)だけ復元される。tool カードは
その場限りの観測で、正本は履歴のほう。`POST /consult` は API としても残る。

worker の context window が細くても長く使える仕組み（両輪）:
- repo 側: 本文は履歴に入らない（下の不変条件）
- 会話側: 履歴が window 予算（`WORKER_LLM_CONTEXT`、既定16000トークン相当）の7割を
  超えると、古いターンを自動で1つの要約に圧縮（Claude Code の auto-compact と同じ）。
  ヘッダーの context % が現在の使用率。

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
- `run.sh` / `run.bat` — launcher / doctor（auth は macOS のみ）

## ルート

- `GET /` UI / `GET /events` SSE / `GET /state` 現在の状態 / `GET /sessions` 保存済みセッション一覧
- `POST /session {repo|id}` 開始/復元 / `POST /session-delete {id}` /
  `POST /worker {message}` / `POST /consult {question}` / `POST /forward` /
  `POST /worker-explore {repo,task}` / `POST /pick-repo`（macOS のみ）

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
