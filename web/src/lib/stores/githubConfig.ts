import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import type { GitHubConfig } from '$lib/github';

const STORAGE_KEY = 'nhk_github_config';

const DEFAULT_CONFIG: GitHubConfig = {
  token: '',
  owner: '',
  repo: '',
  branch: 'main',
  path: 'data/subscriptions.json',
};

function loadInitial(): GitHubConfig {
  if (!browser) return { ...DEFAULT_CONFIG };
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return { ...DEFAULT_CONFIG };
  try {
    return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

function createGitHubConfigStore() {
  const { subscribe, set, update } = writable<GitHubConfig>(loadInitial());

  function persist(config: GitHubConfig) {
    if (browser) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    }
  }

  return {
    subscribe,
    set: (config: GitHubConfig) => {
      persist(config);
      set(config);
    },
    update: (fn: (c: GitHubConfig) => GitHubConfig) => {
      update((c) => {
        const next = fn(c);
        persist(next);
        return next;
      });
    },
    clear: () => {
      if (browser) localStorage.removeItem(STORAGE_KEY);
      set({ ...DEFAULT_CONFIG });
    },
  };
}

export const githubConfig = createGitHubConfigStore();
