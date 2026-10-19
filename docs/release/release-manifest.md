# Playback for Notion — リリース管理

更新: 2026-10-20。初回公開、**審査未提出**。ビルド2の候補は `release/playback-1.0.0-2` で管理する。
追跡Issue: https://github.com/satoki252595/nhkRadio/issues/14

| 項目 | 値 |
|---|---|
| Bundle ID / prefix / Team | `dev.satoki.playback` / `QVUR5T7J46` / `QVUR5T7J46`（Apple登録画面で確認） |
| バージョン / ビルド | `1.0.0` / `2` |
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
