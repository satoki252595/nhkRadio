# SaaS 移行ロードマップ

購読リスト（`series_ids`）を Pages UI → 永続化層 → 録音ワーカー へ伝播させる仕組みを
段階的に拡張していくためのメモ。

## 現在のアーキテクチャ

```
[Pages UI]
   │ ☁ GitHubへプッシュ (ブラウザ内の PAT)
   ▼
[GitHub Contents API]
   │ commit data/subscriptions.json
   ▼
[GitHub Actions record.yml]
   │ python -m nhk_recorder --subscriptions data/subscriptions.json
   ▼
[録音 → Notion アップロード]
```

- 購読データは `{series_ids: string[], updated_at: string, user_id?: string}` 形式
- Web 側は `SyncAdapter` インタフェース (`web/src/lib/sync/types.ts`) で抽象化済み
- GitHub 実装は `web/src/lib/sync/github.ts`
- 録音 CLI は `--subscriptions` にローカルパス / http(s) URL どちらも受け付ける

## フェーズ別移行計画

| フェーズ | ユーザー数 | 永続化層 | 録音ワーカー | 認証 |
|---|---|---|---|---|
| **Phase 1 (現在)** | 1〜数人 | GitHub file (`data/subscriptions.json`) | GitHub Actions (cron) | Fine-grained PAT (ブラウザ localStorage) |
| **Phase 2** | 10〜100 | Cloudflare KV / D1 or Supabase | GitHub Actions (matrix) or Cloudflare Workers Cron | OAuth (GitHub / Google) |
| **Phase 3** | 100+ | Postgres (Supabase / Neon) | 専用ワーカー (Fly.io / Render / ECS) | JWT / Session Cookie |

## Phase 2 への移行タスク

### Web フロントエンド

- [ ] `createRestApiAdapter(baseUrl, authToken)` を `web/src/lib/sync/` に追加
  - `SyncAdapter` インタフェースはそのまま流用
  - GET `/api/users/:id/subscriptions` → `pull`
  - PUT `/api/users/:id/subscriptions` → `push`
- [ ] `/subscriptions` ページで GitHub / REST のバックエンド切替 UI
- [ ] OAuth ログインフロー（GitHub App / Supabase Auth など）
- [ ] `subscriptions` ストアに `user_id` を埋める

### バックエンド (新規)

- [ ] Cloudflare Workers or Supabase Edge Functions で API
  - `GET /api/users/:id/subscriptions`
  - `PUT /api/users/:id/subscriptions`
  - 認可: JWT または OAuth access token 検証
- [ ] 永続化: KV (`user:{id}:subscriptions`) or `subscriptions` テーブル

### 録音ワーカー

- [ ] GitHub Actions を **matrix 戦略** でユーザーごとに並列実行
  ```yaml
  strategy:
    matrix:
      user_id: ${{ fromJson(needs.list-users.outputs.ids) }}
  steps:
    - run: |
        python -m nhk_recorder \
          --subscriptions https://api.example.com/users/${{ matrix.user_id }}/subscriptions \
          --within 65
  ```
- [ ] 事前 job でユーザー一覧を API から取得して `outputs` に流す
- [ ] ユーザーごとの Notion 設定（token / DB）を Actions Secrets or API で供給

## Phase 3 への移行タスク

- [ ] GitHub Actions → 専用ワーカー (cron + キュー) へ移行
  - 同時実行数やリトライの制御
  - Notion アップロード失敗時の再送キュー
- [ ] 録音ファイル保管: GitHub Artifacts → S3 / R2
- [ ] ユーザーごとの利用制限 (録音時間 / ストレージ)
- [ ] 課金: Stripe 連携

## 今のコードで保たれている抽象

- **`SyncAdapter` インタフェース** — Phase 2 では `createRestApiAdapter` を追加して
  `createGitHubSyncAdapter` と並列に選択可能にするだけ
- **`nhk_recorder --subscriptions` の URL 対応** — Phase 2 で
  `https://api.example.com/...` をそのまま渡せる
- **`{series_ids, updated_at, user_id?}` スキーマ** — マルチテナント化時に
  破壊的変更なしで `user_id` を必須化できる

## 決めておくべきこと

- ユーザー ID の形式（GitHub login / UUID / OAuth sub）
- Notion 連携をユーザーごとに持たせるか、共通 DB に寄せるか
- 録音ファイルの配信形態（ユーザー private S3 / Notion 埋め込みのみ / etc）
- Phase 2 移行のトリガー（ユーザー数 / PAT 運用の限界）
