# Playback for Notion — 設計書

Notionデータベース上の音声・動画ファイルをiPhoneで再生／ダウンロードする汎用iOSアプリ。
既存のNHKラジオ録音DBが初期プリセットだが、任意のDBに接続できる。

## 決定事項（ユーザー合意済み 2026-10-18）

| 項目 | 決定 |
|---|---|
| 配布 | B案: App Store一般公開（TestFlightで検証後） |
| 認証 | Notion OAuth（public connection）＋ Worker中継。副導線としてBYOT（自分のトークンを貼る）もUX付きで用意 |
| 名前 | 「Playback for Notion」（ホーム表示名「Playback」）。App Store同名なし確認済み |
| Bundle ID | `dev.satoki.playback`（Team `QVUR5T7J46`） |
| 対象 | iPhone専用・iOS 17+ |
| 機能 | 再生フルセット（下記）。CarPlayのみv1.1 |
| 配置 | 本リポジトリ配下 `ios/`（アプリ）と `worker/`（認証中継） |

## 全体構成

```
iPhone App (SwiftUI/SwiftData/AVFoundation)
  │  1. ASWebAuthenticationSession で Notion認可画面
  │  2. code を Worker 経由で token に交換（client_secret はアプリに入れない）
  │  3. 以後は access_token で Notion API を直接呼ぶ
  ├──────────────► Cloudflare Worker「playback-auth」
  │                  POST /oauth/exchange, POST /oauth/refresh
  │                  GET  /oauth/callback (アプリへ302), GET /privacy, GET /health
  └──────────────► Notion API (api.notion.com/v1, Notion-Version: 2022-06-28)
```

- Notion-Version は既存アップローダー `nhk_recorder/notion.py` と同じ `2022-06-28` に固定する
  （`databases/{id}/query` 等の形が検証済み。新 data_sources API 移行は将来課題）。
- Worker はコード交換専用。トークンを保存・ログに出さない。client_secret は Wrangler secret のみ。
- NotionファイルURLは署名付きで約1時間で失効する。再生／ダウンロード直前に
  `GET /v1/pages/{id}` でメディア列を再取得してURLを取り直す（`external` 型はそのまま）。
  ダウンロード済みファイルはローカル再生する。

## 認証フロー（OAuth・主導線）

1. アプリが `state`（乱数）を生成し、ASWebAuthenticationSession で次を開く:
   `https://api.notion.com/v1/oauth/authorize?owner=user&client_id=…&response_type=code&redirect_uri=<Worker>/oauth/callback&state=…`
2. ユーザーが許可すると Worker の `/oauth/callback?code=…&state=…` へ戻る。
   Worker は `playbacknotion://oauth?code=…&state=…` へ 302 し、アプリが受け取る。
3. アプリは `state` を検証し、Worker `POST /oauth/exchange {code, redirect_uri}` を呼ぶ。
   Worker は Basic 認証（client_id:client_secret）で `POST /v1/oauth/token` に交換し、結果をそのまま返す。
4. `access_token` / `refresh_token` / ワークスペース情報を Keychain に保存。
   401時は Worker `POST /oauth/refresh {refresh_token}` で再取得する。

## トークン接続（BYOT・副導線）— UX仕様

OAuthで許可し忘れたDBや、自分の internal connection を使いたい人向け。

- ステップ表示（1. 接続を作成 → 2. トークンをコピー → 3. ここに貼る → 4. DBに接続を追加）で案内する。
- 作成画面へのディープリンク、貼り付け時の即時検証（`GET /v1/users/me`）と成功時のワークスペース名表示。
- エラーは原因別に日本語で説明する（形式不正／権限なし／DB未共有）。

## DB接続と列マッピング（汎用化の核）

接続は複数DBを登録可能。各接続ごとにマッピングを保存する。

1. DBの指定: アクセス可能なDB一覧（`POST /v1/search`）から選ぶ／DBのURL・IDを貼る（URLから32桁hexを抽出）。
2. スキーマ取得（`GET /v1/databases/{id}`）→ 自動判定:
   - メディア列: `files` 型を候補に自動選択（複数あればユーザー選択）。
   - タイトル列: `title` 型を自動採用。
   - その他の列: 一覧・詳細に表示する列と、並び替えキー（date優先）を選べる。
3. 先頭行をプレビューして確定。
4. NHKラジオDBプリセット: 番組名/音声ファイル/放送日/チャンネル/時間帯/録音時間(分)/キーワード を初期値にする。

プロパティ値は型ごとに文字列化して保持する（title, rich_text, select, multi_select, date,
number, checkbox, url, email, phone_number, status, people, created_time, last_edited_time,
formula, rollup, relation件数, files件数）。詳細画面では全列を表で見せる。

## 画面と再生機能（Q3フルセット）

- タブ: ライブラリ / ダウンロード / 履歴（続きから再生）/ 設定。タブバー上に常駐ミニプレイヤー。
- ライブラリ: 接続DB切替、検索、フィルタ（select列等）、ソート、行に任意列を表示。
  選択モードで複数行を選んで一括ダウンロード（他列を見ながら選べることが要件）。
- 詳細: 全プロパティ表、メディアファイル一覧（1ページ複数ファイル対応）、
  再生・ダウンロード・お気に入り・再生済み切替・Notionで開く。
- 再生: バックグラウンド再生、ロック画面／コントロールセンター操作、AirPlay、動画PiP、
  0.5–3.0倍速、±15秒スキップ、シーク、キュー、連続再生、リピート（なし/全曲/1曲）、シャッフル、
  スリープタイマー、再生位置の自動保存とレジューム、割り込み（着信等）からの復帰。
- ダウンロード: バックグラウンドURLSession、進捗表示、キャンセル／再試行、
  容量管理画面（合計・個別削除・全削除）、ダウンロード済みフィルタ。

## データモデル

- Keychain: access_token / refresh_token / BYOTトークン / ワークスペース情報（認証種別つき）。
- SwiftData:
  - `DatabaseConnection`: DB id・タイトル・アイコン・マッピング（メディア列/タイトル列/表示列/ソート）・最終同期。
  - `PlaybackProgress`: ページid＋ファイル名 → 再生位置・完了・お気に入り・最終再生日時。
  - `DownloadRecord`: ページid＋ファイル名 → ローカルパス・サイズ・ダウンロード日時。
- ファイル保存先: `Application Support/Downloads/<pageId>/…`（iCloudバックアップ除外）。
- ライブラリ行データはメモリ＋軽量キャッシュ。オフライン時はダウンロード済み一覧が主導線。

## Worker「playback-auth」仕様

| エンドポイント | 役割 |
|---|---|
| `GET /health` | 死活確認 `{ok:true, service:"playback-auth", version}` |
| `GET /oauth/callback` | code/state（またはerror）を `playbacknotion://oauth?…` へ302 |
| `POST /oauth/exchange` | `{code, redirect_uri}` を Notion token に交換して返す |
| `POST /oauth/refresh` | `{refresh_token}` で access_token を再取得して返す |
| `GET /privacy` | プライバシーポリシー（日英）— App Store提出用 |
| `GET /support` | サポートページ — App Store提出用 |

- Secrets: `NOTION_CLIENT_SECRET`（必須）。Vars: `NOTION_CLIENT_ID`, `NOTION_REDIRECT_URI`, `APP_SCHEME`。
- セキュリティ: redirect_uri は設定値と完全一致のみ許可。code/token はログに出さない。
  メソッド制限、JSON以外のボディ拒否、Notionのエラーはステータスを保って素通し。
- Observability（Logs/Traces）を有効化する。

## テスト方針

- Worker: 型チェック＋ローカル起動で /health・/oauth/callback の302・不正リクエストの4xx を確認。
- iOS単体: プロパティ文字列化、DB URLからのID抽出、マッピング自動判定、時間フォーマット。
- 実機相当: Xcodeシミュレータ＋Orca（orca-emulator）でオンボーディング〜再生〜DLを通す。
  実データ検証はユーザー登録（次節）完了後に実施。

## リリースゲート（証跡必須）

1. ASCにアプリレコード作成（Bundle ID登録→アプリ作成）。ASC APIキー `4485SH762T` 使用可否を確認。
2. アーカイブ前: source preflight。アップロード前: binary preflight（指紋を保存）。
3. TestFlight処理完了→実機で該当ビルドを検証し審査動画を新規撮影。
4. メタデータ・プライバシー回答・スクリーンショット・審査メモ（審査用デモ接続の案内つき）を整合。
5. 提出クリック直前にユーザー確認。提出後に提出詳細ページで全アイテムの状態を確認して完了とする。

## ユーザー作業チェックリスト（順番が重要）

1. **Cloudflare**: `npx wrangler login`（このMacで未ログインなら）。その後こちらで
   `playback-auth` をデプロイし、確定ドメインを共有する。
2. **Notion public connection 登録**（https://app.notion.com/developers/connections）:
   - 種別: Public、名前: `Playback for Notion`
   - Redirect URI: `https://playback-auth.satoki252595.workers.dev/oauth/callback`
   - Capability: Read content のみ（書き込み不要）
   - 発行された `OAuth client ID` と `OAuth client secret` をローカルファイル経由で共有
     （secret は Worker secret に入れる。git・チャット添付ファイルに入れない）。
3. **App Store Connect**: Issuer ID の共有（APIキー `4485SH762T` と対）。
   アプリレコード作成をAPIで行う場合はこちらで実施。
4. 審査用に、サンプルメディア入りDBを1つ用意（公開可能な音声/動画でOK）。

## 公開作業の進捗（2026-10-19）

- 追跡Issue: https://github.com/satoki252595/nhkRadio/issues/14
- Notion OAuth接続を作成済み。Client ID: `3fdd872b-594c-81c5-a259-0037b004178a`。コンテンツ読み取りのみ、更新・挿入・コメント権限なし。各ユーザーが自分のワークスペースに接続する。
- Client SecretはGit外の保護ファイルからWorker secretに登録済み。iOS/WorkerのClient IDを一致させた。
- Worker本番デプロイ: `c46fb1a6-f77f-4777-9517-ffcbba2b8338`。URLクエリをログ・トレースから除外。
- Xcode Apple Accountログイン済み。Apple Program更新契約（2026-10-14発効）はユーザー承認後、2026-10-18の同意を確認。
- Bundle IDをAppleに登録済み。App ID prefixは登録画面で `QVUR5T7J46` を確認。
- ASCアプリ作成済み: https://appstoreconnect.apple.com/apps/6824236423/distribution （SKU `dev.satoki.playback`、日本語）。
- 初回公開地域はユーザー指定で日本のみ。無料、IAPなし、承認後自動リリースを使用する。
- commit/pushと公開作業は今回のユーザー指示で許可済み。最終提出直前確認は別途行う。
- iOSテスト14/14、既存Pythonテスト82/82、Worker型チェック・dry-run、本番ルート7件のHTTP応答を確認。実ユーザーOAuthと実機再生はまだ未検証。

上の旧ユーザー作業チェックリストは着手前の記録。現在の提出可否は `docs/release/release-manifest.md` とGit外の候補別preflight証跡を参照する。

## OAuth再接続時の案内（2026-10-19）

Notionの「権限がすでに付与されています」は認証失敗ではない。「ページを選択する」→使用DBを選択→許可で再接続する。実際の認可画面でこの導線を確認した。ユーザー情報取得は不要のため無効化し、認可画面からユーザー／メールアドレスの表示権限が消えたことを再読込で確認した。

アプリ初回画面にこの案内を追加し、OAuth中継を経由する認証更新についても正確な保存説明へ揃えた。変更後のiOSテスト14件合格。根拠: https://developers.notion.com/guides/get-started/authorization

## 共有URL検索・保存コピー削除後の再生（2026-10-20）

DB接続画面へNotionの「リンクをコピー」で得たURLをそのまま貼ると検索する。URLのパスからDB IDを読み取り、`v=`のビューIDやworkspace名中のUUIDと区別する。未共有のDBはURLだけでは取得できないため、入力を保持してNotionでアクセスを許可し、同じDBを再検索する導線を置く。

ダウンロード削除は端末の保存コピーの削除。Notionに元ファイルがある項目はライブラリに残り、次の再生で元ファイルを取得し直す。削除したローカルURLをプレイヤーに保持させない。単件削除・一括削除・再生準備中の削除を回帰テストする。
