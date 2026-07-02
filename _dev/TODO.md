# TODO — consult-cockpit

## Active
- P1 reader の API 経路実装: READER_LLM_* を実配線（consult を API reader でも動かす。休眠設定・doctor 行は済み） [設計=_dev/design_auth.md]
- P2 OAuth ループバックログイン（提供元のみ）: openExternal+PKCE → 127.0.0.1/callback → キー発行 → キーチェーン。device code フォールバック
- P2 公開(public GitHub)化: /gemma* legacy alias 削除、env.py の _INTERNAL_FALLBACK 1行削除、社内資産スクラブ、ライセンス、最小スモークテスト

## Deferred
- Gemma 自律 consult: Gemma に「ローカル探索」「ChatGPT consult」の2ツールを持たせ、タスクの重さで自分で選ばせる [実タスクで回したくなったら]
- 別マシン配布の実地: .env 配布 + 各マシンの Chrome サインイン手順の doku [配布先が決まったら]
- アイドル時ミラー最適化: 現状 1.5s ごとに Chrome を叩く [常用で気になったら]
