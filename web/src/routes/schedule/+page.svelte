<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import type { ProgramsData, Program } from '$lib/types';
  import { subscriptions } from '$lib/stores/subscriptions';
  import { fmtJstTime, fmtJstDateOnly } from '$lib/time';

  let allPrograms: Program[] = $state([]);
  let dates: string[] = $state([]);
  let selectedDate = $state<string>('');
  let loading = $state(true);
  let error: string | null = $state(null);
  let subscribedOnly = $state(false);
  let query = $state('');

  onMount(async () => {
    try {
      // programs-latest.json から今日の日付を取得
      const latestRes = await fetch(`${base}/data/programs-latest.json`);
      if (!latestRes.ok) throw new Error(`HTTP ${latestRes.status}`);
      const latest: ProgramsData = await latestRes.json();

      // 今日から7日先までの番組データを並列取得
      // latest.date は YYYY-MM-DD (JST) なので文字列で日付を加算する
      const [baseYear, baseMonth, baseDay] = latest.date.split('-').map(Number);
      const dateList: string[] = [];
      for (let i = 0; i < 7; i++) {
        // UTCで日付加算してからYYYY-MM-DDを得る (タイムゾーンずれ回避)
        const d = new Date(Date.UTC(baseYear, baseMonth - 1, baseDay + i));
        const y = d.getUTCFullYear();
        const m = String(d.getUTCMonth() + 1).padStart(2, '0');
        const day = String(d.getUTCDate()).padStart(2, '0');
        dateList.push(`${y}-${m}-${day}`);
      }

      const results = await Promise.all(
        dateList.map(async (date) => {
          const res = await fetch(`${base}/data/programs-${date}.json`);
          if (!res.ok) return null;
          return (await res.json()) as ProgramsData;
        }),
      );

      const loaded = results.filter((r): r is ProgramsData => r !== null);
      dates = loaded.map((d) => d.date);
      selectedDate = dates[0] ?? '';
      allPrograms = loaded.flatMap((d) => d.programs);
    } catch (e) {
      error = `データ取得失敗: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      loading = false;
    }
  });

  const fmtTime = fmtJstTime;
  const fmtDateShort = fmtJstDateOnly;

  function fmtDuration(sec: number): string {
    const min = Math.floor(sec / 60);
    return `${min}分`;
  }

  let filtered = $derived.by(() => {
    let list = [...allPrograms];

    // 日付フィルタ (検索時は全日、そうでなければ選択日のみ)
    if (!query.trim() && selectedDate) {
      list = list.filter((p) => p.start_time.startsWith(selectedDate));
    }

    // 購読中フィルタ
    if (subscribedOnly) {
      list = list.filter((p) => p.series_id && $subscriptions.has(p.series_id));
    }

    // キーワード検索 (title + subtitle + content)
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter((p) => {
        const text = `${p.title} ${p.subtitle} ${p.content} ${p.series_name}`.toLowerCase();
        return text.includes(q);
      });
    }

    return list.sort((a, b) => a.start_time.localeCompare(b.start_time));
  });

  function toggleSub(seriesId: string) {
    if (seriesId) subscriptions.toggle(seriesId);
  }

  const serviceLabels: Record<string, string> = {
    r1: 'AM',
    r3: 'FM',
  };

  const radikoStationShort: Record<string, string> = {
    ABC: 'ABC', MBS: 'MBS', OBC: 'OBC', FMO: 'FMO', '802': '802',
    CCL: 'CCL', CRK: 'CRK', KISSFMKOBE: 'KISS', KBS: 'KBS',
    RN1: 'RN1', RN2: 'RN2', 'JOAK-FM': 'AK-FM', JOBK: 'BK',
  };

  function getServiceChip(service: string): { label: string; className: string } {
    if (service.startsWith('radiko:')) {
      const sid = service.slice(7);
      return { label: radikoStationShort[sid] ?? sid, className: 'service-radiko' };
    }
    return { label: serviceLabels[service] || service, className: `service-${service}` };
  }
</script>

<svelte:head>
  <title>番組表 | NHK Radio</title>
</svelte:head>

<h1 class="page-title">番組表</h1>
<p class="page-subtitle">
  {query.trim() ? `全${dates.length}日から検索` : '1週間分の番組をキーワード検索'} · {filtered.length}件
</p>

<div class="search-row">
  <input
    type="text"
    bind:value={query}
    placeholder="🔍 番組名・内容で検索 (例: 落語100選、真打、英語)"
    class="search"
  />
</div>

{#if !query.trim() && dates.length > 0}
  <div class="date-tabs">
    {#each dates as d}
      <button
        class="date-tab"
        class:active={selectedDate === d}
        onclick={() => (selectedDate = d)}
      >
        {fmtDateShort(d)}
      </button>
    {/each}
  </div>
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
    <p>該当する番組がありません</p>
  </div>
{:else}
  <div class="list">
    {#each filtered as p (p.id)}
      {@const isSubscribed = p.series_id && $subscriptions.has(p.series_id)}
      {@const chip = getServiceChip(p.service)}
      <div class="item" class:subscribed={isSubscribed}>
        <div class="time">
          {#if query.trim()}
            <div class="time-date">{fmtDateShort(p.start_time.slice(0, 10))}</div>
          {/if}
          <div class="time-start">{fmtTime(p.start_time)}</div>
          <div class="time-duration">{fmtDuration(p.duration_sec)}</div>
        </div>
        <div class="service-chip {chip.className}">{chip.label}</div>
        <div class="body">
          <div class="title">{p.title}</div>
          {#if p.content}
            <div class="content-text">{p.content.slice(0, 120)}{p.content.length > 120 ? '…' : ''}</div>
          {/if}
          {#if p.series_name}
            <div class="series-name">📻 {p.series_name}</div>
          {/if}
        </div>
        {#if p.series_id}
          <button
            class="sub-toggle"
            class:active={isSubscribed}
            onclick={() => toggleSub(p.series_id)}
            aria-label={isSubscribed ? '購読解除' : 'シリーズを購読'}
            title={isSubscribed ? '購読解除' : `${p.series_name} を購読`}
          >
            {isSubscribed ? '✓' : '+'}
          </button>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .search-row {
    margin-bottom: 0.75rem;
  }
  .search {
    width: 100%;
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
  .date-tabs {
    display: flex;
    gap: 0.375rem;
    margin-bottom: 0.75rem;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 0.25rem;
  }
  .date-tab {
    flex-shrink: 0;
    padding: 0.4375rem 0.875rem;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    color: var(--text-2);
    font-size: 0.8125rem;
    font-weight: 500;
    white-space: nowrap;
    transition: all 0.15s ease;
  }
  .date-tab:hover {
    color: var(--text-0);
    background: rgba(255, 255, 255, 0.06);
  }
  .date-tab.active {
    background: var(--accent-gradient);
    color: #fff;
    border-color: transparent;
  }
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
    grid-template-columns: 80px auto 1fr auto;
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
  .time-date {
    font-size: 0.6875rem;
    color: var(--accent-1);
    font-weight: 600;
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
  .service-radiko {
    background: linear-gradient(135deg, #10b981, #047857);
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
  .series-name {
    font-size: 0.6875rem;
    color: var(--accent-1);
    margin-top: 0.25rem;
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
      grid-template-columns: 70px 1fr auto;
    }
    .service-chip {
      display: none;
    }
  }
</style>
