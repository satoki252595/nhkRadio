<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import { base } from '$app/paths';

  let { children } = $props();
</script>

<div class="app">
  <header class="header">
    <div class="header-inner">
      <a href="{base}/" class="brand">
        <span class="brand-icon">📻</span>
        <span class="brand-name">NHK Radio</span>
      </a>
      <nav class="nav">
        <a href="{base}/" class:active={$page.url.pathname === base + '/' || $page.url.pathname === base}>シリーズ</a>
        <a href="{base}/schedule" class:active={$page.url.pathname.startsWith(base + '/schedule')}>今日の番組</a>
        <a href="{base}/subscriptions" class:active={$page.url.pathname.startsWith(base + '/subscriptions')}>購読中</a>
      </nav>
    </div>
  </header>

  <main class="main">
    {@render children()}
  </main>

  <footer class="footer">
    <span>NHKラジオ録音ツール · GitHub Actions + Notion連携</span>
  </footer>
</div>

<style>
  .app {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }
  .header {
    position: sticky;
    top: 0;
    z-index: 10;
    background: rgba(15, 15, 35, 0.85);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }
  .header-inner {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0.875rem 1.25rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    text-decoration: none;
    color: #fff;
    font-weight: 700;
    font-size: 1.125rem;
  }
  .brand-icon {
    font-size: 1.5rem;
  }
  .brand-name {
    letter-spacing: 0.02em;
  }
  .nav {
    display: flex;
    gap: 0.25rem;
  }
  .nav a {
    padding: 0.5rem 1rem;
    border-radius: 999px;
    color: #a0a0b8;
    text-decoration: none;
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.15s ease;
  }
  .nav a:hover {
    color: #fff;
    background: rgba(255, 255, 255, 0.06);
  }
  .nav a.active {
    color: #fff;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  }
  .main {
    flex: 1;
    max-width: 1200px;
    width: 100%;
    margin: 0 auto;
    padding: 1.5rem 1.25rem 3rem;
  }
  .footer {
    max-width: 1200px;
    margin: 0 auto;
    padding: 1.5rem 1.25rem;
    color: #606070;
    font-size: 0.8125rem;
    text-align: center;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }
  @media (max-width: 640px) {
    .nav a {
      padding: 0.375rem 0.75rem;
      font-size: 0.8125rem;
    }
    .brand-name {
      display: none;
    }
  }
</style>
