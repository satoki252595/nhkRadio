<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import type { SeriesIndex, Series, ProgramsData, Program } from '$lib/types';
  import { subscriptions, keywords } from '$lib/stores/subscriptions';
  import SeriesCard from '$lib/components/SeriesCard.svelte';
  import { githubSyncConfig } from '$lib/sync/config';
  import { createGitHubSyncAdapter, type GitHubSyncConfig } from '$lib/sync/github';
  import { diagnose, type DiagnosticResult } from '$lib/sync/diagnose';
  import { fmtJstDateTime } from '$lib/time';

  let allSeries: Series[] = $state([]);
  let upcomingPrograms: Program[] = $state([]);
  let loading = $state(true);

  let showSyncPanel = $state(false);
  let syncing = $state(false);
  let diagnosing = $state(false);
  let diag = $state<DiagnosticResult | null>(null);
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

      // 番組データをロード (直近7日)
      const latestRes = await fetch(`${base}/data/programs-latest.json`);
      if (latestRes.ok) {
        const latest: ProgramsData = await latestRes.json();
        const [by, bm, bd] = latest.date.split('-').map(Number);
        const dateList: string[] = [];
        for (let i = 0; i < 7; i++) {
          const d = new Date(Date.UTC(by, bm - 1, bd + i));
          dateList.push(
            `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`,
          );
        }
        const results = await Promise.all(
          dateList.map(async (date) => {
            const r = await fetch(`${base}/data/programs-${date}.json`);
            if (!r.ok) return null;
            return (await r.json()) as ProgramsData;
          }),
        );
        upcomingPrograms = results
          .filter((r): r is ProgramsData => r !== null)
          .flatMap((d) => d.programs);
      }
    } finally {
      loading = false;
    }
  });

  let subscribedSeries = $derived(
    allSeries.filter((s) => $subscriptions.has(s.series_id)),
  );

  /** NHK同時配信局 (NHK本家がある場合に除外対象) */
  const NHK_SIMULCAST = new Set(['JOBK', 'JOAK', 'JOBK-FM', 'JOAK-FM']);

  /** サービスの優先度 (大きいほど優先) */
  function servicePriority(service: string): number {
    if (service === 'r1' || service === 'r3') return 100;
    if (service.startsWith('radiko:')) {
      const station = service.split(':')[1];
      return NHK_SIMULCAST.has(station) ? 10 : 50;
    }
    return 0;
  }

  /** タイトルを正規化 (先頭の[局名]除去、空白統一) */
  function normalizeTitle(title: string): string {
    return title.replace(/^\[[^\]]+\]\s*/, '').replace(/[\s\u3000]+/g, ' ').trim();
  }

  /** 同時刻・同タイトルの番組を重複排除 (優先度の高い方を残す) */
  function dedupePrograms(programs: Program[]): Program[] {
    const byKey = new Map<string, Program>();
    for (const p of programs) {
      const norm = normalizeTitle(p.title);
      // NHK: (start_time, title) で統合、Radiko: (start_time, title, station) で分離
      const station = p.service.startsWith('radiko:') ? p.service.split(':')[1] : '';
      const key = `${p.start_time}|${norm}|${station}`;
      const existing = byKey.get(key);
      if (!existing || servicePriority(p.service) > servicePriority(existing.service)) {
        byKey.set(key, p);
      }
    }
    return [...byKey.values()];
  }

  // 購読中シリーズ+キーワードに一致する今後の番組 (録音予定)
  let upcomingRecordings = $derived.by(() => {
    const subIds = $subscriptions;
    const kws = $keywords;
    const filtered = upcomingPrograms
      .filter((p) => {
        if (p.series_id && subIds.has(p.series_id)) return true;
        if (kws.length > 0) {
          const text = `${p.title} ${p.subtitle} ${p.content}`.toLowerCase();
          return kws.some((kw) => text.includes(kw.toLowerCase()));
        }
        return false;
      });
    return dedupePrograms(filtered)
      .sort((a, b) => a.start_time.localeCompare(b.start_time));
  });

  const fmtDateTime = fmtJstDateTime;

  function fmtDuration(sec: number): string {
    return `${Math.floor(sec / 60)}分`;
  }

  function clearAll() {
    if (confirm('すべての購読とキーワードを解除しますか？')) {
      subscriptions.clear();
    }
  }

  let kwInput = $state('');

  function addKeyword() {
    const v = kwInput.trim();
    if (!v) return;
    keywords.add(v);
    kwInput = '';
  }

  function removeKeyword(kw: string) {
    keywords.remove(kw);
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

  async function testConnection() {
    if (!form.token || !form.owner || !form.repo) {
      syncMessage = { kind: 'err', text: 'token / owner / repo は必須です' };
      return;
    }
    diagnosing = true;
    diag = null;
    try {
      diag = await diagnose(form);
    } finally {
      diagnosing = false;
    }
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

<section class="keywords-section">
  <h2 class="section-title">キーワード録音</h2>
  <p class="section-hint">
    番組名・サブタイトル・内容にキーワードが含まれる番組を自動録音します。
    <br />
    例: <code>落語100選</code>, <code>真打</code>, <code>朗読</code> など(深夜便の特集コーナーにも対応)
  </p>
  <div class="keyword-input">
    <input
      type="text"
      bind:value={kwInput}
      placeholder="キーワードを入力 (Enterで追加)"
      onkeydown={(e) => e.key === 'Enter' && addKeyword()}
    />
    <button class="btn primary" onclick={addKeyword} disabled={!kwInput.trim()}>追加</button>
  </div>
  {#if $keywords.length > 0}
    <div class="keyword-tags">
      {#each $keywords as kw}
        <span class="keyword-tag">
          {kw}
          <button
            class="keyword-remove"
            onclick={() => removeKeyword(kw)}
            aria-label={`${kw}を削除`}
          >
            ✕
          </button>
        </span>
      {/each}
    </div>
  {:else}
    <p class="keyword-empty">まだキーワードがありません</p>
  {/if}
</section>

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
      <button class="btn" onclick={testConnection} disabled={diagnosing}>
        {diagnosing ? '⏳ テスト中...' : '🔍 接続テスト'}
      </button>
      {#if $githubSyncConfig}
        <button class="btn danger" onclick={clearSyncConfig}>設定を削除</button>
      {/if}
    </div>
    {#if diag}
      <div class="diag">
        <strong>{diag.ok ? '✓ 接続テスト成功' : '✗ 接続テスト失敗'}</strong>
        {#each diag.steps as s}
          <div class="diag-step" class:ng={!s.ok}>
            <div class="diag-step-label">{s.ok ? '✓' : '✗'} {s.step}</div>
            <div class="diag-step-detail">{s.detail}</div>
          </div>
        {/each}
      </div>
    {/if}
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
{:else if subscribedSeries.length === 0 && $keywords.length === 0}
  <div class="empty">
    <div class="empty-icon">📻</div>
    <p>まだ購読していません</p>
    <p style="font-size: 0.875rem; margin-top: 0.5rem;">
      シリーズページから気になる番組を購読してください
    </p>
  </div>
{:else}
  {#if upcomingRecordings.length > 0}
    <section class="upcoming-section">
      <h2 class="section-title">録音予定 ({upcomingRecordings.length}件 / 7日間)</h2>
      <div class="upcoming-list">
        {#each upcomingRecordings as p (p.id)}
          <div class="upcoming-item">
            <div class="upcoming-time">
              <span class="upcoming-date">{fmtDateTime(p.start_time)}</span>
              <span class="upcoming-dur">{fmtDuration(p.duration_sec)}</span>
            </div>
            <div class="upcoming-body">
              <div class="upcoming-title">{p.title}</div>
              {#if p.series_name}
                <span class="upcoming-series">{p.series_name}</span>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    </section>
  {:else}
    <div class="info">
      <p>直近7日間の録音予定はありません。番組データが更新されるとここに表示されます。</p>
    </div>
  {/if}

  {#if subscribedSeries.length > 0}
    <h2 class="section-title" style="margin-top: 2rem;">購読中のシリーズ ({subscribedSeries.length}件)</h2>
    <div class="grid">
      {#each subscribedSeries as series (series.series_id)}
        <SeriesCard {series} />
      {/each}
    </div>
  {/if}
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
    flex-wrap: wrap;
  }
  .diag {
    margin-top: 0.875rem;
    padding: 0.875rem;
    border-radius: 10px;
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid rgba(255, 255, 255, 0.08);
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    font-size: 0.8125rem;
  }
  .diag > strong {
    font-size: 0.875rem;
  }
  .diag-step {
    padding: 0.5rem 0.625rem;
    border-radius: 6px;
    background: rgba(74, 222, 128, 0.08);
    border: 1px solid rgba(74, 222, 128, 0.2);
  }
  .diag-step.ng {
    background: rgba(248, 113, 113, 0.08);
    border-color: rgba(248, 113, 113, 0.25);
  }
  .diag-step-label {
    font-weight: 600;
    margin-bottom: 0.1875rem;
  }
  .diag-step-detail {
    color: var(--text-1);
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 0.6875rem;
    line-height: 1.5;
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
  .keywords-section {
    margin: 1.5rem 0;
    padding: 1.125rem 1.25rem;
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border);
  }
  .section-title {
    margin: 0 0 0.375rem;
    font-size: 1rem;
    font-weight: 600;
  }
  .section-hint {
    margin: 0 0 0.875rem;
    font-size: 0.8125rem;
    color: var(--text-2);
    line-height: 1.55;
  }
  .section-hint code {
    padding: 0.0625rem 0.3125rem;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.08);
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 0.9em;
    color: var(--text-1);
  }
  .keyword-input {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }
  .keyword-input input {
    flex: 1;
    padding: 0.5rem 0.875rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: rgba(0, 0, 0, 0.25);
    color: var(--text-0);
    font-size: 0.875rem;
    outline: none;
  }
  .keyword-input input:focus {
    border-color: var(--accent-1);
  }
  .keyword-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .keyword-tag {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.3125rem 0.5rem 0.3125rem 0.75rem;
    border-radius: 999px;
    background: linear-gradient(135deg, rgba(102, 126, 234, 0.25), rgba(118, 75, 162, 0.2));
    border: 1px solid rgba(102, 126, 234, 0.35);
    color: var(--text-0);
    font-size: 0.8125rem;
    font-weight: 500;
  }
  .keyword-remove {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.3);
    color: var(--text-1);
    font-size: 0.6875rem;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
  }
  .keyword-remove:hover {
    background: var(--danger);
    color: #fff;
  }
  .keyword-empty {
    margin: 0;
    font-size: 0.8125rem;
    color: var(--text-2);
  }
  .upcoming-section {
    margin-bottom: 1.5rem;
  }
  .upcoming-list {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
    max-height: 480px;
    overflow-y: auto;
  }
  .upcoming-item {
    display: flex;
    gap: 0.875rem;
    align-items: center;
    padding: 0.625rem 0.875rem;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border);
    transition: background 0.15s;
  }
  .upcoming-item:hover {
    background: rgba(255, 255, 255, 0.05);
  }
  .upcoming-time {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    flex-shrink: 0;
    min-width: 100px;
  }
  .upcoming-date {
    font-size: 0.8125rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--text-0);
  }
  .upcoming-dur {
    font-size: 0.6875rem;
    color: var(--text-2);
  }
  .upcoming-body {
    min-width: 0;
  }
  .upcoming-title {
    font-size: 0.8125rem;
    font-weight: 500;
    color: var(--text-0);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .upcoming-series {
    font-size: 0.6875rem;
    color: var(--accent-1);
  }
</style>
