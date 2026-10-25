# Playback for Notion: 500円買い切りへの変更

更新: 2026-10-25。追跡: [公開 #14](https://github.com/satoki252595/nhkRadio/issues/14)、[収益化 #15](https://github.com/satoki252595/nhkRadio/issues/15)。ユーザーは「買い切り500円に設定」「Opusによるメリット訴求動画の改善」「課金前提のApp Store申請」を明示依頼した。

## 決定した販売仕様

- 日本向け有料ダウンロード500円。利用開始時にApp Storeで一度支払い、ビルド8の機能を利用する。
- アプリ内課金・サブスクリプション・Pro制限は追加しない。500円で将来のAI等まで提供する約束はしない。
- 日本のみの配信を維持。Notionアカウント/対象DBへのアクセス許可が必要。Notion自体の利用料・容量上限は別であり、音源は付属しない。
- バイナリ変更は不要。元commit `7c90e6e2275c0b8b95d25129df12b7e36c8547cd`、1.0.0 (8)、既存TestFlight/実機/審査用技術動画の同定を維持する。文書commitをバイナリの元commitへ差し替えない。

## 確認済み

- 旧提出 `947c63bb-da78-48ce-ac84-6119f93bad5f` は作業開始時に審査待ち。旧設定は無料だった。
- 日本の500円価格点をAPIから取得し、価格スケジュールを設定。別のGETで日本/JPY・500円・開始日/終了日指定なしを確認。
- 現在の配信選択は175地域のうち日本1地域。APIの日本のcontentStatusesには `CANNOT_SELL` と `AVAILABLE_FOR_SALE_UNRELEASED_APP` があり、価格設定だけで有料販売可能とは判断しない。
- 審査メモの「無料」を「日本向け500円の有料ダウンロード（買い切り）、IAP/サブスクなし」へ修正し、独立GETで全文一致を確認。1481文字/UTF-16単位。UI上の文字数確認は未了。
- アプリのバイナリ・ソースは変更していない。
- 有料表記へ変更した審査メモと最新の地域証跡でcomplete検査68/68 PASS。新complete指紋 `908fe8b4256a1375be3d2dc4ca41b022912dbc2be0b77f2f75c367fc55785baf`。これは契約・新App Preview掲載・再提出の完了を証明するものではない。

## 動画制作

Opus 5.5へ新たに依頼済み。前作の操作説明を減らし、既存Notion DBの音声/動画を連続再生・保存してオフライン再生できるメリットを伝える。既存ビルド8の実機素材を再利用し、旧ファイルは上書きしない。

[Apple App Previews](https://developer.apple.com/app-store/app-previews/)では、掲載動画はアプリ内の映像を使用する。App Store用は実画面を背景にした短い訴求コピーで構成し、実画面の少ない自由な構成は別の紹介用動画として作る。未実装の時刻メモ・AI・自動保存・全形式対応を宣伝しない。

成果の動画・編集可能な台本/EDL・QA・ハッシュはGit外へ保存する。公開用素材の収録元は同じビルド8。App Review添付の技術検証動画と、一般向けApp Previewを混同しない。

## 残る公開条件

1. Paid Apps Agreement、税務・銀行情報、有料販売可能状態を確認する。必要な本人の法的同意・支払先情報は本人が入力する。
2. 新動画の独立した視覚QAと技術検査。App Storeの差し替えと処理完了確認。
3. 新しい審査メモを束縛するcomplete検査は68/68 PASS。実画面で価格・メモ・掲載物・文字数を確認する。
4. 差し替えに旧審査の取り下げが必要な場合は、素材が完成してから対象と影響を提示する。取り下げ/再提出はその時点の確認と実際のアイテム状態に従う。
5. 最終的な提出ID・日時・項目数・全項目の状態を確認して記録する。

有料価格の設定は確認済みだが、有料公開・新動画掲載・再提出の完了を示す記録ではない。

## 証跡

Git外: `~/.config/playback/release/paid-launch-2026-10-25/`。価格変更前後のAPI応答、500円の価格点、審査メモの要求/応答/独立照合、地域一覧、Opusへの依頼文を保存。秘密鍵・銀行/税務の個人情報はGitへ保存しない。

旧バイナリのbinary指紋は `d707b6dd14bedb75c26c53ab6b60f0a1b4a97d039f178ed6e2576dbfabdb05f9`。旧complete指紋を新メモの検査結果として流用しない。

参照: [Appleの価格設定](https://developer.apple.com/help/app-store-connect/manage-app-pricing/set-a-price/)、[審査ガイドライン2.3.4](https://developer.apple.com/app-store/review/guidelines/#accurate-metadata)。一次資料確認日: 2026-10-25。
