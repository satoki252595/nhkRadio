<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import type { ProgramsData, Program } from '$lib/types';
  import { subscriptions } from '$lib/stores/subscriptions';

  let data: ProgramsData | null = $state(null);
  let loading = $state(true);
  let error: string | null = $state(null);
  let subscribedOnly = $state(false);

  onMount(async () => {
    try {
      const res = await fetch(`${base}/data/programs-latest.json`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (e) {
      error = `データ取得失敗: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      loading = false;
    }
  });

  function fmtTime(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  }

  function fmtDuration(sec: number): string {
    const min = Math.floor(sec / 60);
    return `${min}分`;
  }

  let filtered = $derived.by(() => {
    if (!data) return [];
    let list = [...data.programs].sort((a, b) => a.start_time.localeCompare(b.start_time));
    if (subscribedOnly) {
      list = list.filter((p) => $subscriptions.has(p.series_id));
    }
    return list;
  });

  function toggleSub(seriesId: string) {
    if (seriesId) subscriptions.toggle(seriesId);
  }

  const serviceLabels: Record<string, string> = {
    r1: 'AM',
    r3: 'FM',
  };
</script>

<svelte:head>
  <title>今日の番組 | NHK Radio</title>
</svelte:head>

<h1 class="page-title">今日の番組</h1>
{#if data}
  <p class="page-subtitle">
    {data.date} · エリア {data.area} · {data.programs.length}番組
  </p>
{/if}

<div class="controls">
  <label class="filter">
    <input type="checkbox" bind:checked={subscribedOnly} />
    <span>購読中のみ表示</span>
  </label>
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
  </div>
{:else if filtered.length === 0}
  <div class="empty">
    <div class="empty-icon">📭</div>
    <p>番組がありません</p>
  </div>
{:else}
  <div class="list">
    {#each filtered as p (p.id)}
      {@const isSubscribed = p.series_id && $subscriptions.has(p.series_id)}
      <div class="item" class:subscribed={isSubscribed}>
        <div class="time">
          <div class="time-start">{fmtTime(p.start_time)}</div>
          <div class="time-duration">{fmtDuration(p.duration_sec)}</div>
        </div>
        <div class="service-chip service-{p.service}">{serviceLabels[p.service] || p.service}</div>
        <div class="body">
          <div class="title">{p.title}</div>
          {#if p.content}
            <div class="content-text">{p.content.slice(0, 120)}{p.content.length > 120 ? '…' : ''}</div>
          {/if}
        </div>
        {#if p.series_id}
          <button
            class="sub-toggle"
            class:active={isSubscribed}
            onclick={() => toggleSub(p.series_id)}
            aria-label={isSubscribed ? '購読解除' : '購読する'}
          >
            {isSubscribed ? '✓' : '+'}
          </button>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .controls {
    display: flex;
    margin-bottom: 1.25rem;
  }
  .filter {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 1rem;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    cursor: pointer;
    font-size: 0.875rem;
    color: var(--text-1);
    transition: all 0.15s ease;
  }
  .filter:hover {
    background: rgba(255, 255, 255, 0.06);
  }
  .filter input {
    accent-color: var(--accent-1);
  }
  .list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .item {
    display: grid;
    grid-template-columns: 70px auto 1fr auto;
    gap: 0.875rem;
    align-items: center;
    padding: 0.875rem 1rem;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border);
    transition: all 0.15s ease;
  }
  .item:hover {
    background: rgba(255, 255, 255, 0.05);
    border-color: var(--border-strong);
  }
  .item.subscribed {
    border-color: rgba(102, 126, 234, 0.4);
    background: rgba(102, 126, 234, 0.08);
  }
  .time {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
  }
  .time-start {
    font-size: 1rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .time-duration {
    font-size: 0.75rem;
    color: var(--text-2);
  }
  .service-chip {
    font-size: 0.6875rem;
    font-weight: 700;
    padding: 0.25rem 0.5rem;
    border-radius: 6px;
    letter-spacing: 0.05em;
    color: #fff;
  }
  .service-r1 {
    background: linear-gradient(135deg, #3b82f6, #1e40af);
  }
  .service-r3 {
    background: linear-gradient(135deg, #a855f7, #6b21a8);
  }
  .body {
    min-width: 0;
  }
  .title {
    font-size: 0.9375rem;
    font-weight: 600;
    color: var(--text-0);
    margin-bottom: 0.25rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .content-text {
    font-size: 0.8125rem;
    color: var(--text-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sub-toggle {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.08);
    color: var(--text-1);
    font-size: 1.125rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
  }
  .sub-toggle:hover {
    background: rgba(255, 255, 255, 0.14);
  }
  .sub-toggle.active {
    background: var(--accent-gradient);
    color: #fff;
  }
  @media (max-width: 640px) {
    .item {
      grid-template-columns: 60px 1fr auto;
    }
    .service-chip {
      display: none;
    }
  }
</style>
