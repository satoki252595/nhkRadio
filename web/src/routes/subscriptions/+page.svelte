<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import type { SeriesIndex, Series } from '$lib/types';
  import { subscriptions } from '$lib/stores/subscriptions';
  import SeriesCard from '$lib/components/SeriesCard.svelte';
  import { githubSyncConfig } from '$lib/sync/config';
  import { createGitHubSyncAdapter, type GitHubSyncConfig } from '$lib/sync/github';

  let allSeries: Series[] = $state([]);
  let loading = $state(true);
  let copied = $state(false);

  let showSyncPanel = $state(false);
  let syncing = $state(false);
  let syncMessage = $state<{ kind: 'ok' | 'err'; text: string } | null>(null);
  let form = $state<GitHubSyncConfig>({
    token: '',
    owner: '',
    repo: '',
    path: 'data/subscriptions.json',
    branch: 'main',
  });

  $effect(() => {
    const saved = $githubSyncConfig;
    if (saved) {
      form = {
        token: saved.token,
        owner: saved.owner,
        repo: saved.repo,
        path: saved.path ?? 'data/subscriptions.json',
        branch: saved.branch ?? 'main',
      };
    }
  });

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

  function saveSyncConfig() {
    if (!form.token || !form.owner || !form.repo) {
      syncMessage = { kind: 'err', text: 'token / owner / repo は必須です' };
      return;
    }
    githubSyncConfig.save({ ...form });
    syncMessage = { kind: 'ok', text: '設定を保存しました（ブラウザに保存）' };
  }

  function clearSyncConfig() {
    githubSyncConfig.clear();
    form = { token: '', owner: '', repo: '', path: 'data/subscriptions.json', branch: 'main' };
    syncMessage = { kind: 'ok', text: '設定を削除しました' };
  }

  async function pushToGitHub() {
    if (!$githubSyncConfig) {
      syncMessage = { kind: 'err', text: '先に GitHub 設定を保存してください' };
      return;
    }
    syncing = true;
    syncMessage = null;
    try {
      const adapter = createGitHubSyncAdapter($githubSyncConfig);
      await subscriptions.pushTo(adapter);
      syncMessage = { kind: 'ok', text: `✓ GitHub にプッシュしました (${$subscriptions.size}件)` };
    } catch (e) {
      syncMessage = { kind: 'err', text: `プッシュ失敗: ${(e as Error).message}` };
    } finally {
      syncing = false;
    }
  }

  async function pullFromGitHub() {
    if (!$githubSyncConfig) {
      syncMessage = { kind: 'err', text: '先に GitHub 設定を保存してください' };
      return;
    }
    if (!confirm('GitHub の内容でローカルを上書きします。よろしいですか？')) return;
    syncing = true;
    syncMessage = null;
    try {
      const adapter = createGitHubSyncAdapter($githubSyncConfig);
      const ok = await subscriptions.pullFrom(adapter);
      syncMessage = ok
        ? { kind: 'ok', text: `✓ GitHub から取得しました (${$subscriptions.size}件)` }
        : { kind: 'err', text: 'リモートに購読ファイルがありません' };
    } catch (e) {
      syncMessage = { kind: 'err', text: `取得失敗: ${(e as Error).message}` };
    } finally {
      syncing = false;
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
    <button class="btn primary" onclick={pushToGitHub} disabled={syncing}>
      {syncing ? '⏳ 同期中...' : '☁ GitHubへプッシュ'}
    </button>
    <button class="btn" onclick={pullFromGitHub} disabled={syncing}>⬇ GitHubから取得</button>
    <button class="btn" onclick={() => (showSyncPanel = !showSyncPanel)}>⚙ 同期設定</button>
    <button class="btn" onclick={copyExport}>
      {copied ? '✓ コピー済み' : '📋 JSONをコピー'}
    </button>
    <button class="btn" onclick={downloadExport}>⬇ JSONダウンロード</button>
    <button class="btn danger" onclick={clearAll}>すべて解除</button>
  </div>
{:else}
  <div class="actions">
    <button class="btn" onclick={pullFromGitHub} disabled={syncing || !$githubSyncConfig}>
      ⬇ GitHubから取得
    </button>
    <button class="btn" onclick={() => (showSyncPanel = !showSyncPanel)}>⚙ 同期設定</button>
  </div>
{/if}

{#if syncMessage}
  <div class="msg {syncMessage.kind}">{syncMessage.text}</div>
{/if}

{#if showSyncPanel}
  <div class="sync-panel">
    <h3>GitHub 同期設定</h3>
    <p class="hint">
      Fine-grained PAT（<code>Contents: Read and write</code> 権限）を発行し、対象リポジトリを指定してください。
      設定はこのブラウザの localStorage にのみ保存されます。
    </p>
    <div class="form-row">
      <label>Personal Access Token
        <input type="password" bind:value={form.token} placeholder="github_pat_..." autocomplete="off" />
      </label>
    </div>
    <div class="form-grid">
      <label>Owner
        <input type="text" bind:value={form.owner} placeholder="your-name" />
      </label>
      <label>Repo
        <input type="text" bind:value={form.repo} placeholder="nhkRadio" />
      </label>
      <label>Branch
        <input type="text" bind:value={form.branch} placeholder="main" />
      </label>
      <label>Path
        <input type="text" bind:value={form.path} placeholder="data/subscriptions.json" />
      </label>
    </div>
    <div class="form-actions">
      <button class="btn primary" onclick={saveSyncConfig}>設定を保存</button>
      {#if $githubSyncConfig}
        <button class="btn danger" onclick={clearSyncConfig}>設定を削除</button>
      {/if}
    </div>
  </div>
{/if}

{#if $subscriptions.size > 0}
  <div class="info">
    <p>
      「GitHubへプッシュ」でリポジトリの <code>{form.path || 'data/subscriptions.json'}</code> を更新すると、
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
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .msg {
    padding: 0.625rem 0.875rem;
    border-radius: 10px;
    font-size: 0.875rem;
    margin-bottom: 1rem;
  }
  .msg.ok {
    background: rgba(74, 222, 128, 0.08);
    border: 1px solid rgba(74, 222, 128, 0.25);
    color: #86efac;
  }
  .msg.err {
    background: rgba(248, 113, 113, 0.08);
    border: 1px solid rgba(248, 113, 113, 0.25);
    color: #fca5a5;
  }
  .sync-panel {
    padding: 1rem 1.125rem;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border);
    margin-bottom: 1.25rem;
  }
  .sync-panel h3 {
    margin: 0 0 0.5rem;
    font-size: 1rem;
  }
  .sync-panel .hint {
    font-size: 0.8125rem;
    color: var(--text-2);
    margin: 0 0 0.875rem;
  }
  .sync-panel .hint code {
    padding: 0.0625rem 0.3125rem;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.08);
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 0.8125em;
  }
  .form-row,
  .form-grid {
    margin-bottom: 0.75rem;
  }
  .form-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 0.625rem;
  }
  .sync-panel label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.75rem;
    color: var(--text-2);
  }
  .sync-panel input {
    padding: 0.5rem 0.625rem;
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid var(--border);
    color: var(--text-1);
    font-size: 0.875rem;
    font-family: inherit;
  }
  .sync-panel input:focus {
    outline: none;
    border-color: rgba(102, 126, 234, 0.5);
  }
  .form-actions {
    display: flex;
    gap: 0.5rem;
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
