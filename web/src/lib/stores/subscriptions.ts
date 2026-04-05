import { writable, derived, get } from 'svelte/store';
import { browser } from '$app/environment';
import type { SubscriptionsPayload, SyncAdapter } from '../sync/types';

const STORAGE_KEY = 'nhk_subscriptions';

interface State {
  seriesIds: Set<string>;
  keywords: string[];
}

function loadInitial(): State {
  if (!browser) return { seriesIds: new Set(), keywords: [] };
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return { seriesIds: new Set(), keywords: [] };
  try {
    const parsed = JSON.parse(raw);
    // 旧形式: [...]
    if (Array.isArray(parsed)) {
      return { seriesIds: new Set(parsed), keywords: [] };
    }
    return {
      seriesIds: new Set(parsed.series_ids ?? []),
      keywords: Array.isArray(parsed.keywords) ? parsed.keywords : [],
    };
  } catch {
    return { seriesIds: new Set(), keywords: [] };
  }
}

function persist(state: State): void {
  if (!browser) return;
  const payload: SubscriptionsPayload = {
    series_ids: [...state.seriesIds],
    keywords: state.keywords,
    updated_at: new Date().toISOString(),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

function snapshot(state: State): SubscriptionsPayload {
  return {
    series_ids: [...state.seriesIds],
    keywords: state.keywords,
    updated_at: new Date().toISOString(),
  };
}

// 内部state
const stateStore = writable<State>(loadInitial());

// 公開: seriesIds (Set) のストア (旧API互換)
// $subscriptions.has(id) / .size が動くように Set を公開
const subscriptionsStore = {
  subscribe: derived(stateStore, ($s) => $s.seriesIds).subscribe,
  toggle: (seriesId: string) => {
    stateStore.update((s) => {
      const nextIds = new Set(s.seriesIds);
      if (nextIds.has(seriesId)) nextIds.delete(seriesId);
      else nextIds.add(seriesId);
      const next = { ...s, seriesIds: nextIds };
      persist(next);
      return next;
    });
  },
  clear: () => {
    if (browser) localStorage.removeItem(STORAGE_KEY);
    stateStore.set({ seriesIds: new Set(), keywords: [] });
  },
  export: (): string => {
    return JSON.stringify(snapshot(get(stateStore)), null, 2);
  },
  /** 現在の購読リストをリモートに保存。 */
  pushTo: async (adapter: SyncAdapter): Promise<void> => {
    await adapter.push(snapshot(get(stateStore)));
  },
  /** リモートから購読リストを取得してローカルに反映。 */
  pullFrom: async (adapter: SyncAdapter): Promise<boolean> => {
    const remote = await adapter.pull();
    if (!remote) return false;
    const next: State = {
      seriesIds: new Set(remote.series_ids),
      keywords: remote.keywords ?? [],
    };
    persist(next);
    stateStore.set(next);
    return true;
  },
};

export const subscriptions = subscriptionsStore;

// 公開: キーワード一覧の派生ストア
export const keywords = {
  subscribe: derived(stateStore, ($s) => $s.keywords).subscribe,
  add: (kw: string) => {
    const trimmed = kw.trim();
    if (!trimmed) return;
    stateStore.update((s) => {
      if (s.keywords.includes(trimmed)) return s;
      const next = { ...s, keywords: [...s.keywords, trimmed] };
      persist(next);
      return next;
    });
  },
  remove: (kw: string) => {
    stateStore.update((s) => {
      const next = { ...s, keywords: s.keywords.filter((k) => k !== kw) };
      persist(next);
      return next;
    });
  },
};
