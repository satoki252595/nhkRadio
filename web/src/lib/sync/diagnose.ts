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
          detail:
            'トークンにContents:Write権限がありません。Fine-grained tokenの場合、対象リポジトリで「Contents: Read and write」を設定してください。',
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

  // Step 4: ファイルパス確認
  try {
    const url = `${API_BASE}/repos/${config.owner}/${config.repo}/contents/${encodePath(path)}?ref=${encodeURIComponent(branch)}`;
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
