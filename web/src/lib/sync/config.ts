import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import type { GitHubSyncConfig } from './github';

const STORAGE_KEY = 'nhk_sync_github_config';

function loadInitial(): GitHubSyncConfig | null {
  if (!browser) return null;
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (parsed?.token && parsed?.owner && parsed?.repo) return parsed;
  } catch {}
  return null;
}

function createGitHubSyncConfigStore() {
  const { subscribe, set } = writable<GitHubSyncConfig | null>(loadInitial());
  return {
    subscribe,
    save: (config: GitHubSyncConfig) => {
      if (browser) localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
      set(config);
    },
    clear: () => {
      if (browser) localStorage.removeItem(STORAGE_KEY);
      set(null);
    },
  };
}

export const githubSyncConfig = createGitHubSyncConfigStore();
