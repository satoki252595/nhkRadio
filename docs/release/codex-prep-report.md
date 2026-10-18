# Playback for Notion — Codex 公開準備作業報告

作成: 2026-10-18T23:33:13.755732+09:00。作業場所: `/Users/satoki252595/orca/nhkRadio`。
**公開準備は未完了、提出不可**。認証情報を使わず可能な確認と、実行環境で停止した段階の記録を行った。
[release-manifest ドラフト](release-manifest.md) を併せて参照。

## 結果一覧

| タスク | 判定 | 実施結果 |
|---|---|---|
| 1. 現状把握 | 完了 | 設計・提出ドラフト、iOS/Worker の設定・ソース・git 状態を確認 |
| 2. ビルド・PlaybackTests | 不合格 / 実行阻害 | ビルド exit 65、テストコマンド exit 70。宣言 14件、実行 0件、合格 0件。テストの assertion 合否は未評価 |
| 3. 4画面撮影 | 未達 | 指定端末の登録あり。サービス接続・起動・撮影に失敗。インストール / デモ起動は未到達。新規 PNG 0枚 |
| 4. manifest | 完了（ドラフト） | 既知値を実設定と照合。不明値は「未確定（ユーザー作業）」 |
| 5. 配布可否 | 再確認完了・配布不可 | 新規 archive exit 65、既存 probe の export exit 70。IPA なし |
| 6. 報告・証跡 | 完了 | 本書、コマンド記録、出力ログ、設定照合、入力ハッシュを作成 |

## 1. 現状と作業範囲

読んだ主資料は `docs/playback-for-notion.md`、`docs/app-store-submission.md`。
`ios/project.yml`、pbxproj、共有 scheme、Info.plist、Config.swift、AppState、OnboardingView、DemoData、各対象画面、PlaybackTests、Worker の README・package.json・wrangler.jsonc・OAuth ルーティングを確認した。

開始時の読み取り結果:

```text
## main...origin/main
?? docs/app-store-submission.md
?? docs/playback-for-notion.md
?? ios/
?? worker/
```

HEAD: `903b6674e35fb1ebb30248f845e0f457b14664e8`。既存の GitHub リポジトリ `https://github.com/satoki252595/nhkRadio` を再利用。
[開始時 git status](evidence/prep-2026-10-18/git-status-before.log)、[HEAD](evidence/prep-2026-10-18/git-head.log)、[終了時 git status](evidence/prep-2026-10-18/git-status-after.log)。
`ios/`・`worker/` 自体が未追跡のため、この HEAD をアプリソースの候補固定済み commit として扱わない。

アプリ / Worker のソース・既存設定は変更していない。既存 build ディレクトリを消さず、今回の出力先は新規の `ios/build/codex-prep-2026-10-18/` とした。
[入力ファイル 46個の SHA-256](evidence/prep-2026-10-18/project-input-sha256.json) と [再照合](evidence/prep-2026-10-18/project-input-preservation.json) では、取得後の既存入力の変更・欠落は 0件。
ユーザー指定の `RTK.md` はワークスペース・祖先および `~/.codex/RTK.md` の確認範囲では見つからなかった。

## 2. 実行環境

- `xcode-select -p`: `/Applications/Xcode.app/Contents/Developer`
- `xcodebuild -version`: `Xcode 27.1` / `Build version 27A9275`（[証跡](evidence/prep-2026-10-18/toolchain.log)）
- プロジェクトの既存 `flake.nix` を確認。インストール、flake 変更、依存更新はしていない。
- 初回の `nix develop --offline --no-write-lock-file -c sh -c 'command -v python3; command -v ffmpeg; command -v ffprobe'` は exit 0 で次の既存 Nix ストアを返した（ツール応答から転記）。

```text
/nix/store/ls1816af8myfcsa4gk7626nsx6sb5yn0-python3-3.12.14-env/bin/python3
/nix/store/mv3x2v2pr6pwvwj7cdyh8nci2q1wpnjq-ffmpeg-headless-8.1.2-bin/bin/ffmpeg
/nix/store/mv3x2v2pr6pwvwj7cdyh8nci2q1wpnjq-ffmpeg-headless-8.1.2-bin/bin/ffprobe
```

その後の同じ Nix 起動は daemon 接続拒否で失敗したため、既に解決できた Nix ストアの Python を直接使ってコマンド実行・証跡保存を行った。Node も既存の Nix ストア由来（[パス証跡](evidence/prep-2026-10-18/runtime-tools.json)）。Apple 固有のビルド / export には既存 Xcode の絶対パスを使用した。依存環境を別方式で新設していない。

```sh
cd /Users/satoki252595/orca/nhkRadio
nix develop --offline --no-write-lock-file -c sh -c 'command -v python3; command -v ffmpeg; command -v ffprobe'
```
終了コード: **1**。 [実行記録](evidence/prep-2026-10-18/nix-environment-command.json) / [出力原文](evidence/prep-2026-10-18/nix-environment.log)。

```text
error: cannot connect to socket at '/nix/var/nix/daemon-socket/socket': Operation not permitted
```

## 3. ビルド・ユニットテスト

### Simulator ビルド

```sh
cd /Users/satoki252595/orca/nhkRadio/ios
/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild -project Playback.xcodeproj -scheme Playback -configuration Debug -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' -derivedDataPath /Users/satoki252595/orca/nhkRadio/ios/build/codex-prep-2026-10-18/DerivedData CODE_SIGNING_ALLOWED=NO build
```
終了コード: **65**。 [実行記録](evidence/prep-2026-10-18/simulator-build-command.json) / [出力原文](evidence/prep-2026-10-18/simulator-build.log)。

結果は `** BUILD FAILED **`。最初の根本原因と直後のコンパイラエラーは次のとおり。

```text
sandbox-exec: sandbox_apply: Operation not permitted
/Users/satoki252595/orca/nhkRadio/ios/Playback/App/AppState.swift:16:13: error: external macro implementation type 'ObservationMacros.ObservableMacro' could not be found for macro 'Observable()'; '/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/Developer/usr/bin/swift-plugin-server' produced malformed response
```

Observation / SwiftData / SwiftUI マクロの実行拒否に続いて多数の二次的コンパイルエラーが発生している。
実行環境の制約が原因と判断した。ソースを変えて仕様・マクロを除去したり、sandbox を無効化したりする修正はしていない。
根本原因をこの権限内では除去できないため、修正済み・再ビルド成功とは記録しない。

### PlaybackTests

```sh
cd /Users/satoki252595/orca/nhkRadio/ios
/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild -project Playback.xcodeproj -scheme Playback -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max,OS=26.5' -destination-timeout 15 -derivedDataPath /Users/satoki252595/orca/nhkRadio/ios/build/codex-prep-2026-10-18/TestDerivedData -resultBundlePath /Users/satoki252595/orca/nhkRadio/ios/build/codex-prep-2026-10-18/PlaybackTests.xcresult -only-testing:PlaybackTests CODE_SIGNING_ALLOWED=NO test
```
終了コード: **70**。 [実行記録](evidence/prep-2026-10-18/unit-tests-command.json) / [出力原文](evidence/prep-2026-10-18/unit-tests.log)。

```text
xcodebuild: error: Unable to find a device matching the provided destination specifier:
		{ platform:iOS Simulator, OS:26.5, name:iPhone 17 Pro Max }

	The requested device could not be found because no available devices matched the request.
```

CoreSimulator に接続できず、テスト実行前に destination の解決で停止した。
ソース上の XCTest メソッドは **14件**（NotionID 4、MappingSuggestion 2、PropertyFormatting 4、LibraryItemParsing 1、FormatHelpers 3）。
今回実行 **0件**、合格 **0件**、assertion の失敗件数は **未評価**。14件合格とは扱わない。
[宣言件数の記録](evidence/prep-2026-10-18/test-source-count.json)。

結果 bundle の生成先は `ios/build/codex-prep-2026-10-18/PlaybackTests.xcresult`。テスト合格の証拠ではない。
追加のサマリー取得も次のエラーで失敗した。

```sh
cd /Users/satoki252595/orca/nhkRadio
xcrun xcresulttool get test-results summary --path /Users/satoki252595/orca/nhkRadio/ios/build/codex-prep-2026-10-18/PlaybackTests.xcresult
```
終了コード: **64**。 [実行記録](evidence/prep-2026-10-18/test-result-summary-command.json) / [出力原文](evidence/prep-2026-10-18/test-result-summary.log)。

```text
Error: You don’t have permission to save the file “58475C18-D008-4A35-A251-ED19DB7EC487” in the folder “TestReport”.
Usage: xcresulttool <subcommand>
  See 'xcresulttool --help' for more information.
```

## 4. Simulator とスクリーンショット

実行した一覧確認コマンドは以下。両方 exit 1。

```sh
cd /Users/satoki252595/orca/nhkRadio
xcrun simctl list devices available
xcrun simctl list runtimes
```

[一覧確認の実行記録](evidence/prep-2026-10-18/inventory-commands.json)、[devices 原文](evidence/prep-2026-10-18/simulator-devices.log)、[runtimes 原文](evidence/prep-2026-10-18/simulator-runtimes.log)。
一覧が取得できないため、読み取り可能な `~/Library/Developer/CoreSimulator/Devices/*/device.plist` の端末メタデータを補助的に確認した。
[全登録一覧](evidence/prep-2026-10-18/simulator-device-metadata.json) に次の指定端末がある。

```text
name: iPhone 17 Pro Max
UDID: 14C56DCC-7626-455B-ACB4-5169C62F27DB
runtime: com.apple.CoreSimulator.SimRuntime.iOS-26-5
isDeleted: false
```

これは登録の証拠であり、ランタイムの利用可能性の証明ではない。端末不存在とは断定しない。
代替機種もサービス側の利用可能一覧を確認できず、代替撮影は行っていない。

```sh
cd /Users/satoki252595/orca/nhkRadio
xcrun simctl boot 14C56DCC-7626-455B-ACB4-5169C62F27DB
```
終了コード: **1**。 [実行記録](evidence/prep-2026-10-18/simulator-boot-command.json) / [出力原文](evidence/prep-2026-10-18/simulator-boot.log)。

```text
2026-10-18 23:27:59.591 simctl[50360:16375280] Error Domain=NSPOSIXErrorDomain Code=61 "Connection refused" UserInfo={NSLocalizedDescription=CoreSimulatorService connection became invalid.  Simulator services will no longer be available.}
Unable to locate device set: Error Domain=NSPOSIXErrorDomain Code=61 "Connection refused" UserInfo={NSLocalizedFailureReason=Failed to subscribe to notifications from CoreSimulatorService., NSLocalizedDescription=Failed to initialize simulator device set., NSUnderlyingError=0x7b82ef4870 {Error Domain=NSPOSIXErrorDomain Code=61 "Connection refused" UserInfo={NSLocalizedDescription=CoreSimulatorService connection became invalid.  Simulator services will no longer be available.}}}
```

デモの正規導線は、初回画面の「デモライブラリで試す（アカウント不要）」→ `AppState.enterDemoMode()`。
`auth.demoMode` を UserDefaults に保存し、次回起動時は `restoreSession()` が復元する。専用のデモ launch 引数はソース上ない。
詳細はライブラリの行、再生中は再生開始後のミニプレイヤー、ダウンロードは保存操作後の同名タブから開く実装。
起動前に停止しており、この UI 導線を今回実機操作できたとは主張しない。

撮影自体も失敗することを 1画面の出力先で確認した。同じ接続障害があるため、残る 3画面の重複コマンドは実行していない。

```sh
cd /Users/satoki252595/orca/nhkRadio
xcrun simctl io 14C56DCC-7626-455B-ACB4-5169C62F27DB screenshot /Users/satoki252595/orca/nhkRadio/ios/store-screenshots/01-library-iphone17promax-ios26.5.png
```
終了コード: **1**。 [実行記録](evidence/prep-2026-10-18/screenshot-library-command.json) / [出力原文](evidence/prep-2026-10-18/screenshot-library.log)。

今回の PNG は **0枚**。ファイル名・解像度・サイズの実測値は存在しない。
[保存予定名と取得状況](../../ios/store-screenshots/README.md) を作成。
`/private/tmp/playback-sim-*.png` の既存ファイルは今回の撮影物でも固定候補の証跡でもないため転用していない。

## 5. リリース設定・Worker・preflight

[manifest](release-manifest.md) に Bundle ID、Team、1.0.0 / 1、Worker URL、Redirect URI の指定値と実設定を併記した。
既知値は一致。例外は **対象デバイス**で、project.yml の base `1` を pbxproj のターゲット固有 `1,2` が上書きしている。
iPhone 専用の仕様と衝突するため記録だけ行い、今回変更はしていない。候補固定前に生成設定と生成物の整合が必要。

```sh
cd /Users/satoki252595/orca/nhkRadio/ios
/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild -project Playback.xcodeproj -target Playback -configuration Release -showBuildSettings -json
```
終了コード: **0**。 [実行記録](evidence/prep-2026-10-18/release-build-settings-command.json) / [出力原文](evidence/prep-2026-10-18/release-build-settings.log)。

ログには選択したリリース識別・署名設定と stderr のみ保存し、無関係な環境変数の一覧は保存していない。
Notion Client ID は iOS・Worker ともに空文字。Client Secret の値や実配備状況は取得していない。

Worker は既存 TypeScript による読み取り検証のみ追加した。

```sh
cd /Users/satoki252595/orca/nhkRadio/worker
node node_modules/typescript/bin/tsc --noEmit
```
終了コード: **0**。 [実行記録](evidence/prep-2026-10-18/worker-typecheck-command.json) / [出力原文](evidence/prep-2026-10-18/worker-typecheck.log)。

型チェック成功（診断出力なし）。依存の追加・インストール・デプロイ・認証は行っていない。
公開 Worker の疎通、OAuth 実通信、Notion DB 接続は今回未検証。

`release-ios-app-store` の example-config でスキーマを確認し、既知値を入れた [source-preflight.draft.json](source-preflight.draft.json) を作成した。
ASC アプリID、SKU、App ID prefix、公開方法、候補 commit は意図的に未確定としてある。提出に使える設定ではない。

```sh
cd /Users/satoki252595/orca/nhkRadio
/nix/store/ls1816af8myfcsa4gk7626nsx6sb5yn0-python3-3.12.14-env/bin/python3 /Users/satoki252595/.codex/skills/release-ios-app-store/scripts/ios_release_preflight.py verify --stage source --config /Users/satoki252595/orca/nhkRadio/docs/release/source-preflight.draft.json --strict-warnings
```
終了コード: **2**。 [実行記録](evidence/prep-2026-10-18/source-preflight-command.json) / [出力原文](evidence/prep-2026-10-18/source-preflight.log)。

```text
CONFIG_ERROR: release.app_store_connect_id must be a 6-20 digit App Store Connect app ID
```

未知の数字を捏造して preflight を通していない。入力検証で停止しているため、source の個別ゲートは合格していない。
source の clean-tree / 候補固定ゲートを迂回して本番配布を行わない。
次節の archive / export は、ユーザーが明示指定した**診断用 probe**として実施し、公開候補の作成・検証成功とは扱わない。

## 6. archive / 配布 export の再確認

### 新規 archive probe

```sh
cd /Users/satoki252595/orca/nhkRadio/ios
/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild -project Playback.xcodeproj -scheme Playback -configuration Release -destination generic/platform=iOS -derivedDataPath /Users/satoki252595/orca/nhkRadio/ios/build/codex-prep-2026-10-18/ArchiveDerivedData -archivePath /Users/satoki252595/orca/nhkRadio/ios/build/codex-prep-2026-10-18/Playback-probe.xcarchive BUILD_SOURCE_COMMIT=UNSET archive
```
終了コード: **65**。 [実行記録](evidence/prep-2026-10-18/archive-probe-command.json) / [出力原文](evidence/prep-2026-10-18/archive-probe.log)。

```text
/Users/satoki252595/orca/nhkRadio/ios/Playback.xcodeproj: error: No profiles for 'dev.satoki.playback' were found: Xcode couldn't find any iOS App Development provisioning profiles matching 'dev.satoki.playback'. Automatic signing is disabled and unable to generate a profile. To enable automatic signing, pass -allowProvisioningUpdates to xcodebuild. (in target 'Playback' from project 'Playback')
** ARCHIVE FAILED **
```

署名入力の段階で停止。`-allowProvisioningUpdates`、API 認証オプション、Apple ID の操作は使っていない。
候補が未固定のため `BUILD_SOURCE_COMMIT=UNSET` を明示し、未追跡ソースに現在の HEAD を誤って来歴として埋め込まないようにした。
新規の使用可能な archive は生成されなかった。

### 既存 probe の明示的 export

既存 `/private/tmp/Playback.xcarchive` を名前で指定して使用した。自動的な「最新 archive」の選択ではない。
[plist の識別情報](evidence/prep-2026-10-18/previous-probe-archive-info.json) は Bundle ID / Team / version / build が指定値と一致。
ただし `UIDeviceFamily = [1,2]` で、来歴キーに HEAD が入っていても現在の未追跡ソースとの対応は証明できない。
[ファイル別 SHA-256・サイズ](evidence/prep-2026-10-18/previous-probe-archive-sha256.json) を記録した。配布・提出候補としては使用しない。

[export-options-probe.plist](export-options-probe.plist) は `method=app-store-connect`、`destination=export`、指定 Team、Automatic signing。
バージョン自動変更を無効にし、ローカル export だけを指定した。

```sh
cd /Users/satoki252595/orca/nhkRadio/ios
/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild -exportArchive -archivePath /private/tmp/Playback.xcarchive -exportOptionsPlist /Users/satoki252595/orca/nhkRadio/docs/release/export-options-probe.plist -exportPath /Users/satoki252595/orca/nhkRadio/ios/build/codex-prep-2026-10-18/export-probe
```
終了コード: **70**。 [実行記録](evidence/prep-2026-10-18/export-probe-command.json) / [出力原文](evidence/prep-2026-10-18/export-probe.log)。

```text
error: exportArchive Failed to load profile.
  Profile is missing the required UUID property.

** EXPORT FAILED **
```

今回観測したのは **Failed to load profile / Profile is missing the required UUID property**。
既存提出ドラフトにある **No Accounts** は今回のログでは再現・確認できていない。今回のエラーを No Accounts に置き換えない。
この隔離環境でのプロファイル読み取り失敗であり、実体の破損・アカウント状態は断定しない。
プロファイルを削除・再生成せず、この段階で停止した。IPA / DistributionSummary は今回生成されていない。

ASC キーは [存在確認のみ](evidence/prep-2026-10-18/asc-key-existence-only.json) 実施。
`~/.appstoreconnect/private_keys/AuthKey_4485SH762T.p8` の存在を確認し、内容は一切読まず、署名・API 呼び出しにも使っていない。

## 7. 残ブロッカーと次の作業

| ブロッカー | 必要な対応 / 今回の根拠 |
|---|---|
| 実行環境 | CoreSimulator 接続、Swift macro sandbox、Xcode のプロファイルアクセスが可能な環境で同じ検証を再実行。権限制限の無効化は今回行わない |
| Notion 登録 | ユーザーが Public connection を登録し、既知 Redirect URI・Read content を設定。Client ID を確定。Secret は安全なローカル手段で Worker secret に設定し、Git / 報告書には保存しない。実 DB / OAuth 接続はその後に検証 |
| Xcode サインイン・署名 | ユーザーが Xcode のアカウント・対象 Team を確認し、開発 / 配布プロファイルを整備。元資料では No Accounts とあるが、今回はプロファイル関連エラーまでを観測 |
| ASC レコード作成 | ユーザー作業。Bundle ID `dev.satoki.playback`、ASC アプリID / SKU / Issuer ID 等を確定。今回は ASC 未操作 |
| iPhone / iPad 設定 | iPhone 専用の設計に対して pbxproj が `1,2`。生成設定と生成物を整合し、再ビルド・再撮影する |
| 説明文の整合 | 提出ドラフト・OnboardingView の「トークン / 認証情報を開発者サーバーには送信しない」は OAuth refresh の実装と整合確認が必要。`AuthService.refreshOAuthToken()` は refresh token を Worker に送り、Worker はトークン応答を中継する。保存しないことと、中継しないことを混同しない。今回文言は変更していない |
| commit / push | ユーザーの明示指示待ち。アプリ一式が未追跡。今回 commit / push / tag は一切実行していない。候補固定後 source → archive / export → binary preflight をやり直す |
| スクリーンショット | 新規 4画面を指定シミュレータ・ネイティブ解像度で撮影し、実際の寸法 / サイズ / 内容を確認。今回 0枚 |
| TestFlight・実機審査動画 | 今回アップロード禁止のため未実施。後日明示された範囲で検証済み IPA をアップロードし、処理済みの同一 TestFlight build を実機で確認・動画撮影。開発 build や Simulator は代替証拠にしない |
| 提出 | 確定メタデータ、プライバシー回答、地域・DSA、同一 build の動画・審査メモと complete preflight が必要。今回提出・アップロードは一切していない |

月 1,000円以上のコストが発生する操作、新規有料リソース作成、デプロイ、パスワード / 2FA 入力、Apple / Notion へのサインイン代行は行っていない。

## 8. 作成物・証跡の扱い

- `docs/release/release-manifest.md`: 未確定を残した manifest。
- `docs/release/codex-prep-report.md`: 本書。
- `docs/release/source-preflight.draft.json`: 未確定値を含む、使用不可の source 設定ドラフト。
- `docs/release/export-options-probe.plist`: ローカル export 診断用設定。
- `docs/release/evidence/prep-2026-10-18/`: コマンド argv / cwd / 終了コード、原文ログ、設定・端末登録・入力ハッシュなど。
- `ios/store-screenshots/README.md`: PNG 未取得の記録と保存予定名。
- `ios/build/codex-prep-2026-10-18/`: 今回の中間生成物・失敗した結果 bundle（既存 `.gitignore` の対象）。

証跡一式のファイルサイズと SHA-256 は [evidence-sha256.json](evidence/prep-2026-10-18/evidence-sha256.json) に記録する。
これは作業ファイルの整合性確認用であり、成功した binary / complete preflight の指紋ではない。
原文ログにある既存コード署名証明書の表示名は公開鍵側の識別情報であり、秘密鍵は取得していない。
