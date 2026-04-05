<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import type { SeriesIndex, Series } from '$lib/types';
  import { subscriptions } from '$lib/stores/subscriptions';
  import SeriesCard from '$lib/components/SeriesCard.svelte';

  let allSeries: Series[] = $state([]);
  let loading = $state(true);
  let error: string | null = $state(null);
  let query = $state('');
  let serviceFilter = $state<'all' | 'nhk' | 'radiko'>('all');
  let areaFilter = $state<'all' | 'kanto' | 'kansai'>('all');

  onMount(async () => {
    try {
      const res = await fetch(`${base}/data/series.json`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: SeriesIndex = await res.json();
      allSeries = data.series;
    } catch (e) {
      error = `データ取得失敗: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      loading = false;
    }
  });

  let filtered = $derived.by(() => {
    let list = allSeries;
    if (serviceFilter === 'nhk') {
      list = list.filter((s) => s.service === 'r1' || s.service === 'r3');
    } else if (serviceFilter === 'radiko') {
      list = list.filter((s) => s.service.startsWith('radiko:'));
    }
    if (areaFilter === 'kanto') {
      // JP13=東京 JP14=神奈川 JP11=埼玉 JP12=千葉 JP08=茨城 JP09=栃木 JP10=群馬
      list = list.filter((s) => /^JP(08|09|10|11|12|13|14)$/.test(s.area ?? '') || s.area === 'NHK');
    } else if (areaFilter === 'kansai') {
      // JP27=大阪 JP28=兵庫 JP26=京都 JP29=奈良 JP25=滋賀 JP30=和歌山
      list = list.filter((s) => /^JP(25|26|27|28|29|30)$/.test(s.area ?? '') || s.area === 'NHK');
    }
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter(
        (s) =>
          s.series_name.toLowerCase().includes(q) ||
          s.sample_description.toLowerCase().includes(q) ||
          s.genre.some((g) => g.toLowerCase().includes(q)),
      );
    }
    return list;
  });

  let subscribedCount = $derived($subscriptions.size);
</script>

<svelte:head>
  <title>シリーズ | NHK Radio</title>
</svelte:head>

<h1 class="page-title">シリーズを購読</h1>
<p class="page-subtitle">
  購読した番組は毎週自動録音されます（{subscribedCount}件 購読中 / 全{allSeries.length}件）
</p>

<div class="controls">
  <input
    type="text"
    bind:value={query}
    placeholder="番組名・ジャンルで検索"
    class="search"
  />
  <div class="tabs">
    <button
      class="tab"
      class:active={serviceFilter === 'all'}
      onclick={() => (serviceFilter = 'all')}
    >
      すべて
    </button>
    <button
      class="tab"
      class:active={serviceFilter === 'nhk'}
      onclick={() => (serviceFilter = 'nhk')}
    >
      NHK
    </button>
    <button
      class="tab"
      class:active={serviceFilter === 'radiko'}
      onclick={() => (serviceFilter = 'radiko')}
    >
      民放
    </button>
  </div>
  <div class="tabs">
    <button
      class="tab"
      class:active={areaFilter === 'all'}
      onclick={() => (areaFilter = 'all')}
    >
      全国
    </button>
    <button
      class="tab"
      class:active={areaFilter === 'kanto'}
      onclick={() => (areaFilter = 'kanto')}
    >
      関東
    </button>
    <button
      class="tab"
      class:active={areaFilter === 'kansai'}
      onclick={() => (areaFilter = 'kansai')}
    >
      関西
    </button>
  </div>
</div>

{#if loading}
  <div class="empty">
    <div class="empty-icon">⏳</div>
    <p>読み込み中...</p>
  </div>
{:else if error}
  <div class="empty">
    <div class="empty-icon">⚠️</div>
    <p>{error}</p>
    <p style="font-size: 0.875rem; margin-top: 0.5rem;">
      data/series.json が存在することを確認してください
    </p>
  </div>
{:else if filtered.length === 0}
  <div class="empty">
    <div class="empty-icon">🔍</div>
    <p>該当する番組がありません</p>
  </div>
{:else}
  <div class="grid">
    {#each filtered as series (series.series_id)}
      <SeriesCard {series} />
    {/each}
  </div>
{/if}

<style>
  .controls {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
  }
  .search {
    flex: 1;
    min-width: 200px;
    padding: 0.625rem 1rem;
    border-radius: 12px;
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-0);
    font-size: 0.9375rem;
    outline: none;
    transition: all 0.15s ease;
  }
  .search:focus {
    border-color: var(--accent-1);
    background: rgba(255, 255, 255, 0.06);
  }
  .search::placeholder {
    color: var(--text-2);
  }
  .tabs {
    display: flex;
    gap: 0.25rem;
    padding: 0.25rem;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
  }
  .tab {
    padding: 0.5rem 1rem;
    border-radius: 8px;
    color: var(--text-2);
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.15s ease;
  }
  .tab:hover {
    color: var(--text-0);
  }
  .tab.active {
    background: var(--accent-gradient);
    color: #fff;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 1rem;
  }
</style>
