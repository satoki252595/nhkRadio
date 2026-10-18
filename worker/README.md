# playback-auth

「Playback for Notion」iOSアプリの OAuth トークン交換中継 Worker。
Notion の client secret をアプリに埋め込まないために、認可コード → トークン交換だけを担当する。
コードやトークンは保存せず、ログにも出さない。

## エンドポイント

| パス | 役割 |
|---|---|
| `GET /health` | 死活確認 |
| `GET /oauth/callback` | Notion からのリダイレクトを受け、`playbacknotion://oauth?…` へ302 |
| `POST /oauth/exchange` | `{code, redirect_uri}` を Notion トークンに交換 |
| `POST /oauth/refresh` | `{refresh_token}` でアクセストークン再取得 |
| `GET /privacy` | プライバシーポリシー（App Store 用） |
| `GET /support` | サポートページ（App Store 用） |

## セットアップ（順番厳守）

```sh
npm install
npm run deploy            # 1. 先にデプロイして確定ドメインを得る
# 2. Notion の public connection を登録（Redirect URI = https://<domain>/oauth/callback）
# 3. 発行された client ID / secret を設定する:
npx wrangler secret put NOTION_CLIENT_SECRET
# 4. wrangler.jsonc の vars (NOTION_CLIENT_ID / NOTION_REDIRECT_URI) を埋めて再デプロイ
npm run types && npm run check && npm run deploy
```

ローカル開発は `.dev.vars.example` を `.dev.vars` にコピーして使う（git 対象外）。

## 検証

```sh
npm run check     # tsc --noEmit
npm run dry-run   # wrangler deploy --dry-run
npm run dev       # ローカル起動後: curl http://127.0.0.1:8787/health
```
