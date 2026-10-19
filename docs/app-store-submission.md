# Playback for Notion — App Store 提出ドラフト（v1.0.0 / build 2）

状態: Notion OAuth登録・Worker設定・Xcodeログイン・ASCアプリ作成は完了。公開候補のarchive/export/preflightとTestFlight実機検証を進行中。審査未提出。

## リリース同定

| 項目 | 値 |
|---|---|
| 種別 | 初回リリース |
| アプリ名 | Playback for Notion |
| Bundle ID | `dev.satoki.playback` |
| Team | `QVUR5T7J46` |
| バージョン / ビルド | 1.0.0 / 2 |
| 主言語 | 日本語 |
| カテゴリ | ミュージック（副: ユーティリティ） |
| 価格 | 無料（IAPなし） |
| 対象 | iPhone, iOS 17+ |
| ASC アプリID | `6824236423` |
| プライバシーポリシー | https://playback-auth.satoki252595.workers.dev/privacy |
| サポートURL | https://playback-auth.satoki252595.workers.dev/support |
| OAuth Redirect URI | https://playback-auth.satoki252595.workers.dev/oauth/callback |

## メタデータ（日本語）

- サブタイトル（30字）: `DBの音声・動画プレイヤー`
  ※商標語を入れない（審査チェックリスト準拠）。「Notion」はアプリ名の互換表示のみ。
- キーワード（100字）: `音声プレイヤー,動画,ラジオ,録音,オフライン,mp3,m4a,データベース,倍速,バックグラウンド再生`
  ※他社商標・他アプリ名を含めない。
- 説明文:
  ```
  Playback for Notion は、Notion のデータベースに保存した音声・動画ファイルを
  iPhone で再生するためのプレイヤーです。

  ■ できること
  ・データベースのファイル列を選ぶだけで、一覧からタップ再生
  ・他の列（日付・セレクト・テキスト等）も一覧と詳細で確認
  ・必要な回を選んでダウンロードし、オフライン再生
  ・バックグラウンド再生、ロック画面・コントロールセンター操作、AirPlay
  ・0.5–3.0倍速、±15秒スキップ、再生位置の自動保存と続きから再生
  ・キュー、連続再生、リピート、シャッフル、スリープタイマー、動画のPiP
  ・検索、フィルタ、お気に入り、再生履歴

  ■ 接続方法
  「Notionでサインイン」（OAuth）または自分の接続トークンで接続できます。
  トークンは端末のKeychainに保存されます。OAuthのコード交換・認証更新時のみ
  開発者の中継サーバーを経由し、中継サーバーでは永続保存しません。
  アカウントなしで試せるデモライブラリも内蔵しています。

  ※ 本アプリは Notion Labs, Inc. と提携していない独立したアプリです。
  ```
- プロモーションテキスト: `DB内の音声・動画をタップ再生。ダウンロードでオフライン対応。`

## プライバシー回答

- データ収集: なし（`Data Not Collected`）
- トラッキング: なし（PrivacyInfo.xcprivacy 済）
- 暗号化: `ITSAppUsesNonExemptEncryption = false` 設定済み
- 権限: カメラ/マイク/写真等の要求なし（UsageDescription 不要）

## 年齢レーティング

4+想定（ユーザー生成コンテンツは本人のNotion内のみ・共有機能なし）。

## App Review Notes ドラフト（要: 実ビルド番号・実機・動画情報を差し込む）

```
Playback for Notion plays audio/video files stored in the user's own
Notion databases.

No account is required to review the core experience:
1. Launch the app.
2. Tap "デモライブラリで試す（アカウント不要）" on the first screen.
3. A sample library opens. Tap any row's play button to play audio,
   tap the row for details (all database columns), use the download
   button to save media for offline playback, and open the mini
   player to try speed/sleep-timer/queue controls.

Optional full flow: "Notionでサインイン" (OAuth) or
"自分のトークンで接続" connects the reviewer's own Notion workspace;
the user then selects a database and its media (files) column.

Privacy: tokens stay in the device Keychain. The developer's relay
server only exchanges the OAuth authorization code and stores
nothing. No analytics, no ads, no in-app purchases.
```

審査動画は TestFlight 実ビルドを実機で新規撮影すること（開発ビルド・旧ビルド不可）。

## スクリーンショット

6.9"（iPhone 17 Pro Max 等, 1320×2868）セットを最終候補ビルドで撮影する。
撮影対象: ライブラリ / 詳細（全列）/ 再生中 / ダウンロード / 接続・マッピング。
iPad 非対応のため iPad セット不要。

## 公開の残ゲート（2026-10-19）

1. 候補commit/push → source preflight → Release archive/export → binary preflight。
2. TestFlightアップロードと処理完了 → 実機確認・審査動画の新規撮影。
3. 最終候補UIのスクリーンショットと掲載情報、プライバシー・年齢レーティング・日本のみの配信地域を整合。
4. complete preflight → 提出直前の最終確認 → 審査提出 → 提出詳細の状態確認。

Notion Client IDは `3fdd872b-594c-81c5-a259-0037b004178a`。各ユーザーが自分のワークスペースとDBを選択する。秘密値はリポジトリ外。無料・IAPなし、日本のみ、承認後に自動リリース。
追跡: https://github.com/satoki252595/nhkRadio/issues/14
