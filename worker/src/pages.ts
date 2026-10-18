const baseStyle = `
  body { font-family: -apple-system, "Hiragino Sans", sans-serif; line-height: 1.7;
         color: #1c1c1e; max-width: 720px; margin: 0 auto; padding: 24px 20px 64px; }
  h1 { font-size: 1.5rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
  .note { color: #555; font-size: .9rem; } hr { border: none; border-top: 1px solid #ddd; margin: 3rem 0; }
`;

function page(title: string, body: string): string {
  return `<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title} — Playback for Notion</title><style>${baseStyle}</style></head>
<body>${body}</body></html>`;
}

const disclaimer = `
<p class="note">Playback for Notion は独立したサードパーティアプリであり、Notion Labs, Inc. とは提携していません。
"Notion" は Notion Labs, Inc. の商標です。<br>
Playback for Notion is an independent third-party app and is not affiliated with Notion Labs, Inc.</p>`;

export const privacyHTML = page(
  "プライバシーポリシー / Privacy Policy",
  `
<h1>プライバシーポリシー</h1>
<p>「Playback for Notion」（以下「本アプリ」）における情報の取り扱いを説明します。</p>

<h2>収集する情報</h2>
<p>本アプリは、利用者の個人情報を開発者のサーバーに収集・保存しません。解析ツールや広告SDKも含まれていません。</p>
<ul>
  <li>Notion のアクセストークンは、利用者の端末内の Keychain にのみ保存されます。</li>
  <li>ダウンロードしたメディアファイルと再生履歴は、利用者の端末内にのみ保存されます。</li>
  <li>認証中継サーバー（Cloudflare Workers）は、Notion OAuth の認可コードをトークンへ交換する処理のみを行い、
      認証更新時にはリフレッシュトークンを中継します。認可コードやトークンを永続保存したりログに記録したりしません。</li>
</ul>

<h2>外部サービスとの通信</h2>
<ul>
  <li>Notion API（api.notion.com）: 利用者が許可したワークスペースのデータベースとファイルを取得するために通信します。</li>
  <li>メディアファイルの配信元（Notion が発行する署名付きURL）: 再生とダウンロードのために通信します。</li>
</ul>
<p>各サービスのプライバシーポリシーが適用されます。</p>

<h2>情報の削除</h2>
<p>トークンは本アプリの設定からサインアウトすると削除されます。Keychainの情報はアプリの削除後も残る場合があります。
ダウンロードは本アプリの設定から削除できます。アプリを削除すると、ダウンロードと履歴も削除されます。
Notion 側の連携は、Notion の設定画面からいつでも解除できます。</p>

<hr>

<h1>Privacy Policy</h1>
<p>This policy describes how "Playback for Notion" (the "App") handles information.</p>

<h2>Information We Collect</h2>
<p>The App does not collect or store personal information on the developer's servers.
It contains no analytics or advertising SDKs.</p>
<ul>
  <li>Your Notion access token is stored only in the Keychain on your device.</li>
  <li>Downloaded media files and playback history are stored only on your device.</li>
  <li>The authentication relay (Cloudflare Workers) only exchanges a Notion OAuth
      authorization code for tokens and relays refresh tokens during renewal;
      it never persistently stores or logs codes or tokens.</li>
</ul>

<h2>Third-Party Services</h2>
<ul>
  <li>Notion API (api.notion.com): to read databases and files you have authorized.</li>
  <li>Media file hosts (signed URLs issued by Notion): for playback and downloads.</li>
</ul>

<h2>Deleting Your Information</h2>
<p>Sign out in the App's settings to delete your tokens. Keychain data may remain after uninstalling the App.
Delete downloads in the App's settings. Uninstalling removes downloads and history.
You can revoke the Notion connection at any time in your Notion settings.</p>

${disclaimer}
`,
);

export const supportHTML = page(
  "サポート / Support",
  `
<h1>サポート</h1>

<h2>データベースが見つからないとき</h2>
<p>OAuth 許可の際に、対象のページ／データベースへのアクセスを許可しているか確認してください。
トークン接続の場合は、Notion のページ右上「…」→「接続を追加」で、作成した接続を対象DBに追加してください。</p>

<h2>再生・ダウンロードが始まらないとき</h2>
<p>Notion のファイルURLは期限付きのため、本アプリは再生直前にURLを取得し直します。
ネットワーク接続を確認のうえ、一覧を引っ張って更新（Pull to Refresh）してからお試しください。
ダウンロード済みのファイルはオフラインでも再生できます。</p>

<h2>お問い合わせ</h2>
<p><a href="https://github.com/satoki252595/nhkRadio/issues">サポート窓口（GitHub Issues）</a>へお問い合わせください。
公開の窓口なので、トークン・個人情報・非公開DBの内容は投稿しないでください。
不具合報告の際は、iOS のバージョンと発生手順を添えていただけると助かります。</p>

${disclaimer}
`,
);
