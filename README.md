# NHK Radio Recorder

NHKラジオの番組表を取得し、キーワード(例: 落語/英語)にマッチする番組を自動録音してNotionデータベースにアップロードするツール。

## 機能

- NHK番組表API (v3) から全番組を取得
- **シリーズ購読方式**: 気になる番組を購読 → 毎週自動録音 (またはキーワード方式も可)
- ffmpegでHLS→M4A録音
- Notionデータベースに音声ファイル+メタ情報を自動アップロード
- Notionモバイルアプリから再生可能
- GitHub Actions + GitHub Pages で無料運用
- **モダンなWebUI (SvelteKit)** で番組選択・購読管理

## 必要なもの

- Python 3.10+
- ffmpeg
- NHK APIキー (https://api-portal.nhk.or.jp/ で無料取得)
- Notion Integrationトークン (https://www.notion.so/profile/integrations で作成)

## ローカルセットアップ

```bash
# 1. 依存インストール
pip install -e ".[dev]"

# 2. 認証情報を設定
cp .env.example .env
# .env を編集して NHK_API_KEY / NOTION_TOKEN / NOTION_DATABASE_ID を記入

# 3. Notionデータベースに Integration を接続
# Notionでデータベースを開く → 右上「…」→「接続」→ あなたのIntegrationを選択

# 4. 動作確認 (録音せず対象番組だけ表示)
python -m nhk_recorder --dry-run

# 5. 録音実行 (開始時刻までTimerで待機)
python -m nhk_recorder
```

## 設定

`.env`:
```bash
NHK_API_KEY=your_nhk_api_key
NOTION_TOKEN=ntn_your_notion_token
NOTION_DATABASE_ID=6dc536e3d4404708a92ef5554353fa0d
```

エリアコード・キーワード等の変更は `config.yaml` を作成:
```yaml
area: "270"           # 大阪 (130=東京, 230=名古屋 等)
services: [r1, r3]    # r1=AM, r3=FM
keywords: ["落語", "らくご", "英語"]
```

## GitHub Actions での自動実行 (推奨)

ローカルPCを動かし続けたくない場合の設定手順:

1. **リポジトリをGitHubにpush** (publicなら実行時間無制限)

2. **Secretsを登録**: Settings → Secrets and variables → Actions → New repository secret
   - `NHK_API_KEY`
   - `NOTION_TOKEN`
   - `NOTION_DATABASE_ID`

3. **動作確認**: Actionsタブ → "NHK Radio Recorder" → "Run workflow" で手動実行

これで毎時0分(UTC 0-14 = JST 9-23)に自動起動し、直近65分以内に開始する対象番組を録音します。

録音対象は `data/subscriptions.json`（シリーズ購読方式）をデフォルトで参照します。
WebUI の「☁ GitHubへプッシュ」で更新するか、キーワード方式に切り替えたい場合は
手動実行の `mode` を `keywords` に変更してください。

## コマンド

| コマンド | 説明 |
|---|---|
| `python -m nhk_recorder --dry-run` | 対象番組の確認のみ |
| `python -m nhk_recorder` | Timer待機モード(ローカル用) |
| `python -m nhk_recorder --within 65` | 直近65分以内の番組を即時録音(GitHub Actions用) |
| `python -m nhk_recorder --subscriptions data/subscriptions.json` | 購読ベースで録音 (ローカルパス) |
| `python -m nhk_recorder --subscriptions https://.../subscriptions.json` | 購読ベースで録音 (URL 経由、SaaS 移行時用) |
| `python -m nhk_recorder --date 2026-04-10` | 指定日の番組を対象にする |
| `python -m nhk_recorder.data_export` | 番組データJSONを生成 (Web UI用) |

## プロジェクト構成

```
001_radio/
├── .env                      # 認証情報 (gitignore)
├── .env.example
├── config.yaml.example
├── .github/workflows/
│   ├── record.yml            # 録音ワークフロー (毎時実行)
│   ├── data-update.yml       # 番組データ更新 (毎日早朝)
│   └── deploy-pages.yml      # GitHub Pagesデプロイ
├── data/                     # 番組データ (GitHub Actionsが生成)
│   ├── series.json
│   ├── programs-YYYY-MM-DD.json
│   └── subscriptions.json    # 購読中シリーズID (手動orWebUIから配置)
├── nhk_recorder/
│   ├── main.py               # エントリーポイント
│   ├── config.py             # 設定ローダ(.env + config.yaml)
│   ├── api.py                # NHK番組表API v3 クライアント
│   ├── matcher.py            # キーワード/シリーズマッチング
│   ├── streams.py            # ストリームURL取得
│   ├── recorder.py           # ffmpeg録音
│   ├── scheduler.py          # Timer待機スケジューラ
│   ├── notion.py             # Notionアップロード
│   └── data_export.py        # Web UI向けJSON生成
├── web/                      # SvelteKit フロントエンド (GitHub Pages)
│   ├── src/routes/           # ページ
│   └── src/lib/              # コンポーネント/ストア
├── recordings/               # 録音ファイル出力先 (gitignore)
└── tests/
```

## Webフロントエンド (GitHub Pages)

SvelteKitで構築されたモダンなWebUI。シリーズ購読・番組閲覧が可能。

### ローカル開発
```bash
cd web
npm install
npm run dev  # http://localhost:5173
```

### GitHub Pages デプロイ
`main`ブランチに`web/`や`data/`をpushすると自動デプロイされます。

1. GitHub リポジトリ → Settings → Pages → Source を「GitHub Actions」に設定
2. 初回デプロイ後、`https://{username}.github.io/{repo-name}/` でアクセス可能

### 購読フロー

#### 推奨: WebUI から GitHub に直接同期
1. GitHub で **Fine-grained Personal Access Token** を発行
   - Settings → Developer settings → Personal access tokens → Fine-grained tokens
   - Repository access: このリポジトリを選択
   - Permissions: **Contents: Read and write**
2. Webサイトの「購読中」ページ → 「⚙ 同期設定」→ PAT / owner / repo を入力して保存
   (ブラウザの localStorage にのみ保存されます)
3. 気になる番組を「購読」
4. 「☁ GitHubへプッシュ」をクリック → `data/subscriptions.json` が自動コミットされる
5. 次回の GitHub Actions 実行時から、購読した番組が自動録音される

別のブラウザ/端末で購読を引き継ぐ場合は「⬇ GitHubから取得」でリモートの購読リストを読み込めます。

#### 従来: JSON を手動配置
1. Webサイトで番組を検索 → 「購読」ボタンをクリック (localStorageに保存)
2. 「購読中」ページで「JSONダウンロード」
3. ダウンロードした `subscriptions.json` を `data/subscriptions.json` として配置してコミット
4. 次回の GitHub Actions 実行時から、購読した番組が自動録音される

## テスト

```bash
python -m pytest tests/ -v
```

## 注意事項

- NHKラジオ第2 (r2) は2026年3月30日廃止。現在は r1(AM) と r3(FM) のみ
- NHK APIは1日300リクエスト制限
- 録音した音声は個人利用の範囲内でお使いください
- Notionファイルアップロードは有料プランで5GBまで

## SaaS 化への移行計画

将来のマルチユーザー化・SaaS 化については [`docs/saas-migration.md`](docs/saas-migration.md) を参照。
