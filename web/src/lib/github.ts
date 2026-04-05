/**
 * GitHub REST API クライアント
 * 購読リストJSONをリポジトリにコミットするために使用。
 */

export interface GitHubConfig {
  token: string;
  owner: string;
  repo: string;
  branch: string;
  path: string;
}

export interface PushResult {
  ok: boolean;
  message: string;
  commitUrl?: string;
  debug?: string[];
}

export interface DiagnosticResult {
  ok: boolean;
  steps: Array<{ step: string; ok: boolean; detail: string }>;
}

const API_BASE = 'https://api.github.com';

function headers(token: string): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'Content-Type': 'application/json',
  };
}

/**
 * パスの各セグメントを個別にエンコード (スラッシュは残す)。
 */
function encodePath(path: string): string {
  return path
    .split('/')
    .map((seg) => encodeURIComponent(seg))
    .join('/');
}

/**
 * UTF-8文字列を base64 にエンコード (GitHub API用)。
 */
function utf8ToBase64(str: string): string {
  const bytes = new TextEncoder().encode(str);
  let binary = '';
  for (const b of bytes) {
    binary += String.fromCharCode(b);
  }
  return btoa(binary);
}

/**
 * 接続診断: トークン→リポジトリ→ブランチ→ファイルの順にアクセスチェック。
 * どこで落ちているかを段階的に特定する。
 */
export async function diagnose(config: GitHubConfig): Promise<DiagnosticResult> {
  const steps: DiagnosticResult['steps'] = [];

  // Step 1: トークン確認 (GET /user)
  try {
    const res = await fetch(`${API_BASE}/user`, {
      headers: headers(config.token),
    });
    if (res.ok) {
      const user = await res.json();
      steps.push({
        step: '1. トークン認証',
        ok: true,
        detail: `ログインユーザー: ${user.login}`,
      });
    } else if (res.status === 401) {
      steps.push({
        step: '1. トークン認証',
        ok: false,
        detail: 'トークンが無効または期限切れです (401)',
      });
      return { ok: false, steps };
    } else {
      steps.push({
        step: '1. トークン認証',
        ok: false,
        detail: `HTTP ${res.status}: ${await res.text()}`,
      });
      return { ok: false, steps };
    }
  } catch (e) {
    steps.push({
      step: '1. トークン認証',
      ok: false,
      detail: `通信エラー: ${e instanceof Error ? e.message : String(e)}`,
    });
    return { ok: false, steps };
  }

  // Step 2: リポジトリアクセス確認
  try {
    const res = await fetch(`${API_BASE}/repos/${config.owner}/${config.repo}`, {
      headers: headers(config.token),
    });
    if (res.ok) {
      const repo = await res.json();
      const perms = repo.permissions || {};
      const canWrite = perms.push || perms.maintain || perms.admin;
      steps.push({
        step: '2. リポジトリアクセス',
        ok: true,
        detail: `${repo.full_name} (${repo.private ? 'private' : 'public'}) / 書き込み権限: ${canWrite ? 'あり' : 'なし'}`,
      });
      if (!canWrite) {
        steps.push({
          step: '→ 権限エラー',
          ok: false,
          detail: 'トークンにContents:Write権限がありません。Fine-grained tokenの場合、対象リポジトリで「Contents: Read and write」を設定してください。',
        });
        return { ok: false, steps };
      }
    } else if (res.status === 404) {
      steps.push({
        step: '2. リポジトリアクセス',
        ok: false,
        detail: `リポジトリが見つかりません: ${config.owner}/${config.repo}
原因候補:
  (a) owner/repo名のスペルミス
  (b) Fine-grained tokenで対象リポジトリが未選択
  (c) プライベートリポジトリへのアクセス権なし
  (d) リポジトリ自体が存在しない`,
      });
      return { ok: false, steps };
    } else {
      steps.push({
        step: '2. リポジトリアクセス',
        ok: false,
        detail: `HTTP ${res.status}: ${await res.text()}`,
      });
      return { ok: false, steps };
    }
  } catch (e) {
    steps.push({
      step: '2. リポジトリアクセス',
      ok: false,
      detail: `通信エラー: ${e instanceof Error ? e.message : String(e)}`,
    });
    return { ok: false, steps };
  }

  // Step 3: ブランチ確認
  try {
    const res = await fetch(
      `${API_BASE}/repos/${config.owner}/${config.repo}/branches/${encodeURIComponent(config.branch)}`,
      { headers: headers(config.token) },
    );
    if (res.ok) {
      steps.push({
        step: '3. ブランチ確認',
        ok: true,
        detail: `${config.branch} ブランチは存在します`,
      });
    } else if (res.status === 404) {
      steps.push({
        step: '3. ブランチ確認',
        ok: false,
        detail: `ブランチ「${config.branch}」が存在しません。設定のブランチ名を確認してください。`,
      });
      return { ok: false, steps };
    } else {
      steps.push({
        step: '3. ブランチ確認',
        ok: false,
        detail: `HTTP ${res.status}: ${await res.text()}`,
      });
      return { ok: false, steps };
    }
  } catch (e) {
    steps.push({
      step: '3. ブランチ確認',
      ok: false,
      detail: `通信エラー: ${e instanceof Error ? e.message : String(e)}`,
    });
    return { ok: false, steps };
  }

  // Step 4: ファイルパス確認 (存在すればshaを取得、無くてもOK)
  try {
    const url = `${API_BASE}/repos/${config.owner}/${config.repo}/contents/${encodePath(config.path)}?ref=${encodeURIComponent(config.branch)}`;
    const res = await fetch(url, { headers: headers(config.token) });
    if (res.ok) {
      const data = await res.json();
      steps.push({
        step: '4. ファイルパス確認',
        ok: true,
        detail: `既存ファイルが見つかりました (sha: ${(data.sha as string).slice(0, 7)}) → 更新モード`,
      });
    } else if (res.status === 404) {
      steps.push({
        step: '4. ファイルパス確認',
        ok: true,
        detail: `ファイル未作成 → 新規作成モード`,
      });
    } else {
      steps.push({
        step: '4. ファイルパス確認',
        ok: false,
        detail: `HTTP ${res.status}: ${await res.text()}`,
      });
      return { ok: false, steps };
    }
  } catch (e) {
    steps.push({
      step: '4. ファイルパス確認',
      ok: false,
      detail: `通信エラー: ${e instanceof Error ? e.message : String(e)}`,
    });
    return { ok: false, steps };
  }

  return { ok: true, steps };
}

/**
 * 既存ファイルの sha を取得 (更新時に必要)。
 * 404の場合は null を返す (新規作成)。
 */
async function getExistingSha(config: GitHubConfig): Promise<string | null> {
  const url = `${API_BASE}/repos/${config.owner}/${config.repo}/contents/${encodePath(config.path)}?ref=${encodeURIComponent(config.branch)}`;
  const res = await fetch(url, {
    method: 'GET',
    headers: headers(config.token),
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`sha取得失敗 (${res.status}): ${await res.text()}`);
  }
  const data = await res.json();
  return data.sha as string;
}

/**
 * JSONテキストをGitHubリポジトリにコミット/更新する。
 */
export async function pushJsonFile(
  config: GitHubConfig,
  content: string,
  message: string,
): Promise<PushResult> {
  const debug: string[] = [];

  // 入力バリデーション
  if (!config.token) return { ok: false, message: 'トークン未設定', debug };
  if (!config.owner || !config.repo) {
    return { ok: false, message: 'owner/repo未設定', debug };
  }
  if (!config.path) return { ok: false, message: 'パス未設定', debug };

  try {
    // 1. 既存ファイルの sha を取得
    const shaUrl = `${API_BASE}/repos/${config.owner}/${config.repo}/contents/${encodePath(config.path)}?ref=${encodeURIComponent(config.branch)}`;
    debug.push(`GET ${shaUrl}`);
    const sha = await getExistingSha(config);
    debug.push(`sha: ${sha ?? '(新規作成)'}`);

    // 2. PUT で作成/更新
    const putUrl = `${API_BASE}/repos/${config.owner}/${config.repo}/contents/${encodePath(config.path)}`;
    debug.push(`PUT ${putUrl}`);
    const body: Record<string, unknown> = {
      message,
      content: utf8ToBase64(content),
      branch: config.branch,
    };
    if (sha) body.sha = sha;

    const res = await fetch(putUrl, {
      method: 'PUT',
      headers: headers(config.token),
      body: JSON.stringify(body),
    });
    debug.push(`response: ${res.status} ${res.statusText}`);

    if (!res.ok) {
      const errText = await res.text();
      let hint = '';
      if (res.status === 404) {
        hint =
          '\n\n【404の原因候補】\n' +
          '・owner/repo名のスペルミス\n' +
          '・Fine-grained tokenで対象リポジトリが選択されていない\n' +
          '・トークンにContents:Write権限がない\n' +
          '・プライベートリポジトリへのアクセス権がない\n\n' +
          '設定画面の「接続テスト」で原因を特定してください。';
      } else if (res.status === 401) {
        hint = '\n\nトークンが無効または期限切れです';
      } else if (res.status === 403) {
        hint = '\n\nトークンに書き込み権限がありません (Contents: Read and write が必要)';
      } else if (res.status === 422) {
        hint = '\n\nバリデーションエラー (shaやブランチ名を確認)';
      }
      return {
        ok: false,
        message: `PUT失敗 ${res.status}: ${errText}${hint}`,
        debug,
      };
    }

    const data = await res.json();
    return {
      ok: true,
      message: sha ? '更新しました' : '新規作成しました',
      commitUrl: data.commit?.html_url,
      debug,
    };
  } catch (e) {
    return {
      ok: false,
      message: `エラー: ${e instanceof Error ? e.message : String(e)}`,
      debug,
    };
  }
}
