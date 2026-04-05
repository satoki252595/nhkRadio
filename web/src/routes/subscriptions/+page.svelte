<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import type { SeriesIndex, Series } from '$lib/types';
  import { subscriptions } from '$lib/stores/subscriptions';
  import SeriesCard from '$lib/components/SeriesCard.svelte';

  let allSeries: Series[] = $state([]);
  let loading = $state(true);
  let copied = $state(false);

  onMount(async () => {
    try {
      const res = await fetch(`${base}/data/series.json`);
      if (res.ok) {
        const data: SeriesIndex = await res.json();
        allSeries = data.series;
      }
    } finally {
      loading = false;
    }
  });

  let subscribedSeries = $derived(
    allSeries.filter((s) => $subscriptions.has(s.series_id)),
  );

  function copyExport() {
    const json = subscriptions.export();
    navigator.clipboard.writeText(json).then(() => {
      copied = true;
      setTimeout(() => (copied = false), 2000);
    });
  }

  function downloadExport() {
    const json = subscriptions.export();
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'subscriptions.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  function clearAll() {
    if (confirm('すべての購読を解除しますか？')) {
      subscriptions.clear();
    }
  }
</script>

<svelte:head>
  <title>購読中 | NHK Radio</title>
</svelte:head>

<h1 class="page-title">購読中のシリーズ</h1>
<p class="page-subtitle">{$subscriptions.size}件 購読中</p>

{#if $subscriptions.size > 0}
  <div class="actions">
    <button class="btn primary" onclick={copyExport}>
      {copied ? '✓ コピー済み' : '📋 JSONをコピー'}
    </button>
    <button class="btn" onclick={downloadExport}>⬇ JSONダウンロード</button>
    <button class="btn danger" onclick={clearAll}>すべて解除</button>
  </div>

  <div class="info">
    <p>
      購読リスト（<code>subscriptions.json</code>）をリポジトリの <code>data/</code> に配置すると、
      GitHub Actions が自動録音します。
    </p>
  </div>
{/if}

{#if loading}
  <div class="empty">
    <div class="empty-icon">⏳</div>
    <p>読み込み中...</p>
  </div>
{:else if subscribedSeries.length === 0}
  <div class="empty">
    <div class="empty-icon">📻</div>
    <p>まだ購読していません</p>
    <p style="font-size: 0.875rem; margin-top: 0.5rem;">
      シリーズページから気になる番組を購読してください
    </p>
  </div>
{:else}
  <div class="grid">
    {#each subscribedSeries as series (series.series_id)}
      <SeriesCard {series} />
    {/each}
  </div>
{/if}

<style>
  .actions {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
  }
  .btn {
    padding: 0.5rem 1rem;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-1);
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.15s ease;
    border: 1px solid var(--border);
  }
  .btn:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #fff;
  }
  .btn.primary {
    background: var(--accent-gradient);
    color: #fff;
    border-color: transparent;
  }
  .btn.primary:hover {
    opacity: 0.9;
  }
  .btn.danger {
    color: var(--danger);
  }
  .btn.danger:hover {
    background: rgba(248, 113, 113, 0.1);
  }
  .info {
    padding: 1rem;
    border-radius: 12px;
    background: rgba(102, 126, 234, 0.08);
    border: 1px solid rgba(102, 126, 234, 0.2);
    margin-bottom: 1.5rem;
    font-size: 0.875rem;
    color: var(--text-1);
  }
  .info p {
    margin: 0;
  }
  .info code {
    padding: 0.125rem 0.375rem;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.08);
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 0.8125em;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 1rem;
  }
</style>
