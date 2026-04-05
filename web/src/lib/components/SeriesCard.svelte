<script lang="ts">
  import type { Series } from '$lib/types';
  import { subscriptions } from '$lib/stores/subscriptions';

  interface Props {
    series: Series;
  }

  let { series }: Props = $props();

  let isSubscribed = $derived($subscriptions.has(series.series_id));

  const serviceColors: Record<string, string> = {
    r1: 'linear-gradient(135deg, #3b82f6, #1e40af)',
    r3: 'linear-gradient(135deg, #a855f7, #6b21a8)',
  };
  const serviceLabels: Record<string, string> = {
    r1: 'NHK AM',
    r3: 'NHK FM',
  };

  function toggle() {
    subscriptions.toggle(series.series_id);
  }
</script>

<div class="card" class:subscribed={isSubscribed}>
  <div class="card-top">
    <span class="service-badge" style="background: {serviceColors[series.service] || '#333'}">
      {serviceLabels[series.service] || series.service.toUpperCase()}
    </span>
    <button
      class="sub-btn"
      class:subscribed={isSubscribed}
      onclick={toggle}
      aria-label={isSubscribed ? '購読解除' : '購読する'}
    >
      {#if isSubscribed}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        購読中
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
        購読
      {/if}
    </button>
  </div>

  <h3 class="card-title">{series.series_name}</h3>

  {#if series.genre.length > 0}
    <div class="genres">
      {#each series.genre.slice(0, 2) as g}
        <span class="genre">{g}</span>
      {/each}
    </div>
  {/if}

  <p class="description">{series.sample_description || series.sample_title}</p>
</div>

<style>
  .card {
    position: relative;
    padding: 1.25rem;
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(30, 30, 58, 0.8), rgba(22, 22, 46, 0.8));
    border: 1px solid var(--border);
    transition: all 0.2s ease;
    display: flex;
    flex-direction: column;
    gap: 0.625rem;
  }
  .card:hover {
    border-color: var(--border-strong);
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  }
  .card.subscribed {
    border-color: rgba(102, 126, 234, 0.5);
    background: linear-gradient(
      180deg,
      rgba(102, 126, 234, 0.12),
      rgba(118, 75, 162, 0.08)
    );
  }
  .card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .service-badge {
    display: inline-block;
    padding: 0.25rem 0.625rem;
    border-radius: 999px;
    font-size: 0.6875rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #fff;
  }
  .sub-btn {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.375rem 0.75rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.08);
    color: var(--text-1);
    font-size: 0.8125rem;
    font-weight: 600;
    transition: all 0.15s ease;
  }
  .sub-btn:hover {
    background: rgba(255, 255, 255, 0.14);
    color: #fff;
  }
  .sub-btn.subscribed {
    background: var(--accent-gradient);
    color: #fff;
  }
  .card-title {
    font-size: 1.0625rem;
    font-weight: 600;
    line-height: 1.4;
    color: var(--text-0);
  }
  .genres {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
  }
  .genre {
    font-size: 0.6875rem;
    padding: 0.125rem 0.5rem;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-2);
  }
  .description {
    margin: 0;
    font-size: 0.8125rem;
    line-height: 1.5;
    color: var(--text-2);
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
</style>
