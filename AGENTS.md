# 開発環境

環境構築・依存管理はプロジェクトの `flake.nix` と `nix develop` を使う。グローバル/ユーザーランドへの直接インストールは行わない。Nixが使えない、または既存方針と衝突する場合はユーザーに確認する。

macOSではNixの開発シェルから、選択済みXcodeのAppleツールを絶対パスで実行する。Node/Python/FFmpegはNixで提供する。

# プロジェクト管理

全プロジェクトを専用GitHubリポジトリで、企画・調査と出典・要件・デザイン・販売・運用・検証・判断まで管理する。作業はIssues、変更経緯はコミットと必要に応じPRへ記録する。新規は既存repoを確認し、なければprivateで作成する。既存repoの重複作成や一括移行はしない。外部ツールの成果は編集可能な書き出しか参照URL・更新日・決定内容を残す。秘密情報と顧客個人情報はGitへ保存しない。

ローカルはサービスごとの独立フォルダとし、新規の標準配置は `/Users/satoki252595/projects/<service-slug>/`。Office配下に別サービスを作らない。既存専用フォルダを再利用し、ルール追加を理由に一括移動・改名しない。作業分離にはworktreeを使える。コードを作らない案件にはコード雛形を作らない。

本repoは既存のnhkRadioと、ユーザー合意済みのPlayback for Notion（`ios/`・`worker/`・`docs/`）を管理する。既存の配置合意は `docs/playback-for-notion.md` を参照し、今回の公開作業で移動・repo重複作成はしない。

# Playbackの公開

`release-ios-app-store`スキルの証跡付き手順を使う。候補commitをpushしてから、そのcommitを `BUILD_SOURCE_COMMIT` としてarchiveする。source / binary / complete preflightのゲートを飛ばさない。公開候補固定後の証跡はGit外へ保存し、バイナリの元commitを差し替えない。審査提出の直前には最終確認を取る。

OAuthのClient IDは公開値、Client Secret・ユーザートークン・Apple秘密鍵はGit外のみ。Notion接続は各ユーザーが自分のワークスペースを認可して使い、開発者は共通のOAuth接続を管理する。

ユーザー指定の `RTK.md` は現在repo・祖先・確認済みスキルルートに存在しない。提供された場合は着手前に読む。
