/**
 * GitHub接続診断: 段階的にアクセスをテストして404/403の原因を特定する。
 */
import type { GitHubSyncConfig } from './github';

export interface DiagnosticResult {
  ok: boolean;
  steps: Array<{ step: string; ok: boolean; detail: string }>;
}

const API_BASE = 'https://api.github.com';

function headers(token: string): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

function encodePath(path: string): string {
  return path
    .split('/')
    .map((seg) => encodeURIComponent(seg))
    .join('/');
}

function b64encode(s: string): string {
  const bytes = new TextEncoder().encode(s);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

export async function diagnose(config: GitHubSyncConfig): Promise<DiagnosticResult> {
  const steps: DiagnosticResult['steps'] = [];
  const branch = config.branch ?? 'main';
  const path = config.path ?? 'data/subscriptions.json';

  // Step 1: トークン確認
  try {
    const res = await fetch(`${API_BASE}/user`, { headers: headers(config.token) });
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

  // Step 2: リポジトリアクセス
  try {
    const res = await fetch(`${API_BASE}/repos/${config.owner}/${config.repo}`, {
      headers: headers(config.token),
    });
    if (res.ok) {
      const repo = await res.json();
      steps.push({
        step: '2. リポジトリアクセス',
        ok: true,
        detail: `${repo.full_name} (${repo.private ? 'private' : 'public'}) にアクセス可能`,
      });
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
      `${API_BASE}/repos/${config.owner}/${config.repo}/branches/${encodeURIComponent(branch)}`,
      { headers: headers(config.token) },
    );
    if (res.ok) {
      steps.push({
        step: '3. ブランチ確認',
        ok: true,
        detail: `${branch} ブランチは存在します`,
      });
    } else if (res.status === 404) {
      steps.push({
        step: '3. ブランチ確認',
        ok: false,
        detail: `ブランチ「${branch}」が存在しません。設定のブランチ名を確認してください。`,
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

  // Step 4: ファイルパス確認 (shaも取得)
  let existingSha: string | null = null;
  try {
    const url = `${API_BASE}/repos/${config.owner}/${config.repo}/contents/${encodePath(path)}?ref=${encodeURIComponent(branch)}`;
    const res = await fetch(url, { headers: headers(config.token) });
    if (res.ok) {
      const data = await res.json();
      existingSha = data.sha as string;
      steps.push({
        step: '4. ファイルパス確認',
        ok: true,
        detail: `既存ファイルが見つかりました (sha: ${existingSha!.slice(0, 7)}) → 更新モード`,
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

  // Step 5: 実際の書き込みテスト (PUT)
  // 読み取り権限と書き込み権限は別。PUTが通るか実際に試す。
  try {
    const testPath = `.nhk-radio-write-test-${Date.now()}.tmp`;
    const putUrl = `${API_BASE}/repos/${config.owner}/${config.repo}/contents/${encodePath(testPath)}`;
    const res = await fetch(putUrl, {
      method: 'PUT',
      headers: { ...headers(config.token), 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: 'test: write permission check (auto-delete)',
        content: b64encode('write permission test'),
        branch,
      }),
    });
    if (res.ok) {
      const data = await res.json();
      const testSha = data.content?.sha;
      steps.push({
        step: '5. 書き込みテスト',
        ok: true,
        detail: `✓ トークンはContents:Write権限を持っています。既存ファイルのsha: ${existingSha ? existingSha.slice(0, 7) : '(新規)'}`,
      });
      // 作成したテストファイルを削除
      if (testSha) {
        await fetch(putUrl, {
          method: 'DELETE',
          headers: { ...headers(config.token), 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: 'test: cleanup write permission check',
            sha: testSha,
            branch,
          }),
        });
      }
    } else {
      const errText = await res.text();
      let hint = '';
      if (res.status === 403) {
        hint =
          '\n\n【403の原因候補】\n' +
          '(1) Fine-grained token の Permissions → Contents が「Read and write」になっていない\n' +
          '(2) ブランチ保護ルール (Branch protection) で直接pushが禁止されている\n' +
          '    → Settings → Branches → Protection rules を確認\n' +
          '(3) Organization Fine-grained token policy で制限されている\n' +
          '(4) トークン作成後に権限を変更したが、トークン再発行していない';
      }
      steps.push({
        step: '5. 書き込みテスト',
        ok: false,
        detail: `PUT失敗 ${res.status}: ${errText}${hint}`,
      });
      return { ok: false, steps };
    }
  } catch (e) {
    steps.push({
      step: '5. 書き込みテスト',
      ok: false,
      detail: `通信エラー: ${e instanceof Error ? e.message : String(e)}`,
    });
    return { ok: false, steps };
  }

  return { ok: true, steps };
}
