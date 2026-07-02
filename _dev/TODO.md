# TODO — consult-cockpit

## Active
（なし）

## Deferred
- OAuth ループバックログイン（提供元のみ）: PKCE → 127.0.0.1/callback → キー発行 → キーチェーン。device code フォールバック [OAuth を提供する有料プロバイダ(Anthropic 等)を reader に使う人が現れたら]
- 別マシン配布の実地: .env 配布 + 各マシンの Chrome サインイン手順の doku [配布先が決まったら]
- アイドル時ミラー最適化: 現状 1.5s ごとに Chrome を叩く [常用で気になったら]
