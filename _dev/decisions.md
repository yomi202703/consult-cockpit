# consult-cockpit _dev / decisions（append-only）

過去エントリは書き換えない。

## 2026-07-03 訂正：雇用者サインオフのゲートは不要（前提が誤り）

- オーナー明言: 本プロジェクトは完全に個人のもの・会社と無関係の善意 PJ。
- 「雇用者サインオフ」ゲートは Claude の推測(インターンリーダーがチームへ共有＋
  improver/.env 参照から社内出自と保守的に判断)だった。前提が誤りだったので撤回。
- 公開の実行(GitHub 作成＋push)は Deferred のトリガー消滅 → Active P1 へ昇格。
- 変わらない事実: 公開コードに内部エンドポイント/キーは含まれない(スクラブ済・.env は gitignore)。

## 2026-07-03 公開準備：スクラブ・alias 削除・LICENSE・スモークテスト

- 内部資産スクラブ実施: env.py の `_INTERNAL_FALLBACK`(improver/.env) 削除(ローカル動作は
  improver の .env を src/.env にコピーして維持 — gitignore 済み)。DEFAULT_REPO の
  `~/pi-workspace/nav-demo` フォールバック→cwd。UI の repo 欄既定値→"."。docs の
  improver 言及を除去。スクラブ grep(improver|pi-workspace|内部URL)は _dev/ 以外ゼロ。
- /gemma* legacy alias を削除(実測 404)。導入から削除まで1日 — alias の寿命としては最短健全。
- LICENSE: MIT(holder=yomi202703)。tests/: stdlib unittest のスモーク12本
  (repo_fetch のパス安全・コマンド実行、env の優先順位ヘルパー、adapter のパース、
  resolve_lane×キーチェーン stub)。ネットワーク・実キーチェーン非使用。
  テストが env.py の unclosed file 警告を炙り出し→修正。
- 残る公開ゲートは技術外のみ: 雇用者サインオフ、GitHub リポジトリ作成(公開行為そのもの)。
  コードは公開可能な状態。

## 2026-07-03 API reader 配線：consult がブラウザ無しで動く

- `READER_LLM_*` を実配線。consult の dispatch: API reader 設定あり→ `_run_api_consult`
  (worker-explore と同型の fetch ループを lane="reader" で回す)、無ければ従来 scrape、
  どちらも無ければ 503。API 設定時は scrape controller を起動しない(status/mirror の
  所有者を1本化 — 「一度に reader は1つ」)。
- ミラー流用: API reader の transient 会話を scrape と同じ mirror イベント形に写像して
  左ペインに表示。UI は reader_mode=api で「<model> (API)」ラベル＋緑ドット。
- 不変条件は同一: repo 本文は reader の transient と中央レーンのみ。実測で worker 履歴 0 を確認。
- 検証(実走): READER を Gemma エンドポイントに向け、consult がブラウザ無しで repo を
  fetch 探索 → 不変条件を問う質問に repo を読んで正答 → forward が回答81Bだけを worker へ。
  doctor は設定時「consult uses this, not the scrape lane」を表示。
- これで公開版の形が完成: 両レーン API・キーチェーン・scrape は完全 optional。

## 2026-07-03 P1実装：any-API worker＋SecretStore＋scrape optional＋worker/reader改名

- 実装コミット: 64a3615(repo_fetch fork＋nav ガード) / 5754226(llm_client＋secrets_store＋env) /
  5d65346(改名・ルート・doctor・auth)。計画は plans/hidden-wobbling-moler（探索3体＋Plan agent）。
- repo_fetch.py = nav.py の純 repo 読み層(protocol/READ/GREP/LS/TREE/build_brief)の意図的
  ownership fork。理由: nav の3ヘルパー(CMD_RE/build_brief/run_commands)が worker レーンにも
  使われており、chatgpt-web 無しで動くにはこの分離が核心だった。上流 nav.py は不変更
  (CDP 修正は上流へ、repo-fetch 修正は fork へ)。「vendor するな」規約のこの1点だけの例外。
- scrape optional 化: `import nav` は try/except ImportError のみ(実バグは落とす)。無ければ
  worker-only モード — /consult 503(detail 付き)、doctor は [off] 情報行、controller 不起動、
  SSE 初回 status が disabled。ランタイム切断は元から graceful、壊れていたのはロードだけ。
- キー優先順位(核心): 明示 env var ＞ keychain ＞ .env 値。load_env() が非上書きのため、
  素朴実装では stale .env が keychain に勝ってしまう — env.py に `_injected` set と
  `from_live_env()` を足して「本当に外から来た env」を区別。doctor が key source を表示。
- secrets_store.py: /usr/bin/security 直叩き(Claude Code 拡張の解剖と同型)。timeout 2s、
  rc 44/36=clean not-found。service="consult-cockpit"、account=<provider>(プロバイダ単位。
  Claude Code のユーザー単位とは意図的に違う — レーンがプロバイダを共有したらキーも共有)。
- env 命名は WORKER_LLM_*/READER_LLM_* に確定(旧 TODO の「LLM_*＋alias」案は不採用 —
  WORKER_LLM_* が現行名なので alias 不要、汎用 LLM_* はレーン2本と衝突)。READER_LLM_* は
  休眠(resolve→None、doctor 情報行のみ)。REQUIRED は BASE_URL+MODEL に縮小
  (PROVIDER は required-but-unread のバグだった→optional/default openai、API_KEY は keychain 可)。
- アダプタは 4-field の flat dict(path/headers/payload/parse_line)のみ。gemma|ollama|vllm →
  openai エントリ。anthropic は resolve 時 NotImplementedError。クラス階層/registry は
  2つ目の方言が実在するまで作らない。
- wire+UI 改名(who/イベント/status キー/CSS/route)を alias なしで一気に実施 — SSE の消費者は
  同梱 index.html のみで互換面が存在しないため。ルートだけ /gemma* を互換 alias で残す
  (tuple membership で同一分岐)。公開時削除は TODO の公開化項目に登録。
- UI ラベルは /state(worker_model, reader_mode) から動的表示 — 「Gemma と書いてあるのに
  任意モデル」という嘘を排除。
- 検証: doctor 両モード緑 / worker-only 実走(200・503・SSE・explore 往復) / 通常モード回帰 /
  キー3経路(env・keychain・.env)の優先順位実証 / fork 同値 / py_compile / 残骸 grep ゼロ。

## 2026-07-01 新設：Gemma × ChatGPT 3レーン観測コックピット

- 起源: chatgpt-web の `nav.py consult`(素の web ChatGPT に repo を読ませる)を、
  ローカル小context Gemma(improver/pi 系)の「文脈オフロード」として可視化したい、
  という会話から。左=ChatGPT ミラー / 中央=fetch トラフィック(主役)/ 右=Gemma。
- 決定(ユーザー確認): consult の引き金は人間駆動(Gemma 自律 tool-loop は作らない)、
  v1 で3レーン一気、ChatGPT ペインは本物タブの CDPミラー。
- 実装: 1プロセス、stdlib `ThreadingHTTPServer`+SSE。CDP タブは単一資源なので
  ws 操作を1本の tab-controller スレッドに直列化。Gemma チャットは CDP を触らず並走。
- 再利用: nav.py を書き換えず `connect/get_state/find_fetch/run_commands/send_message/
  wait_complete/build_brief/NEWCHAT_JS` を import。consult ループは SSE 版に焼き直し。
- 検証: nav-demo のバグ入りコピー(`total*(1-percent)`=-18240)で consult 1ラウンド完走、
  ChatGPT が discount.py を fetch→percent/100 の修正 diff を回答。

## 2026-07-01 不変条件：repo 本文は Gemma の永続 context に入れない

- consult 経路: `run_commands` の出力(repo 本文)は ChatGPT タブと中央レーンにしか出さない。
- `/forward`: ChatGPT の最終回答テキストのみを上限8KBで Gemma 履歴へ。fetch 配膳は渡さない。
- 検証: forward 後、README/inventory.py の本文が Gemma 履歴に不在(回答だけ crossing)を確認。

## 2026-07-01 Gemma ローカル探索を追加（explore）＋不変条件の精密化

- 動機: 「Gemma は使い放題、どしどし探索させてよい。ただし遅いのは不可」。
- 実装: nav の fetch 機構を Gemma に向けた `_run_gemma_explore`。Gemma が `fetch` を出す→
  `run_commands` で配膳→Gemma へ返す、を最大4ラウンド。ブラウザ非経由の直 API。
- 速度対策: ラウンド上限4・複数ファイル一括(brief が ≤8/turn を許容)・中央レーンに即 tick。
  実測: first fetch 1.0–1.5s / final answer 4–5s(consult ~40s に対し桁違いに速い)。
- 不変条件の精密化: explore は「ユーザーが明示的に Gemma に読ませた」意図的な例外。repo 本文は
  **一時 context** にだけ入り、**永続**の Gemma 履歴には最終回答しか残さない。だから履歴は痩せたまま。
- 中央レーンは who タグ(chatgpt=青 / gemma=緑)で色分け。「誰がどのファイルを読んでいるか」が主役。

## 2026-07-02 方針：チーム版/公開版の認証を any-API＋OSキーチェーンへ

- 背景: 想定ユーザーが「自前 Gemma を立てる個人」→「任意 API を使う社内チーム＋公開配布」に変化。
  裏取りに VSCode 拡張3種の実物を解剖（github/microsoft/anthropic.claude-code、この日）。
- 判明: 拡張のクリーンなログイン＝システムブラウザ委譲＋`vscode://`/`127.0.0.1` ループバック＋
  OS キーチェーン保存。差は「上流が OAuth を出すか」だけ。Anthropic は
  `claude.com/cai/oauth/authorize`→`create_api_key`を公開、ChatGPT web は第三者 OAuth 無し
  （＝現行 CDP スクレイプは上流仕様差の必然、実装の下手さではない）。
- 決定した方向: (1) 既定を「API キー＋OS キーチェーン(拡張なら SecretStorage)」に、
  (2) OAuth ループパックは提供元のみ上乗せ（Claude Code を踏襲）、
  (3) ChatGPT web スクレイプは optional・非既定に降格。
- 公開(public GitHub)化の鍵＝スクレイプ・レーンを既定から外すこと。standalone 化と
  OpenAI web 自動化の ToS グレー排除が同時に達成。位置づけは「文脈オフロード観測ツール」。
- 公開前ゲート: 社内資産スクラブ（improver/.env フォールバック・内部エンドポイント）・
  雇用者サインオフ・ライセンス・最小テスト。詳細設計→`_dev/design_auth.md`。

## 2026-07-02 repo-shape：ランタイムを src/ に集約

- `server.py` / `gemma_chat.py` / `env.py` / `static/` を `src/` へ git-mv(履歴保持)。
  ルートは入口/メタ(run.sh・README・SKILL・CLAUDE)のみに。普遍レイヤーの source スロット化。
- 波及: run.sh 2箇所を `$HERE/src/server.py` に、README/SKILL の Files 一覧を src/ プレフィックスへ。
  import は3モジュールが兄弟ごと移動で無変更、`INDEX = join(HERE,"static",…)` も HERE(=src/) 基準で解決。
- 手順: オーナー判断でブランチ不要・main 直接。`run.sh doctor` 緑(唯一の FAIL=Chrome:9333 down は
  手動停止中の別件で、移動とは無関係)。
- 維持した既存の逸脱: governance は `_dev/`(docs/ でなく)、nav/ask/cdp は非vendored import。

## 2026-07-01 移植性：improver/venv/httpx から脱依存（bare python3 化）

- 気づき: コックピットが improver から使っていたのは env_loader(.env 読むだけ)。gemma_subagent は
  未使用。よって langgraph 等の重い venv は不要。
- 対応: (1) `env.py` を新設し .env 読取を内製(探索順 $COCKPIT_ENV → ./.env → improver/.env)。
  (2) `gemma_chat.py` を httpx→stdlib urllib のストリーミングに置換。(3) server.py から improver 依存除去、
  `COCKPIT_SCRIPTS/REPO/ENV/PORT/PYTHON` で上書き可能に。(4) `run.sh` を launcher 化
  (`run.sh [repo]` 既定 cwd / `run.sh doctor`)。(5) SKILL.md 追加で一級スキル化。
- 前提(chatgpt-web の nav/ask/cdp)は 3.10+ 構文を使っておらず system python3(3.9)でも import 可。
  よって cockpit は python3 だけで動く(venv 不要)。
- 検証: doctor 6項目パス、bare homebrew python3.14 で起動、explore で cockpit 自身のコードを読ませて
  設計不変条件を 5.1s で正答。env は内部者に配布可という前提のため別マシン移植も現実的
  (残る手動は各マシンの Chrome サインインのみ)。
