<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import type { SeriesIndex, Series } from '$lib/types';
  import { subscriptions } from '$lib/stores/subscriptions';
  import { githubConfig } from '$lib/stores/githubConfig';
  import { pushJsonFile, type PushResult } from '$lib/github';
  import SeriesCard from '$lib/components/SeriesCard.svelte';
  import GitHubConfigModal from '$lib/components/GitHubConfigModal.svelte';

  let allSeries: Series[] = $state([]);
  let loading = $state(true);
  let configOpen = $state(false);
  let pushing = $state(false);
  let pushResult: PushResult | null = $state(null);

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

  let githubReady = $derived(
    Boolean($githubConfig.token && $githubConfig.owner && $githubConfig.repo),
  );

  function clearAll() {
    if (confirm('すべての購読を解除しますか？')) {
      subscriptions.clear();
    }
  }

  async function pushToGitHub() {
    if (!githubReady) {
      configOpen = true;
      return;
    }
    pushing = true;
    pushResult = null;
    try {
      const json = subscriptions.export();
      const result = await pushJsonFile(
        $githubConfig,
        json,
        `Update subscriptions (${$subscriptions.size} series)`,
      );
      pushResult = result;
      if (result.ok) {
        setTimeout(() => (pushResult = null), 5000);
      }
    } finally {
      pushing = false;
    }
  }
</script>

<svelte:head>
  <title>購読中 | NHK Radio</title>
</svelte:head>

<div class="header-row">
  <div>
    <h1 class="page-title">購読中のシリーズ</h1>
    <p class="page-subtitle">{$subscriptions.size}件 購読中</p>
  </div>
  <button class="icon-btn" onclick={() => (configOpen = true)} aria-label="GitHub設定">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="3"></circle>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
    </svg>
  </button>
</div>

{#if $subscriptions.size > 0}
  <div class="actions">
    <button
      class="btn primary"
      onclick={pushToGitHub}
      disabled={pushing}
      title={githubReady ? 'GitHubリポジトリにsubscriptions.jsonを直接コミット' : 'GitHub設定が未設定です (歯車アイコンから設定)'}
    >
      {#if pushing}
        ⏳ プッシュ中...
      {:else}
        🚀 GitHubへプッシュ
      {/if}
    </button>
    <button class="btn danger" onclick={clearAll}>すべて解除</button>
  </div>

  {#if pushResult}
    <div class="result" class:ok={pushResult.ok} class:error={!pushResult.ok}>
      <strong>{pushResult.ok ? '✓ 成功' : '✗ 失敗'}</strong>
      <pre>{pushResult.message}</pre>
      {#if pushResult.commitUrl}
        <a href={pushResult.commitUrl} target="_blank" rel="noopener">コミットを見る →</a>
      {/if}
      {#if pushResult.debug && pushResult.debug.length > 0}
        <details class="debug">
          <summary>デバッグログ</summary>
          <pre>{pushResult.debug.join('\n')}</pre>
        </details>
      {/if}
      {#if !pushResult.ok}
        <button class="link-btn" style="margin-top: 0.5rem;" onclick={() => (configOpen = true)}>
          ⚙️ 設定画面で接続テストを実行
        </button>
      {/if}
    </div>
  {/if}

  {#if !githubReady}
    <div class="info">
      <p>
        💡 <button class="link-btn" onclick={() => (configOpen = true)}>GitHub連携を設定</button>
        すると、「GitHubへプッシュ」で購読リストをリポジトリに直接コミットできます。
      </p>
    </div>
  {:else}
    <div class="info">
      <p>
        購読リストを <code>{$githubConfig.owner}/{$githubConfig.repo}:{$githubConfig.path}</code>
        にコミットします。次回のActions実行から反映されます。
      </p>
    </div>
  {/if}
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

<GitHubConfigModal open={configOpen} onclose={() => (configOpen = false)} />

<style>
  .header-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1.5rem;
  }
  .header-row .page-title,
  .header-row .page-subtitle {
    margin-bottom: 0;
  }
  .header-row .page-subtitle {
    margin-top: 0.25rem;
  }
  .icon-btn {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--border);
    color: var(--text-1);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: all 0.15s ease;
  }
  .icon-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #fff;
  }
  .actions {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
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
  .btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.1);
    color: #fff;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn.primary {
    background: var(--accent-gradient);
    color: #fff;
    border-color: transparent;
  }
  .btn.primary:hover:not(:disabled) {
    opacity: 0.9;
  }
  .btn.danger {
    color: var(--danger);
  }
  .btn.danger:hover:not(:disabled) {
    background: rgba(248, 113, 113, 0.1);
  }
  .result {
    padding: 0.875rem 1rem;
    border-radius: 12px;
    margin-bottom: 1rem;
    font-size: 0.875rem;
  }
  .result.ok {
    background: rgba(74, 222, 128, 0.1);
    border: 1px solid rgba(74, 222, 128, 0.3);
    color: var(--success);
  }
  .result.error {
    background: rgba(248, 113, 113, 0.1);
    border: 1px solid rgba(248, 113, 113, 0.3);
    color: var(--danger);
  }
  .result strong {
    display: block;
    margin-bottom: 0.375rem;
  }
  .result pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: inherit;
    font-size: 0.8125rem;
    color: var(--text-1);
  }
  .result a {
    display: inline-block;
    margin-top: 0.5rem;
    color: var(--accent-1);
    font-size: 0.8125rem;
  }
  .info {
    padding: 0.875rem 1rem;
    border-radius: 12px;
    background: rgba(102, 126, 234, 0.08);
    border: 1px solid rgba(102, 126, 234, 0.2);
    margin-bottom: 1.5rem;
    font-size: 0.8125rem;
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
  .link-btn {
    color: var(--accent-1);
    text-decoration: underline;
    font: inherit;
    padding: 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 1rem;
  }
</style>
