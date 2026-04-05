import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import type { SubscriptionsPayload, SyncAdapter } from '../sync/types';

const STORAGE_KEY = 'nhk_subscriptions';

function loadInitial(): Set<string> {
  if (!browser) return new Set();
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return new Set();
  try {
    const parsed = JSON.parse(raw);
    // 新形式: {series_ids: [...]} / 旧形式: [...]
    if (Array.isArray(parsed)) return new Set(parsed);
    if (parsed && Array.isArray(parsed.series_ids)) return new Set(parsed.series_ids);
    return new Set();
  } catch {
    return new Set();
  }
}

function persist(ids: Set<string>): void {
  if (!browser) return;
  const payload: SubscriptionsPayload = {
    series_ids: [...ids],
    updated_at: new Date().toISOString(),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

function snapshot(ids: Set<string>): SubscriptionsPayload {
  return {
    series_ids: [...ids],
    updated_at: new Date().toISOString(),
  };
}

function createSubscriptionsStore() {
  const { subscribe, set, update } = writable<Set<string>>(loadInitial());

  const current = (): Set<string> => {
    let v: Set<string> = new Set();
    subscribe((x) => (v = x))();
    return v;
  };

  return {
    subscribe,
    toggle: (seriesId: string) => {
      update((s) => {
        const next = new Set(s);
        if (next.has(seriesId)) next.delete(seriesId);
        else next.add(seriesId);
        persist(next);
        return next;
      });
    },
    clear: () => {
      if (browser) localStorage.removeItem(STORAGE_KEY);
      set(new Set());
    },
    export: (): string => {
      return JSON.stringify(snapshot(current()), null, 2);
    },
    /** 現在の購読リストをリモートに保存。 */
    pushTo: async (adapter: SyncAdapter): Promise<void> => {
      await adapter.push(snapshot(current()));
    },
    /** リモートから購読リストを取得してローカルに反映。 */
    pullFrom: async (adapter: SyncAdapter): Promise<boolean> => {
      const remote = await adapter.pull();
      if (!remote) return false;
      const next = new Set(remote.series_ids);
      persist(next);
      set(next);
      return true;
    },
  };
}

export const subscriptions = createSubscriptionsStore();
