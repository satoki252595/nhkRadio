import type { SubscriptionsPayload, SyncAdapter } from './types';

export interface GitHubSyncConfig {
  token: string;
  owner: string;
  repo: string;
  /** 保存先ファイルパス。デフォルト: data/subscriptions.json */
  path?: string;
  /** ブランチ名。デフォルト: main */
  branch?: string;
}

const API_BASE = 'https://api.github.com';

function headers(token: string): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

/** base64 UTF-8 エンコード（日本語対応） */
function b64encode(s: string): string {
  const bytes = new TextEncoder().encode(s);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

/** base64 UTF-8 デコード */
function b64decode(s: string): string {
  const bin = atob(s.replace(/\s/g, ''));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

export function createGitHubSyncAdapter(config: GitHubSyncConfig): SyncAdapter {
  const path = config.path ?? 'data/subscriptions.json';
  const branch = config.branch ?? 'main';
  const contentsUrl = `${API_BASE}/repos/${config.owner}/${config.repo}/contents/${path}`;

  async function getCurrent(): Promise<{ sha: string; content: string } | null> {
    const res = await fetch(`${contentsUrl}?ref=${encodeURIComponent(branch)}`, {
      headers: headers(config.token),
    });
    if (res.status === 404) return null;
    if (!res.ok) {
      throw new Error(`GitHub GET failed: ${res.status} ${await res.text()}`);
    }
    const data = await res.json();
    return { sha: data.sha, content: b64decode(data.content) };
  }

  return {
    async pull() {
      const cur = await getCurrent();
      if (!cur) return null;
      try {
        return JSON.parse(cur.content) as SubscriptionsPayload;
      } catch {
        return null;
      }
    },
    async push(payload: SubscriptionsPayload) {
      const cur = await getCurrent();
      const body: Record<string, unknown> = {
        message: `chore(subscriptions): update from web UI (${payload.series_ids.length} series)`,
        content: b64encode(JSON.stringify(payload, null, 2) + '\n'),
        branch,
      };
      if (cur) body.sha = cur.sha;

      const res = await fetch(contentsUrl, {
        method: 'PUT',
        headers: { ...headers(config.token), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        throw new Error(`GitHub PUT failed: ${res.status} ${await res.text()}`);
      }
    },
  };
}
