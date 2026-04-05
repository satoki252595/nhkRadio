<script lang="ts">
  import { githubConfig } from '$lib/stores/githubConfig';
  import { diagnose, type DiagnosticResult } from '$lib/github';

  interface Props {
    open: boolean;
    onclose: () => void;
  }

  let { open, onclose }: Props = $props();

  let token = $state($githubConfig.token);
  let owner = $state($githubConfig.owner);
  let repo = $state($githubConfig.repo);
  let branch = $state($githubConfig.branch);
  let path = $state($githubConfig.path);

  let testing = $state(false);
  let diag: DiagnosticResult | null = $state(null);

  $effect(() => {
    if (open) {
      token = $githubConfig.token;
      owner = $githubConfig.owner;
      repo = $githubConfig.repo;
      branch = $githubConfig.branch;
      path = $githubConfig.path;
      diag = null;
    }
  });

  function save() {
    githubConfig.set({
      token: token.trim(),
      owner: owner.trim(),
      repo: repo.trim(),
      branch: branch.trim() || 'main',
      path: path.trim() || 'data/subscriptions.json',
    });
    onclose();
  }

  async function testConnection() {
    testing = true;
    diag = null;
    try {
      diag = await diagnose({
        token: token.trim(),
        owner: owner.trim(),
        repo: repo.trim(),
        branch: branch.trim() || 'main',
        path: path.trim() || 'data/subscriptions.json',
      });
    } finally {
      testing = false;
    }
  }

  function handleBackdrop(e: MouseEvent) {
    if (e.target === e.currentTarget) onclose();
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onclose();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
  <div
    class="backdrop"
    onclick={handleBackdrop}
    onkeydown={(e) => e.key === 'Enter' && handleBackdrop(e as unknown as MouseEvent)}
    role="presentation"
  >
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="gh-title">
      <div class="head">
        <h2 id="gh-title">GitHub 連携設定</h2>
        <button class="close" onclick={onclose} aria-label="閉じる">✕</button>
      </div>

      <div class="body">
        <p class="hint">
          Personal Access Token を発行して、リポジトリに購読リストを直接コミットできます。
        </p>

        <label class="field">
          <span>Personal Access Token</span>
          <input
            type="password"
            bind:value={token}
            placeholder="github_pat_... または ghp_..."
            autocomplete="off"
          />
          <a
            href="https://github.com/settings/personal-access-tokens/new"
            target="_blank"
            rel="noopener"
            class="link"
          >
            Fine-grained tokenを発行 →
          </a>
        </label>

        <div class="row">
          <label class="field">
            <span>Owner (ユーザー名)</span>
            <input type="text" bind:value={owner} placeholder="satoki252595" autocomplete="off" />
          </label>
          <label class="field">
            <span>Repository</span>
            <input type="text" bind:value={repo} placeholder="nhkRadio" autocomplete="off" />
          </label>
        </div>

        <div class="row">
          <label class="field">
            <span>Branch</span>
            <input type="text" bind:value={branch} placeholder="main" autocomplete="off" />
          </label>
          <label class="field">
            <span>ファイルパス</span>
            <input
              type="text"
              bind:value={path}
              placeholder="data/subscriptions.json"
              autocomplete="off"
            />
          </label>
        </div>

        <div class="warn">
          <strong>⚠️ トークン権限の確認</strong>
          <ul>
            <li>
              <strong>Fine-grained token</strong>: Repository access で対象リポジトリを選択し、
              Permissions → Contents を「Read and write」に設定
            </li>
            <li><strong>Classic token</strong>: <code>repo</code> スコープが必要</li>
          </ul>
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

      <div class="foot">
        <button class="btn ghost" onclick={onclose}>キャンセル</button>
        <button class="btn ghost" onclick={testConnection} disabled={testing}>
          {testing ? '⏳ テスト中...' : '🔍 接続テスト'}
        </button>
        <button class="btn primary" onclick={save}>保存</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(6px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
    padding: 1rem;
  }
  .modal {
    width: 100%;
    max-width: 560px;
    max-height: 90vh;
    overflow-y: auto;
    background: var(--bg-1);
    border: 1px solid var(--border-strong);
    border-radius: 16px;
    box-shadow: 0 20px 80px rgba(0, 0, 0, 0.5);
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1.125rem 1.25rem;
    border-bottom: 1px solid var(--border);
  }
  .head h2 {
    font-size: 1.0625rem;
    font-weight: 600;
  }
  .close {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    color: var(--text-2);
    font-size: 0.875rem;
  }
  .close:hover {
    background: rgba(255, 255, 255, 0.08);
    color: #fff;
  }
  .body {
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .hint {
    margin: 0;
    font-size: 0.8125rem;
    color: var(--text-2);
  }
  .row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }
  .field span {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--text-1);
    letter-spacing: 0.03em;
  }
  .field input {
    padding: 0.5625rem 0.75rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: rgba(0, 0, 0, 0.25);
    color: var(--text-0);
    font-size: 0.875rem;
    outline: none;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  }
  .field input:focus {
    border-color: var(--accent-1);
  }
  .link {
    font-size: 0.75rem;
    color: var(--accent-1);
    text-decoration: none;
    align-self: flex-start;
  }
  .link:hover {
    text-decoration: underline;
  }
  .warn {
    padding: 0.875rem;
    border-radius: 10px;
    background: rgba(255, 193, 7, 0.08);
    border: 1px solid rgba(255, 193, 7, 0.2);
    font-size: 0.75rem;
    color: var(--text-1);
  }
  .warn strong {
    display: block;
    margin-bottom: 0.375rem;
  }
  .warn ul {
    margin: 0;
    padding-left: 1.25rem;
  }
  .warn li {
    margin-bottom: 0.25rem;
    line-height: 1.5;
  }
  .warn code {
    padding: 0.0625rem 0.3125rem;
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.08);
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 0.9em;
  }
  .foot {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
    padding: 1rem 1.25rem;
    border-top: 1px solid var(--border);
  }
  .btn {
    padding: 0.5rem 1.125rem;
    border-radius: 10px;
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.15s ease;
  }
  .btn.ghost {
    color: var(--text-1);
    background: transparent;
  }
  .btn.ghost:hover {
    background: rgba(255, 255, 255, 0.06);
    color: #fff;
  }
  .btn.primary {
    background: var(--accent-gradient);
    color: #fff;
  }
  .btn.primary:hover {
    opacity: 0.9;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .diag {
    padding: 0.875rem;
    border-radius: 10px;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid var(--border);
    font-size: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .diag > strong {
    font-size: 0.8125rem;
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
    color: var(--text-0);
    margin-bottom: 0.1875rem;
  }
  .diag-step-detail {
    color: var(--text-1);
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 0.6875rem;
    line-height: 1.5;
  }
  @media (max-width: 560px) {
    .row {
      grid-template-columns: 1fr;
    }
    .foot {
      flex-wrap: wrap;
    }
  }
</style>
