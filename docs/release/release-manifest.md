# Playback for Notion — リリース管理

更新: 2026-10-20。初回公開、**審査未提出**。ビルド3の候補は `release/playback-1.0.0-3` で管理する。
追跡Issue: https://github.com/satoki252595/nhkRadio/issues/14

| 項目 | 値 |
|---|---|
| Bundle ID / prefix / Team | `dev.satoki.playback` / `QVUR5T7J46` / `QVUR5T7J46`（Apple登録画面で確認） |
| バージョン / ビルド | `1.0.0` / `3` |
| ASC App ID / SKU | `6824236423` / `dev.satoki.playback` |
| 対象 | iPhone専用、iOS 17+、拡張ターゲットなし |
| 言語 / 地域 | 日本語 / 日本のみ（ユーザー決定） |
| 価格 / IAP | 無料 / なし |
| 公開方法 | 審査承認後に自動リリース、提出直前はユーザー確認 |
| OAuth Client ID | `3fdd872b-594c-81c5-a259-0037b004178a` |
| Callback | https://playback-auth.satoki252595.workers.dev/oauth/callback |
| Privacy / Support | 同ドメインの `/privacy` / `/support` |
| Worker deployment | `c46fb1a6-f77f-4777-9517-ffcbba2b8338` |
| 検証 | iOS 14/14、Python 82/82、Worker typecheck/dry-run、公開HTTPルート7件合格 |
| 未検証 | 実ユーザーOAuth・実Notionメディア・実機の再生/割込み/バックグラウンド・TestFlight |
| 既存スクリーンショット | `ios/store-screenshots/6.9/` は旧Debugビルド、候補更新後に再撮影する |

公開候補のフルcommit/branch、固定archive/IPA、source/binary/complete config/reportと指紋は、候補固定後に `/Users/satoki252595/.config/playback/release/` へ保存する。元ソースcommitと後日の証跡commitは区別する。候補固定前のprobe archiveはアップロードしない。

ビルド1はアップロード時にXcodeがarchiveへ配信記録を追記し、アップロード前の検証ハッシュと不一致になったため提出しない。ユーザー承認により、機能を変えずビルド番号のみ2へ更新する。旧候補 `6ba28847700f7250f80cc415c43cb56f87a431d4` と `candidate2/` は保持する。新証跡はGit外の `candidate3/` へ保存し、検証済みIPAを直接アップロードする。

過去のsandbox失敗と再検証は [初回報告](codex-prep-report.md) と [再検証報告](codex-prep-report-v2.md) に履歴として保持する。旧 `source-preflight.draft.json` は未提出時のドラフトであり、今回の公開判定には使わない。

## ビルド3の変更（公開前の実機確認からの修正）

- DB接続欄にNotionの共有URLを貼ると自動検索し、検索結果から列設定へ進む。app.notion.com/p/<workspace>/<DB-ID> と notion.so のリンクに対応し、ビューIDやworkspace中の別UUIDをDB IDとして採用しない。
- DBが未共有の場合は、入力URLを保持して同画面からNotion OAuthのアクセス許可追加と再検索を行える。トークン接続には対象DBへ接続を追加する説明を表示する。再認可のキャンセルでは既存セッションを削除しない。
- ダウンロードの単件・全削除時、削除した保存ファイルを参照中のプレイヤーを解放する。ライブラリからの次回再生は元メディアを再取得する。再生準備中の古いURL取得が、削除後の再生へ戻ってくる競合も防止する。
- 候補2（9cfa433a747c97e9f81886e6410d6c407c29d0b2）とcandidate3/の証跡は保持する。ビルド2の本人実機確認はビルド3の検証として流用しない。新しいsource/binary/complete証跡はGit外candidate4/へ保存し、提出前に新TestFlight版で再確認する。
- 変更後のiOSテスト19件が合格。公開候補固定後の最終検証結果はGit外の記録を参照する。審査は未提出。
