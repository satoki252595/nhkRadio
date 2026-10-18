# Playback for Notion — 公開準備再検証報告 v2

実行日: 2026-10-18（JST）。作業ルート: `/Users/satoki252595/orca/nhkRadio`。
証跡ディレクトリ名の `prep-v2-2026-10-19` は今回の実行識別子で、実行日は上記の通り。
[前回報告](codex-prep-report.md) と [提出ドラフト](../app-store-submission.md) を読んでから実施した。

## 結果

| 項目 | 実績 |
|---|---|
| xcodebuild test | **成功、14件実行 / 14件合格 / 失敗0件 / スキップ0件**、exit 0 |
| 対象 | PlaybackTests、iPhone 17 Pro Max、iOS 26.5、arm64 |
| destination | `platform=iOS Simulator,id=14C56DCC-7626-455B-ACB4-5169C62F27DB` |
| デバイス設定 | 既存・テスト後のアプリとも **UIDeviceFamily=[1]**。Playback の Release 実効値も **TARGETED_DEVICE_FAMILY=1** |
| スクリーンショット | **4/4枚あり、全て1320×2868 px** |
| 後片付け | 最終 `orca emulator kill --json` 成功（exit 0 / ok=true）。デバイスは停止していない |
| 保全 | iOSソース・テスト・Xcodeプロジェクト・project.yml・Workerソース/設定など39ファイルの開始/終了SHA-256一致（diff exit 0） |

テストは前回の宣言件数の転記ではなく、今回の実行ログと
[xcresult 集計](evidence/prep-v2-2026-10-19/test-summary.log) を照合した。
`totalTestCount=14`、`passedTests=14`、`failedTests=0`、`skippedTests=0`、
`result=Passed`。スイート別は FormatHelpers 3、LibraryItemParsing 1、
MappingSuggestion 2、NotionID 4、PropertyFormatting 4。
[テスト原文ログ](evidence/prep-v2-2026-10-19/unit-tests.log) の末尾:

```text
Test Suite 'All tests' passed at 2026-10-18 23:39:01.192.
	 Executed 14 tests, with 0 failures (0 unexpected) in 0.011 (0.015) seconds
** TEST SUCCEEDED **
```

前回の `swift-plugin-server` の malformed response と CoreSimulator 接続拒否は
今回のテスト・インストール・起動・撮影を阻害しなかった。
ただし、後述する非致命的な起動時診断があり、無警告とは報告しない。

既存の `ios/build/Build/Products/Debug-iphonesimulator/Playback.app` が開始時から存在した。
今回は `xcodebuild test -derivedDataPath build` が同じアプリを再ビルドし、
その出力を指定デバイスへインストールした。追加の独立した `build` コマンドは不要だった。
Release の設定照合は Bundle ID `dev.satoki.playback`、version/build `1.0.0 / 1`。
生成や設定変更は行っていない。

## スクリーンショットと画面確認

| 画面 | ファイル | 有無 | 寸法 | サイズ |
|---|---|---|---|---:|
| ライブラリ | [01-library.png](../../ios/store-screenshots/6.9/01-library.png) | あり | 1320×2868 | 895,019 bytes |
| 詳細 | [02-detail.png](../../ios/store-screenshots/6.9/02-detail.png) | あり | 1320×2868 | 431,454 bytes |
| 再生中 | [03-nowplaying.png](../../ios/store-screenshots/6.9/03-nowplaying.png) | あり | 1320×2868 | 877,229 bytes |
| ダウンロード | [04-downloads.png](../../ios/store-screenshots/6.9/04-downloads.png) | あり | 1320×2868 | 216,447 bytes |

全4枚を画像として開き、内容を確認した。寸法は
[sips 最終実測](evidence/prep-v2-2026-10-19/screenshot-dimensions-final.log)、
バイト数・SHA-256は [最終メタデータ](evidence/prep-v2-2026-10-19/artifact-metadata-final.log) を参照。
未取得の要求画面はない。接続・マッピングは今回対象外。

各遷移の前後で `orca emulator ax --json` を取得した。
アニメーション中に要素が一時消えたり、旧画面の要素が残った場合は再取得してから操作した。
全タップは取得済みAXのframe中心を使用し、唯一の例外はユーザー指定の
ダウンロードタブ目安 `(0.39, 0.962)` の試行。

| 操作 | 根拠frame (x,y,width,height) | 使用した中心 | 遷移後の確認 |
|---|---|---|---|
| デモ開始 | (0.1667,0.8539,0.6716,0.0188) | (0.5025,0.8633) | ライブラリ5行、サンプル: ラジオ録音 |
| 先頭行 | (0,0.2887,1,0.09) | (0.5,0.3337) | 朝の朗読: 宮沢賢治セレクション、メディアファイル、プロパティ |
| 詳細の再生 | (0.2689,0.3546,0.3,0.061) | (0.4189,0.3851) | 一時停止とミニプレイヤーが出現 |
| ミニプレイヤーのタイトル | (0.1727,0.9146,0.4659,0.0188) | (0.40565,0.924) | 閉じる、キュー、速度、スリープ、再生スライダ |
| Now Playingを閉じる | (0.0545,0.09,0.1636,0.0377) | (0.1363,0.10885) | 詳細へ復帰 |
| 詳細メディア行のダウンロード | (0.8561,0.515,0.053,0.0237) | (0.8826,0.52685) | ダウンロード済み |
| 戻る | (0.0455,0.0649,0.1,0.046) | (0.0955,0.0879) | ライブラリへ復帰 |
| ダウンロードタブ | (0.2731,0.9174,0.2375,0.0565) | (0.39185,0.94565) | 再起動前はNow Playing、再起動後はダウンロード選択値1 |
| 最後のライブラリ確認 | (0.0568,0.9174,0.2375,0.0565) | (0.17555,0.94565) | ライブラリ選択値1、5行 |

ライブラリと詳細を撮影後、再生を開始し、先頭項目の Now Playing を撮影した。
デモ音声は短いため、その後の操作中に連続再生が次の項目へ進んだ。
ダウンロード対象は詳細に表示中の先頭項目のままで、保存済み1件、
`demo-speech-1.m4a`、使用容量208 KBを確認した。

**予定導線での失敗と回復**:
再生開始後、ミニプレイヤーとタブが同じ画面下部に重なり、
AX のダウンロードタブ中心を押しても Now Playing が開いた。
閉じた後、指定目安 `(0.39,0.962)` でも Now Playing が開いた。
これらはCLI exit 0でも、期待したタブ遷移には失敗している。
画面を閉じて `xcrun simctl terminate` → `launch` でアプリだけ再起動し、
デモモードとダウンロードが維持され、ミニプレイヤーが消えたことをAXで確認した。
その後、同じAXタブ中心でダウンロード画面へ遷移して撮影できた。
保存データの削除・再インストール・ソース変更による回避はしていない。

**画像確認上の留意点**:
ライブラリの大見出し「サンプル: ラジオ録音」はAXに存在するが、PNG上では見えない。
終了前に同画面を再撮影しても同様だったため、最終PNGを実表示のまま保存した。
この最終画像には撮影操作で付いた保存済み・再生済み表示がある。
詳細はスクロール上部の1枚であり、下方の全プロパティを1枚に収めた合成画像ではない。
タブ重なりと見出し表示を含め、4枚取得を最終掲載品質の承認とは扱わない。

## エラー・診断原文

テスト・設定照合・端末起動・UI操作・撮影・入力保全の各コマンドは全て exit 0。テストassertion失敗、boot/install/launch/screenshotの
失敗はない。タブ遷移の失敗にはCLIのエラーメッセージはなく、AX結果で誤遷移を確認した
（[中央試行](evidence/prep-v2-2026-10-19/ax-11-tab-attempt.log)、
[下部試行](evidence/prep-v2-2026-10-19/ax-14-downloads.log)）。

テスト起動時はCoreDataの初回ストア作成診断の後、recovery成功が出た。
以下は原文抜粋。全文はunit-tests.logを保持しており、診断を削って成功に見せていない。

```text
CoreData: error:   Sandbox access to file-write-create denied
CoreData: error: addPersistentStoreWithType:configuration:URL:options:error: returned error NSCocoaErrorDomain (512)
CoreData: error: During recovery, parent directory path reported as missing
CoreData: error: Recovery attempt while adding <NSPersistentStoreDescription: 0x103c707b0> (type: SQLite, url: file:///Users/satoki252595/Library/Developer/CoreSimulator/Devices/14C56DCC-7626-455B-ACB4-5169C62F27DB/data/Containers/Data/Application/D7078EF6-BCE3-4CB2-A1F8-105D0E4EEE07/Library/Application%20Support/default.store) was successful!
2026-10-18 23:39:00.857131+0900 Playback[80343:16441134] [Default] BackgroundSession <10CF256B-B731-4DD1-A359-8D50D5236536> an error occurred on the xpc connection to setup the background session: Error Domain=NSCocoaErrorDomain Code=4097 "connection to service named com.apple.nsurlsessiond" UserInfo={NSDebugDescription=connection to service named com.apple.nsurlsessiond}
2026-10-18 23:39:01.209 xcodebuild[79877:16438589] [MT] IDESchemeActionSDKRecord: operatingSystemBuild = <DVTBuildVersion 24A94232>, error = invalidDigitCount(94232).
```

AppIntentsメタデータ抽出にも `warning: Metadata extraction skipped, no AppIntents.framework dependency found`
がある。これらは今回14件の不合格を意味せず、実DB/OAuth/ネットワークダウンロードの
成功を証明するものでもない。デモ保存の確認からネットワーク経由の保存成功は推定しない。

作業用ツール呼び出しの最初の関数読み込みに1回失敗した。検証コマンド実行前のJavaScript
スコープエラーで、修正後に各コマンドを実行した。アプリのエラーではない。

```text
Script error:
ReferenceError: run is not defined
    at exec_main.mjs:2:1
```

最終成果物チェックの初回は、ログ用パイプをheredoc終端へ付加した作業用コマンドの組み立てミスで
exit 1となった。アプリのテスト失敗ではない。初回はteeまで到達しなかったため、
[原文ログ](evidence/prep-v2-2026-10-19/final-verification.log) はツール返却出力をそのまま保存した。

```text
  File "<stdin>", line 21
    PY 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/final-verification.log'
       ^
SyntaxError: invalid syntax
```

コマンド全体を括弧で囲んでログパイプと分離した再実行はexit 0。
PNGシグネチャ・寸法・サイズ・SHA-256、14件のxcresult集計、39入力の一致、
文書リンクとその時点のコマンドログの存在をassertで確認した。
[検証結果](evidence/prep-v2-2026-10-19/final-verification-retry.log):

```text
PASS: 14 tests, 4 PNGs, 39 unchanged inputs, document links, command logs
```

報告ファイルの最初の一括パッチにも作業用エラーがあり、適用前に拒否された。
同一READMEへのDelete/Addを分けて保存し直した。アプリ・設定への変更はない。

```text
apply_patch verification failed: invalid patch: multiple operations target /Users/satoki252595/orca/nhkRadio/ios/store-screenshots/README.md
```


## 生成・更新ファイル

- 新規: `docs/release/codex-prep-report-v2.md`（本書）。
- 更新: `ios/store-screenshots/README.md`（4枚・寸法・制約を反映）。
- 新規: `ios/store-screenshots/6.9/01-library.png`。
- 新規: `ios/store-screenshots/6.9/02-detail.png`。
- 新規: `ios/store-screenshots/6.9/03-nowplaying.png`。
- 新規: `ios/store-screenshots/6.9/04-downloads.png`。
- 新規: `docs/release/evidence/prep-v2-2026-10-19/`（各コマンド原文ログ、AX、commands.json）。
- ビルド出力: `ios/build/codex-prep-v2-2026-10-19/PlaybackTests.xcresult`。
  既存 `ios/build/` 配下のアプリ・テスト・中間成果物もxcodebuildが更新した。

39ファイルの入力保全は [開始](evidence/prep-v2-2026-10-19/source-hashes-before.log)、
[終了](evidence/prep-v2-2026-10-19/source-hashes-after.log)、
[diff](evidence/prep-v2-2026-10-19/source-preservation.log) を参照。
既存の未追跡ソースを含むため、git diffの空表示だけを保全根拠にはしていない。

## 残ブロッカー

今回のテスト実行・4枚取得のブロッカーは解消した。
ただし**公開準備全体の完了・提出可能とは判定しない**。

- ミニプレイヤーがタブ操作を遮る問題と、ライブラリ大見出しの画像上の欠落を要確認。
  今回はソース変更禁止のため修正していない。
- 今回のPNGはDebug Simulator版。候補固定後、最終ビルドと掲載内容の整合確認が必要。
- 前回資料のNotion public connection / Client ID・Secret設定、実DB/OAuth接続確認は未実施。
- 前回資料のXcode署名・配布export、ASCアプリレコード/ID・SKU等の未確定事項は今回未再検証。
  過去の署名エラーが直ったとは判断しない。
- 認証情報の中継と説明文の整合、プライバシー等の最終メタデータ確認が残る。
- 未追跡ファイルの候補commit固定、source/binary preflight、処理済みTestFlightの実機検証、
  同一ビルドの審査動画、complete preflight・提出前確認は未実施。

パスワード/2FA入力、Apple ID/Notionサインイン、ASCへの提出/アップロード、
git commit/push/tag、秘密鍵内容の読取り・出力、デプロイ、有料リソース作成は行っていない。
依存インストールは不要で、既存Xcode/Orca/macOSツールと既存Nix-storeのPythonのみ使用した。
ユーザー指定のRTK.mdは今回のワークスペース・祖先確認範囲でも見つからなかった。

## 実行コマンド全文

以下は検証・撮影・保全の実行順（末尾に成果物チェックの失敗と成功した再実行も記載）。各項目は実行cwd、実際のコマンド（ログ保存用
`set -o pipefail` / `tee` を含む）、終了コードと原文ログを示す。
機械可読一覧は [commands.json](evidence/prep-v2-2026-10-19/commands.json)。
テストとbootstatus/attachは同一プロセスの終了を追跡してexit 0を確認した。

### 1. simulator-devices（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/simulator-devices.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl list devices available 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/simulator-devices.log'
```

### 2. device-family-before（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/device-family-before.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
/usr/libexec/PlistBuddy -c 'Print :UIDeviceFamily' ios/build/Build/Products/Debug-iphonesimulator/Playback.app/Info.plist 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/device-family-before.log'
```

### 3. source-hashes-before（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/source-hashes-before.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
(rg --files ios/Playback ios/PlaybackTests ios/Playback.xcodeproj worker/src; printf '%s\n' ios/project.yml worker/package.json worker/wrangler.jsonc) | sort | xargs shasum -a 256 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/source-hashes-before.log'
```

### 4. unit-tests（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/unit-tests.log)

```sh
cd /Users/satoki252595/orca/nhkRadio/ios
set -o pipefail
/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild -project Playback.xcodeproj -scheme Playback -configuration Debug -destination 'platform=iOS Simulator,id=14C56DCC-7626-455B-ACB4-5169C62F27DB' -derivedDataPath build -resultBundlePath /Users/satoki252595/orca/nhkRadio/ios/build/codex-prep-v2-2026-10-19/PlaybackTests.xcresult -only-testing:PlaybackTests CODE_SIGNING_ALLOWED=NO test 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/unit-tests.log'
```

### 5. test-summary（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/test-summary.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun xcresulttool get test-results summary --path ios/build/codex-prep-v2-2026-10-19/PlaybackTests.xcresult 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/test-summary.log'
```

### 6. device-family-after（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/device-family-after.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
/usr/libexec/PlistBuddy -c 'Print :UIDeviceFamily' ios/build/Build/Products/Debug-iphonesimulator/Playback.app/Info.plist 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/device-family-after.log'
```

### 7. device-state（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/device-state.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl list devices booted 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/device-state.log'
```

### 8. simulator-boot（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/simulator-boot.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl boot 14C56DCC-7626-455B-ACB4-5169C62F27DB 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/simulator-boot.log'
```

### 9. simulator-bootstatus（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/simulator-bootstatus.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl bootstatus 14C56DCC-7626-455B-ACB4-5169C62F27DB -b 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/simulator-bootstatus.log'
```

### 10. simulator-install（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/simulator-install.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl install 14C56DCC-7626-455B-ACB4-5169C62F27DB ios/build/Build/Products/Debug-iphonesimulator/Playback.app 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/simulator-install.log'
```

### 11. simulator-launch（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/simulator-launch.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl launch 14C56DCC-7626-455B-ACB4-5169C62F27DB dev.satoki.playback 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/simulator-launch.log'
```

### 12. emulator-attach（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/emulator-attach.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator attach 14C56DCC-7626-455B-ACB4-5169C62F27DB --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/emulator-attach.log'
```

### 13. ax-01-onboarding（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-01-onboarding.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-01-onboarding.log'
```

### 14. tap-demo（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-demo.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.5025 0.8633 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-demo.log'
```

### 15. ax-02-library（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-02-library.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-02-library.log'
```

### 16. screenshot-library（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/screenshot-library.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl io 14C56DCC-7626-455B-ACB4-5169C62F27DB screenshot ios/store-screenshots/6.9/01-library.png 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/screenshot-library.log'
```

### 17. tap-first-item（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-first-item.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.5 0.3337 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-first-item.log'
```

### 18. ax-03-detail（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-03-detail.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-03-detail.log'
```

### 19. ax-04-detail-settled（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-04-detail-settled.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-04-detail-settled.log'
```

### 20. screenshot-detail（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/screenshot-detail.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl io 14C56DCC-7626-455B-ACB4-5169C62F27DB screenshot ios/store-screenshots/6.9/02-detail.png 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/screenshot-detail.log'
```

### 21. tap-play（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-play.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.4189 0.3851 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-play.log'
```

### 22. ax-05-playing-detail（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-05-playing-detail.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-05-playing-detail.log'
```

### 23. tap-miniplayer-title（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-miniplayer-title.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.40565 0.924 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-miniplayer-title.log'
```

### 24. ax-06-nowplaying（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-06-nowplaying.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-06-nowplaying.log'
```

### 25. screenshot-nowplaying（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/screenshot-nowplaying.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl io 14C56DCC-7626-455B-ACB4-5169C62F27DB screenshot ios/store-screenshots/6.9/03-nowplaying.png 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/screenshot-nowplaying.log'
```

### 26. tap-close-nowplaying（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-close-nowplaying.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.1363 0.10885 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-close-nowplaying.log'
```

### 27. ax-07-detail-return（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-07-detail-return.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-07-detail-return.log'
```

### 28. ax-08-detail-return-settled（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-08-detail-return-settled.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-08-detail-return-settled.log'
```

### 29. tap-download（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-download.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.8826 0.52685 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-download.log'
```

### 30. ax-09-downloaded-detail（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-09-downloaded-detail.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-09-downloaded-detail.log'
```

### 31. tap-back（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-back.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.0955 0.0879 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-back.log'
```

### 32. ax-10-library-return（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-10-library-return.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-10-library-return.log'
```

### 33. tap-downloads-tab-center（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-downloads-tab-center.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.39185 0.94565 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-downloads-tab-center.log'
```

### 34. ax-11-tab-attempt（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-11-tab-attempt.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-11-tab-attempt.log'
```

### 35. tap-close-tab-conflict（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-close-tab-conflict.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.1363 0.10885 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-close-tab-conflict.log'
```

### 36. ax-12-library-close（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-12-library-close.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-12-library-close.log'
```

### 37. ax-13-library-before-downloads（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-13-library-before-downloads.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-13-library-before-downloads.log'
```

### 38. tap-downloads-tab-lower（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-downloads-tab-lower.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.39 0.962 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-downloads-tab-lower.log'
```

### 39. ax-14-downloads（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-14-downloads.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-14-downloads.log'
```

### 40. tap-close-lower-conflict（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-close-lower-conflict.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.1363 0.10885 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-close-lower-conflict.log'
```

### 41. ax-15-before-relaunch（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-15-before-relaunch.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-15-before-relaunch.log'
```

### 42. simulator-terminate-for-tab（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/simulator-terminate-for-tab.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl terminate 14C56DCC-7626-455B-ACB4-5169C62F27DB dev.satoki.playback 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/simulator-terminate-for-tab.log'
```

### 43. simulator-relaunch-for-tab（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/simulator-relaunch-for-tab.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl launch 14C56DCC-7626-455B-ACB4-5169C62F27DB dev.satoki.playback 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/simulator-relaunch-for-tab.log'
```

### 44. ax-16-relaunched-library（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-16-relaunched-library.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-16-relaunched-library.log'
```

### 45. ax-17-relaunched-library-settled（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-17-relaunched-library-settled.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-17-relaunched-library-settled.log'
```

### 46. tap-downloads-tab-after-relaunch（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-downloads-tab-after-relaunch.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.39185 0.94565 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-downloads-tab-after-relaunch.log'
```

### 47. ax-18-downloads-after-relaunch（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-18-downloads-after-relaunch.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-18-downloads-after-relaunch.log'
```

### 48. screenshot-downloads（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/screenshot-downloads.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl io 14C56DCC-7626-455B-ACB4-5169C62F27DB screenshot ios/store-screenshots/6.9/04-downloads.png 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/screenshot-downloads.log'
```

### 49. screenshot-dimensions（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/screenshot-dimensions.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
sips -g pixelWidth -g pixelHeight ios/store-screenshots/6.9/01-library.png ios/store-screenshots/6.9/02-detail.png ios/store-screenshots/6.9/03-nowplaying.png ios/store-screenshots/6.9/04-downloads.png 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/screenshot-dimensions.log'
```

### 50. emulator-kill（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/emulator-kill.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator kill --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/emulator-kill.log'
```

### 51. source-hashes-after（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/source-hashes-after.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
(rg --files ios/Playback ios/PlaybackTests ios/Playback.xcodeproj worker/src; printf '%s\n' ios/project.yml worker/package.json worker/wrangler.jsonc) | sort | xargs shasum -a 256 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/source-hashes-after.log'
```

### 52. source-preservation（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/source-preservation.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
diff -u docs/release/evidence/prep-v2-2026-10-19/source-hashes-before.log docs/release/evidence/prep-v2-2026-10-19/source-hashes-after.log 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/source-preservation.log'
```

### 53. artifact-metadata（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/artifact-metadata.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
stat -f '%N %z bytes' ios/store-screenshots/6.9/01-library.png ios/store-screenshots/6.9/02-detail.png ios/store-screenshots/6.9/03-nowplaying.png ios/store-screenshots/6.9/04-downloads.png && shasum -a 256 ios/store-screenshots/6.9/01-library.png ios/store-screenshots/6.9/02-detail.png ios/store-screenshots/6.9/03-nowplaying.png ios/store-screenshots/6.9/04-downloads.png 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/artifact-metadata.log'
```

### 54. app-release-settings（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/app-release-settings.log)

```sh
cd /Users/satoki252595/orca/nhkRadio/ios
set -o pipefail
/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild -project Playback.xcodeproj -target Playback -configuration Release -showBuildSettings -json | /nix/store/ls1816af8myfcsa4gk7626nsx6sb5yn0-python3-3.12.14-env/bin/python3 -c 'import json,sys; data=json.load(sys.stdin); print(json.dumps([{ "target":v["target"], "settings":{k:v["buildSettings"].get(k) for k in ["PRODUCT_BUNDLE_IDENTIFIER", "MARKETING_VERSION", "CURRENT_PROJECT_VERSION", "TARGETED_DEVICE_FAMILY"]}} for v in data],ensure_ascii=False,indent=2))' 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/app-release-settings.log'
```

### 55. emulator-attach-qa（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/emulator-attach-qa.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator attach 14C56DCC-7626-455B-ACB4-5169C62F27DB --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/emulator-attach-qa.log'
```

### 56. ax-19-downloads-before-library-qa（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-19-downloads-before-library-qa.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-19-downloads-before-library-qa.log'
```

### 57. tap-library-qa（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/tap-library-qa.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator tap 0.17555 0.94565 --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/tap-library-qa.log'
```

### 58. ax-20-library-qa（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/ax-20-library-qa.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator ax --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/ax-20-library-qa.log'
```

### 59. screenshot-library-qa（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/screenshot-library-qa.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
xcrun simctl io 14C56DCC-7626-455B-ACB4-5169C62F27DB screenshot ios/store-screenshots/6.9/01-library.png 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/screenshot-library-qa.log'
```

### 60. emulator-kill-final（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/emulator-kill-final.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
orca emulator kill --json 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/emulator-kill-final.log'
```

### 61. screenshot-dimensions-final（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/screenshot-dimensions-final.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
sips -g pixelWidth -g pixelHeight ios/store-screenshots/6.9/01-library.png ios/store-screenshots/6.9/02-detail.png ios/store-screenshots/6.9/03-nowplaying.png ios/store-screenshots/6.9/04-downloads.png 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/screenshot-dimensions-final.log'
```

### 62. artifact-metadata-final（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/artifact-metadata-final.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
(stat -f '%N %z bytes' ios/store-screenshots/6.9/01-library.png ios/store-screenshots/6.9/02-detail.png ios/store-screenshots/6.9/03-nowplaying.png ios/store-screenshots/6.9/04-downloads.png && shasum -a 256 ios/store-screenshots/6.9/01-library.png ios/store-screenshots/6.9/02-detail.png ios/store-screenshots/6.9/03-nowplaying.png ios/store-screenshots/6.9/04-downloads.png) 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/artifact-metadata-final.log'
```

### 63. final-verification（exit 1）

[原文ログ](evidence/prep-v2-2026-10-19/final-verification.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
/nix/store/ls1816af8myfcsa4gk7626nsx6sb5yn0-python3-3.12.14-env/bin/python3 - <<'PY'
import hashlib, json, re, struct
from pathlib import Path
root = Path('/Users/satoki252595/orca/nhkRadio')
expected = {'01-library.png': (895019, '775d2d6f8c1192d9f3a1c9249cb9515964004219d6f2b875dda9bf00b3f29d46'), '02-detail.png': (431454, 'd1131909da30d0ab1b294358f72b2da936ee4ba080f5592de07202ecb339f24e'), '03-nowplaying.png': (877229, '525aad818c79f59965c2333b9614cf121c5ae15d3954d954ae4795eb04126765'), '04-downloads.png': (216447, '0eaadac500ead159c3f5d84fa1ba323365b7757d8fc9a38281534b06bba83214')}
for name, (size, sha) in expected.items():
    data = (root / 'ios/store-screenshots/6.9' / name).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', data[16:24]) == (1320, 2868)
    assert len(data) == size and hashlib.sha256(data).hexdigest() == sha
    print(name, 'OK: 1320x2868, bytes, SHA-256')
ev = root / 'docs/release/evidence/prep-v2-2026-10-19'
summary = json.loads((ev / 'test-summary.log').read_text())
assert (summary['totalTestCount'], summary['passedTests'], summary['failedTests'], summary['skippedTests'], summary['result']) == (14, 14, 0, 0, 'Passed')
assert (ev / 'source-hashes-before.log').read_bytes() == (ev / 'source-hashes-after.log').read_bytes()
for doc in [root / 'docs/release/codex-prep-report-v2.md', root / 'ios/store-screenshots/README.md']:
    for link in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
        assert (doc.parent / link).exists(), (str(doc), link)
commands = json.loads((ev / 'commands.json').read_text())
assert all(c['exit_code'] == 0 and Path(c['log']).exists() for c in commands)
print('PASS: 14 tests, 4 PNGs, 39 unchanged inputs, document links, command logs')
PY 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/final-verification.log'
```

### 64. final-verification-retry（exit 0）

[原文ログ](evidence/prep-v2-2026-10-19/final-verification-retry.log)

```sh
cd /Users/satoki252595/orca/nhkRadio
set -o pipefail
(
/nix/store/ls1816af8myfcsa4gk7626nsx6sb5yn0-python3-3.12.14-env/bin/python3 - <<'PY'
import hashlib, json, re, struct
from pathlib import Path
root = Path('/Users/satoki252595/orca/nhkRadio')
expected = {'01-library.png': (895019, '775d2d6f8c1192d9f3a1c9249cb9515964004219d6f2b875dda9bf00b3f29d46'), '02-detail.png': (431454, 'd1131909da30d0ab1b294358f72b2da936ee4ba080f5592de07202ecb339f24e'), '03-nowplaying.png': (877229, '525aad818c79f59965c2333b9614cf121c5ae15d3954d954ae4795eb04126765'), '04-downloads.png': (216447, '0eaadac500ead159c3f5d84fa1ba323365b7757d8fc9a38281534b06bba83214')}
for name, (size, sha) in expected.items():
    data = (root / 'ios/store-screenshots/6.9' / name).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', data[16:24]) == (1320, 2868)
    assert len(data) == size and hashlib.sha256(data).hexdigest() == sha
    print(name, 'OK: 1320x2868, bytes, SHA-256')
ev = root / 'docs/release/evidence/prep-v2-2026-10-19'
summary = json.loads((ev / 'test-summary.log').read_text())
assert (summary['totalTestCount'], summary['passedTests'], summary['failedTests'], summary['skippedTests'], summary['result']) == (14, 14, 0, 0, 'Passed')
assert (ev / 'source-hashes-before.log').read_bytes() == (ev / 'source-hashes-after.log').read_bytes()
for doc in [root / 'docs/release/codex-prep-report-v2.md', root / 'ios/store-screenshots/README.md']:
    for link in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
        assert (doc.parent / link).exists(), (str(doc), link)
commands = json.loads((ev / 'commands.json').read_text())
assert all(c['exit_code'] == 0 and Path(c['log']).exists() for c in commands)
print('PASS: 14 tests, 4 PNGs, 39 unchanged inputs, document links, command logs')
PY
) 2>&1 | tee '/Users/satoki252595/orca/nhkRadio/docs/release/evidence/prep-v2-2026-10-19/final-verification-retry.log'
```
