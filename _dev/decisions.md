# consult-cockpit _dev / decisions（append-only）

過去エントリは書き換えない。

## 2026-07-03 auto-compact（worker window 限界への答え）＋セッション削除＋scroll 修正

- オーナー「うちらの課題は gemma の window に限界があるってこと。どうするべき？」
  「機能は完全に claude code 寄りにしたい。セッション削除も」。
- window への答え = Claude Code と同じ auto-compact。既存の3層防御(repo 本文は履歴に
  入らない/ツールラウンド transient/8KB cap)で残る唯一の穴が「会話履歴自体の成長」
  だった。履歴推定が予算(WORKER_LLM_CONTEXT、既定16000tok)の7割(COMPACT_AT)を超えたら、
  直近 COMPACT_KEEP_TURNS(6) を残して古いターンを worker 自身の transient 呼び出しで
  1つの [Earlier conversation, compacted] ターンに畳む。要約失敗時は畳まない
  (housekeeping で会話を壊さない)。トークン推定は bytes/3(和英混在の安全側)。
  UI: header に context % メーター(70%で橙)、圧縮時は「🗜 古い会話を1つの要約に圧縮」note。
- セッション削除: POST /session-delete {id}。active を削除すると landing に戻る
  (busy 中は 409)。UI はサイドバー項目 hover で ✕、confirm 後に削除。
- scroll 不具合(オーナー報告): 回答カード(.rawans pre max-height 280)と tool カード
  (.tbody max-height 340)の入れ子スクロールがホイールを横取りし「ページが動かない」
  と感じさせていた。ChatGPT 同様「ページが唯一のスクローラー」に — 入れ子 scrollbox 全廃、
  renderConsultMirror の scrollIntoView も削除(ページを引っ張る)。
- テスト: test_A(削除→一覧から消える→active なら view リセット)、test_B(専用サーバを
  WORKER_LLM_CONTEXT=300 で立て、5ターンで [compacted] ターン1つに畳まれ履歴が縮むこと。
  compaction は履歴を縮めるので「長さ増加」でなくターン固有マーカーで待つのが要点)。23本緑。
- 教訓: 「小さいモデルで大きい repo を扱う」ツールの完成条件は、repo 側のオフロード
  だけでなく会話側の圧縮も揃うこと。両輪で初めて window 限界に答えたことになる。

## 2026-07-03 セッション永続化＋左サイドバー（Claude Code の「最近の項目」）

- オーナー「過去のセッションを左サイドに乗せることはできないんですか？claude code みたいに」。
- 前提が1つ欠けていた: セッションはメモリのみで、新規セッション/再起動で消えていた。
  永続化を先に敷いた — `~/.consult-cockpit/sessions/<id>.json`（COCKPIT_STATE で変更可、
  stdlib json、tmp+os.replace の atomic 書き、初回ターンまで書かない=空セッションは
  一覧に出ない）。書き込みは履歴/last_answer の全変異点で _persist_locked()
  （_state_lock 保持中に呼ぶ規約）。タイトルは最初の user 発言の先頭48字（Claude Code 式）。
- API: GET /sessions（メタ一覧、更新順、上限50）／POST /session が {repo}=新規 と
  {id}=復元 の両対応（復元は履歴+last_answer をロード）。/state に session_id。
- UI: 左サイドバー（＋新規セッション／最近のセッション一覧、active ハイライト、相対時刻）。
  描画は SSE 'session' イベントに一本化 — 発火タブも他タブも同じ経路で
  resetFeed→showChat→/state から履歴再描画→一覧更新（POST 応答側で描画しない）。
- 3レーン廃止で消えた「左ペイン」が別の役割（観測でなくナビゲーション）で復活した形。
  UI の面は観測でなく「ユーザーの作業単位」に割るのが正しい、の再確認。
- テスト: test_9（保存→一覧→タイトル→切替で履歴クリア→復元で履歴復活→未知 id 404）。
  e2e は COCKPIT_STATE をサンドボックスに向けて実ディレクトリを汚さない。

## 2026-07-03 repo はセッション先頭で固定（Claude Code モデル）＋ネイティブ picker

- オーナー提案「Claude Code / Codex みたいに先にフォルダを指定して、指定後は変えられない
  設計の方が良いんじゃね？」。同意した根拠: 従来は repo がリクエスト毎のパラメータで、
  会話の途中で差し替え可能 — だが worker の履歴は1本なので、2つの repo の話が1つの履歴に
  混ざる設計上の嘘があった。「会話は1つの repo についてのもの」に統一する方が正直。
- 「変えられない」は「セッション中は固定。変更=新規セッション(履歴クリア)」として実装
  (Claude Code と同じ。永久固定より自然)。
- 実装: サーバに _session_repo ＋ POST /session {repo}(isdir 検証・busy 中 409・履歴と
  last_answer をクリア・session イベント broadcast)。/worker /consult は repo param 省略時
  session_repo に fallback(param は API 互換で残す)。UI は landing(どの repo で始めますか？
  📁 選択 / パス入力 / 起動フォルダ chip)→ chat(ヘッダーに 📁 repo名 ＋「＋ 新規セッション」)。
  リロードは /state.session_repo で復元、別タブは session イベントで同期。
- ネイティブ picker(直前コミット): ブラウザは native ダイアログからパスを取れないが、
  サーバがローカルなので osascript 'choose folder' で本物の Finder ダイアログを出し
  POSIX パスを返せる(POST /pick-repo、macOS のみ、cancel は {cancelled})。
- 教訓: 「会話 × 対象」の cardinality を UI に合わせる。履歴が1本なら対象も1つ。
  ツールの直感性はここ数ターン一貫して「Claude Code / ChatGPT の既知モデルに寄せる」が正解。

## 2026-07-03 3レーン → 単一エージェント会話 UI（＋consult 中 live mirror）

- オーナー発案「3分割要らなくない？1で十分。ChatGPT のような agent 対話形式にして、
  思考中/ChatGPTに質問中/repo探索中を出す方がわかりやすい」。/grill-me で設計決着
  (briefing は narrative/decision-collapse-lanes.html に凍結):
  - 観測(誰がどのファイルを読むか)は捨てず会話に折り畳んで残す(「検索しました ▸」式)。
    完全に捨てる案(B)・2レーン案(C)は却下 — offload が「見える」のがこのツールの identity。
  - consult カードは実行中に展開すると live mirror(旧・左レーンをカード内に降格)。
  - ask reader ▶ は残すが結果は inline カード＋[⇥ worker に渡す](別枠 answer/forward 廃止)。
  - status は具体段階＋経過秒(toolcall.summary / waiting.secs を利用)。曖昧な「考えて
    います…」にしない。
  - consult 明示のみ・fetch 自律の非対称は不変。
- 実装: index.html 全面書き換え(1カラム max-width 820px、user=右バブル/assistant=平文、
  🔧 fetch カード・🔍 consult カード・rawans カード・status pill)。サーバ変更は1点のみ:
  consult 実行中に mirror が止まる穴(controller が wait_complete 内でブロック、idle tick
  停止)を、vendored scrape/nav.py の wait_complete に on_poll callback(既定 None、
  get_state 直後に呼ぶ)を追加して塞いだ。_wait_with_heartbeat の beat() スレッドは削除
  (polling ~2s に waiting{secs} と MIRROR_JS 評価を畳んだ — callback は渡された ws を
  使う。self.ws は reload_recover 後 stale、_emit_mirror はエラー時 self.ws=None にして
  recovery と喧嘩するため不使用)。
- 方式選定の根拠(Plan agent 検証): cdp.py の WS.cmd はスレッド非安全(id 不一致応答を
  黙って捨てる＋_buf 共有破壊)なので mirror 発行は必ず controller スレッド上。server 側に
  polling を複製する案は wait_complete の stall recovery(empty>=12→reload_recover)を
  複製して drift するため却下。callback は upstream(chatgpt-web)にも還元できる形。
- リロード仕様: worker 履歴(user turn＋最終回答)のみ復元。tool カードは再構築しない
  (SSE に replay バッファが無い。カードはその場の観測、正本は履歴)。
- 実機確認: consult 中 waiting{secs} と mirror{turns} が~2s毎に交互配信されるのを確認。
- 教訓: UI の面数は「操作主体の数」に従う。操作主体が worker 1本に収束した時点で
  3レーンは過去の構造の遺物だった。観測は面でなく「会話内の progressive disclosure」で残す。

## 2026-07-03 explore をボタンから外し worker の自律 fetch ツールに（＋ask reader ボタン）

- オーナー指摘: 「gemma が操作するなら explore を UI に出す必要なくね？」。consult を
  worker のツールにした論理の延長 — repo を読むのが worker 自身なら、人間がボタンを
  押すのは不自然。答えるのに要れば worker が勝手に読むべき。オーナー選択=「必要なら自動で読む」。
- 変更: worker に2ツールを常備（worker_system() を per-call 注入、履歴に残さない）。
  - fetch(自律・安い): 答えに repo が要れば worker が ```fetch を出す。STRICT 判定
    (parse_fetch_block、```fetch フェンスのみ) — 散文中の "READ" で誤発火しない
    （緩い parse_fetch_text は /worker-explore 専用に残置）。reader 不要で常に使える。
  - consult(明示・高い): 従来通り「ChatGPTに聞いて」の時だけ。
  統一ループ _run_worker: working=system+履歴 を transient に持ち、fetch/consult の各
  ラウンドは working にのみ積む。永続履歴に残すのは user turn と最終回答だけ = 不変条件を
  chat 全体に一般化（従来 consult の [Reader's answer] も transient 化し、より痩せた）。
  ツール budget(WORKER_TOOL_ROUNDS=5)超過で最終回答を強制。
- UI: explore ボタン削除（send 1本＋直接質問用の ask reader ▶ は残す）。ツール呼び出しは
  streaming バブルを検出後にコンパクトな 🔧 行へ畳む(toolcall イベント)。左は純ミラーのまま。
- テスト: mock を「最後のメッセージ」ルーティングに変更 — 永続履歴が全テストで累積し、
  古い "please ask the reader" が後続の plain chat を consult に化けさせる汚染を解消
  （ツール応答も現在意図も常に最新メッセージに来るため最後だけ見れば十分）。test_7 追加
  (worker 自律 fetch＋repo 本文が永続履歴に入らないこと)。実機で env.py を自分で読み正答を確認。
- 教訓: 「誰が操作するか」で UI 面を決める。worker が操作主体のものは人間ボタンにしない
  （consult も explore も同じ結論）。安い読み=自律、高い外注=明示、の非対称が一貫方針。

## 2026-07-03 consult の「固まって見える」修正（無言待機＋古答え返し）

- 症状(オーナー実機): worker 経由 consult で reader(web ChatGPT)が空応答を返すと、
  nav.wait_complete が「完了(テキストあり)」条件を満たせず最大300秒ポーリング → worker が
  無言ロックで約5分「固まって見える」。機構自体はデッドロックせず最終的に謝罪応答で回復して
  いたが、UI に進捗が出ず所要が長すぎた。
- 原因2件: (1) wait_complete の max_wait=300 は自律エージェント向けで対話には長すぎ。
  (2) 待機中に broadcast が無く UI 無言。加えて自分の diff レビューで発見した (3) consult
  失敗時に _last_reader_answer を更新しないため consult_once が前回の古い回答を返す stale bug。
- 対応: (1) _wait_with_heartbeat — 5秒ごとに consult:waiting{secs} を配信、UI は
  「reader 考え中… Ns」表示。max_wait=CONSULT_WAIT_CAP(150s)に短縮(対話は速く可視的に失敗)。
  (2) 空/タイムアウトは consult:error を出し空 answer を配信しない。(3) _run_consult が
  回答を返し、controller が cmd["result"] に格納、consult_once はグローバルでなくそれを返す
  (この consult の結果だけを渡す)。
- 教訓: 人間が張り付く対話経路と、放置される自律経路では適切なタイムアウトが違う。上流
  (chatgpt-web)の 300s を対話用に上書きするのは cockpit 側の責務。

- オーナー観察: 「人間が ChatGPT に質問を打つことは無い。自然なのは Gemma に
  『ChatGPTに聞いて』と頼むこと」。2026-07-01 の「consult の引き金は人間駆動」決定を、
  実物を触った上での再判断として撤回。
- 設計(オーナー ratify): (1) 発動は明示指示のみ — 小型モデルの自律判断ブレ
  (過少/過剰発動)を排除。自律化は必要になったら後段。(2) 左ペインは純観測ミラー化、
  入力は worker の1箇所(repo 欄はヘッダーへ)。/consult ルートは API として存続。
- 機構: WORKER_SYSTEM(逐語はオーナー提示済み)を reader 在時のみ per-call 注入(履歴には
  入れない)。worker が ```consult ブロックを発話 → parse_consult_text → consult_once
  (API reader なら直接 / scrape なら _cmd_q に done Event 付きで投入し待機) → 回答を
  [Reader's answer] として FORWARD_CAP で履歴に注入 → worker が統合回答。
  不変条件は不変(repo 本文は reader の transient と中央レーンのみ)。
- Deferred「Gemma 自律 consult」はこの明示委任形で消化。完全自律(タスク重さで自判)は
  当面 won't do — 発動判断のブレ(gemma-prompt の前提)に対し利得が薄い。
- 検証: e2e(mock)に tool-loop テスト追加(18本・1.4s)。実機で日本語依頼→Gemma が英語の
  consult ブロック→本物 ChatGPT が repo 探索→Gemma が日本語統合(tests/test_e2e.py まで
  引用)を完走。モックの教訓: システムプロンプトにマーカー文字列が含まれるため、mock の
  ルーティングは system role を除外して走査する(マーカー衝突は本物のバグ類型)。

## 2026-07-03 UI磨き＋モックLLMで「テストむずい」を潰す

- UI(操作性、html-deck/review-server の規律を適用): ボタンが作業状態を語る(consult…
  round N・busy 中 disabled)、answer は本文カード＋forward をその場に(3ホップ→1ホップ、
  リロード時も /state の last_answer から復元)、巨大 brief は折り畳み、textarea 自動伸長
  ＋Enter/Shift+Enter、repo 欄を独立行、説明注釈は現物で置換(explore を入力欄の隣へ)、
  worker 下段を2段化(1/3幅でのボタン見切れ修正)。/state に last_answer 追加。
- テスト困難の正体 = SSE＋非同期＋LLM の非決定性＋consult 40秒。処方 = tests/mock_llm.py
  (決定的・即答の OpenAI 互換 SSE。brief を見たら fetch を1回出し、配膳を見たら固定回答)。
  tests/test_e2e.py が mock＋cockpit を子プロセスで立て、実 HTTP で chat/explore/consult/
  forward/不変条件/旧alias404 を検証。スイート全体(17本)で ~1秒。
- 手動 UI 確認もモックで: README のテスト節にコマンド。実 LLM は doctor が担当(疎通1発)。

## 2026-07-03 scrape reader を repo に vendor（主役復帰）

- 背景: オーナー確定「reader に API 課金はしない(するなら Claude Code に課金する)」。
  第三者ツールに「ChatGPT アカウントでログイン」の正規手段は存在しない(first-party
  OAuth は OpenAI 自身の拡張のみ)ため、無課金の強い reader = scrape が唯一解。
  公開版で optional 降格した scrape が、実利用者にとっては主経路と判明した。
- 対応: nav/ask/cdp(純 stdlib・自己完結・全て自作)を `scrape/` に vendor。解決順
  $COCKPIT_SCRIPTS → <repo>/scrape → ~/.claude/skills/chatgpt-web/scripts。
  README に手順昇格＋性質の明記(自分のセッションの自動化・ToS グレー・Cloudflare で
  壊れうる・自己責任・無料アカウント可)。
- 「vendor するな」規約の更新: 公開配布が理由。二重管理のリスクは「上流(chatgpt-web)で
  直してから scrape/ に再コピー」の運用ルールで受ける(CLAUDE.md に明記)。
- これで clone したインターンは Gemma API キー＋ChatGPT 手動ログインだけでフル機能。

## 2026-07-03 公開実行：github.com/yomi202703/consult-cockpit (public, MIT)

- `gh repo create --public --source . --push` で公開。公開後検証: リモートツリー全数に
  .env/鍵ファイル無し、_dev/ にエンドポイント/キーの漏れ無し(improver へのパス言及のみ)。
- _dev/(開発台帳)は公開に含める判断 — 秘密ゼロで、設計経緯が読める資料としての価値を優先。

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
