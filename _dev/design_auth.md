# 設計ノート: チーム版 / 公開版の認証と資格情報

status: 提案（未実装）。根拠は 2026-07-02 の VSCode 拡張3種の実物解剖
(`github-authentication` / `microsoft-authentication` / `anthropic.claude-code`)。
decisions.md 2026-07-02 に方針エントリ、実装キューは TODO.md。

## 前提
- ツールの本質は文脈オフロード: worker(小/安モデル=Gemma)が repo 読解を reader(強モデル)に
  外注し、自分の永続 context を痩せたまま保つ。認証を変えてもこの不変条件は不変。
- 想定ユーザーが「任意 API を使う社内チーム」に変わった。よって raw な OpenAI 互換
  エンドポイントは OAuth 不要・API キーだけで足りる。OAuth は「出している相手」だけの上乗せ。

## 解剖で分かった事実（一次資料）
- VSCode 拡張のクリーンなログインは、中にブラウザを埋めず、システムブラウザへ委譲し
  `vscode://` ディープリンク or `127.0.0.1` ループバックでトークンだけ受け取り、
  OS キーチェーン(SecretStorage)に保存する形。3拡張とも同じ基盤。
- 差は「上流がどの OAuth を出すか」だけ:
  - GitHub / Microsoft: 標準 OAuth（MS は PKCE + MSAL、device code フォールバック）。
  - Anthropic Claude Code: `claude.com/cai/oauth/authorize` → `127.0.0.1/callback` →
    `api.anthropic.com/api/oauth/claude_cli/create_api_key` で API キーを発行 → Keychain。
  - ChatGPT(web): 第三者向け OAuth を出していない → だから CDP スクレイプが必然だった。

## 2レーン = 2つの資格情報
```
lanes:
  reader:  { provider, base_url, model }   # repo を読む強モデル (GPT/Claude/任意)
  worker:  { provider, base_url, model }   # オフロード元の小モデル (Gemma API)
```
- base_url/model は設定に置く（機密でない）。キーだけを SecretStore から provider 名で引く。
  設定ファイルに生キーを書かない。`.env` に生キーを残さない（.env.example はテンプレのみ）。

## SecretStore 抽象（Claude Code と同型・実装2つ）
インターフェイス: `get(provider) / set(provider, secret) / delete(provider)`
- standalone CLI 版: OS キーチェーン
  - macOS: `security add/find-generic-password`（service=`consult-cockpit`, account=provider）
  - Linux: libsecret / Windows: Credential Manager
- VSCode/Cursor 拡張版: `context.secrets`（内部で同じ OS キーチェーン）

## 資格情報の入れ方 = 3経路（相手の対応度で選ぶ）
1. API キー貼り付け（既定・全プロバイダで動く）
   - `consult-cockpit auth set reader` でキー入力 → キーチェーン保存。ChatGPT スクレイプの代替本命。
2. OAuth ループバックログイン（提供している相手のみ・Claude Code を踏襲）
   - `openExternal(authorize URL + PKCE)` → `http://127.0.0.1:<空きポート>/callback` で code 回収
     → token 交換 →（Anthropic 型なら）API キー発行 → キーチェーン保存。
   - リダイレクト不能環境は device code フォールバック。
3. ChatGPT web スクレイプ（optional・非既定・要フラグ）
   - 「API 課金ゼロ」を強く要る人だけの退避路。CDP+signed-in Chrome の脆さ
     （Cloudflare/DOM/失効）を明示。チーム/公開の既定からは外す（下の「公開版」参照）。

## 呼び出し時の流れ
```
起動 → 設定で reader/worker の provider/base_url/model を解決
     → SecretStore.get(provider) でキー取得（無ければ auth 経路へ誘導）
     → 各レーンは Bearer 付きで OpenAI 互換 /chat/completions を叩く
     → consult/explore/forward は現状のまま（機構不変・文脈オフロード維持）
```
- プロバイダ差の吸収: 認証ヘッダ（OpenAI=Bearer / Anthropic=x-api-key + anthropic-version /
  Azure=api-key）とストリーム差を provider アダプタで正規化。

## この設計が効く理由
- 既定を「API キー＋キーチェーン」にすれば全プロバイダで VSCode 同格のクリーンさが出る。
- OAuth を出す相手には Claude Code と同じループバックを足せる。
- ChatGPT スクレイプは optional に降格 → 脆さと ToS グレーを既定から排除。

## 公開版（public GitHub）に向けて
- 公開の鍵は「ChatGPT スクレイプ・レーンを既定から外す」こと。これで:
  - 依存が真に standalone に（chatgpt-web の nav/ask/cdp すら不要／optional extra 化）
  - OpenAI web UI 自動化の ToS グレーを公開既定から排除
- 位置づけ: Copilot/Cline/aider の競合ではなく「2モデル間の文脈オフロードを可視化・制御する
  観測ツール（誰がどのファイルを読むか）」。教材・観測という niche で立てる。
- 公開前の必須ゲート:
  - 社内資産の除去: `~/.claude/lib/improver/.env` フォールバック・内部 Gemma エンドポイント・
    社内 URL/識別子を全スクラブ。
  - 雇用者許可: インターンとして社内の時間/インフラで作った場合、公開前に会社サインオフ。
  - ライセンス（MIT 等）・秘密ゼロ（既に .env は gitignore）・正直な README（要:自前の
    エンドポイントとキー）・最小スモークテスト（現状テスト無し→公開には要追加）。
