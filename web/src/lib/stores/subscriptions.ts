import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const STORAGE_KEY = 'nhk_subscriptions';

function loadInitial(): Set<string> {
  if (!browser) return new Set();
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return new Set();
  try {
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

function createSubscriptionsStore() {
  const { subscribe, set, update } = writable<Set<string>>(loadInitial());

  return {
    subscribe,
    toggle: (seriesId: string) => {
      update((s) => {
        const next = new Set(s);
        if (next.has(seriesId)) {
          next.delete(seriesId);
        } else {
          next.add(seriesId);
        }
        if (browser) {
          localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
        }
        return next;
      });
    },
    clear: () => {
      if (browser) localStorage.removeItem(STORAGE_KEY);
      set(new Set());
    },
    export: (): string => {
      let current: Set<string> = new Set();
      subscribe((v) => (current = v))();
      return JSON.stringify({ series_ids: [...current] }, null, 2);
    },
  };
}

export const subscriptions = createSubscriptionsStore();
