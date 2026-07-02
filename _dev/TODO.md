# TODO — consult-cockpit

## Active
- P1 any-API 一般化: env を `LLM_*`（旧 `WORKER_LLM_*` エイリアス）へ、provider アダプタで認証ヘッダ/ストリーム差を吸収、doctor/docs 追従 [設計=_dev/design_auth.md]
- P1 SecretStore 抽象: get/set/delete、standalone=OSキーチェーン / 拡張=SecretStorage。生キーを設定・.env に置かない
- P2 OAuth ループバックログイン（提供元のみ）: openExternal+PKCE → 127.0.0.1/callback → キー発行 → キーチェーン。device code フォールバック
- P2 公開(public GitHub)化: スクレイプ・レーンを既定から外し standalone 化、社内資産スクラブ、ライセンス、最小スモークテスト

## Deferred
- Gemma 自律 consult: Gemma に「ローカル探索」「ChatGPT consult」の2ツールを持たせ、タスクの重さで自分で選ばせる [実タスクで回したくなったら]
- 別マシン配布の実地: .env 配布 + 各マシンの Chrome サインイン手順の doku [配布先が決まったら]
- アイドル時ミラー最適化: 現状 1.5s ごとに Chrome を叩く [常用で気になったら]
