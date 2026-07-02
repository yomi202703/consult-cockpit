# TODO — consult-cockpit

## Active
- P1 公開(public GitHub)化: /gemma* legacy alias 削除、env.py の _INTERNAL_FALLBACK 1行削除、社内資産スクラブ、ライセンス、最小スモークテスト、雇用者サインオフ
- P2 OAuth ループバックログイン（提供元のみ）: openExternal+PKCE → 127.0.0.1/callback → キー発行 → キーチェーン。device code フォールバック

## Deferred
- Gemma 自律 consult: Gemma に「ローカル探索」「ChatGPT consult」の2ツールを持たせ、タスクの重さで自分で選ばせる [実タスクで回したくなったら]
- 別マシン配布の実地: .env 配布 + 各マシンの Chrome サインイン手順の doku [配布先が決まったら]
- アイドル時ミラー最適化: 現状 1.5s ごとに Chrome を叩く [常用で気になったら]
