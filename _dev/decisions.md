# consult-cockpit _dev / decisions（append-only）

過去エントリは書き換えない。

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
