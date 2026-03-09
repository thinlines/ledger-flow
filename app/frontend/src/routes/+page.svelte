<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api';

  type Health = {
    status: string;
    ledgerVersion?: string;
    hledgerVersion?: string;
  };

  type AppState = {
    initialized: boolean;
    workspacePath: string | null;
    workspaceName: string | null;
    institutions?: Array<{ id: string; displayName: string }>;
    journals?: number;
    csvInbox?: number;
  };

  let health: Health | null = null;
  let state: AppState | null = null;
  let error = '';
  let healthWarning = '';

  let nextActionTitle = 'Start with setup';
  let nextActionCopy = 'Create a workspace so the app can manage your books through the UI.';
  let nextActionHref = '/setup';
  let nextActionLabel = 'Open setup';

  $: inboxCount = state?.csvInbox ?? 0;
  $: journalCount = state?.journals ?? 0;
  $: institutionCount = state?.institutions?.length ?? 0;

  $: {
    if (!state?.initialized) {
      nextActionTitle = 'Start with setup';
      nextActionCopy = 'Create a workspace so Ledger Flow can manage your finances from the app.';
      nextActionHref = '/setup';
      nextActionLabel = 'Open setup';
    } else if (inboxCount > 0) {
      nextActionTitle = 'Import the latest statement activity';
      nextActionCopy = 'Statements are already waiting. Preview them, confirm what is new, and keep the picture current.';
      nextActionHref = '/import';
      nextActionLabel = 'Open import';
    } else if (journalCount === 0) {
      nextActionTitle = 'Bring in your first statement';
      nextActionCopy = 'Your workspace is ready, but there is no history loaded yet. Start with an import to populate the dashboard.';
      nextActionHref = '/import';
      nextActionLabel = 'Import activity';
    } else {
      nextActionTitle = 'Keep categorization sharp';
      nextActionCopy = 'Review uncategorized activity and save repeat decisions as reusable automation rules.';
      nextActionHref = '/unknowns';
      nextActionLabel = 'Open categorization';
    }
  }

  onMount(async () => {
    try {
      state = await apiGet<AppState>('/api/app/state');
    } catch (e) {
      error = String(e);
      return;
    }

    try {
      health = await apiGet<Health>('/api/health');
    } catch (_e) {
      healthWarning = 'Version checks unavailable';
    }
  });
</script>

<section class="view-card hero home-hero">
  <p class="eyebrow">Overview</p>
  <h2 class="page-title page-title-xl">Keep your finances current</h2>
  <p class="subtitle hero-subtitle">
    A clean daily workspace for imports, categorization, and ongoing financial upkeep.
  </p>
  <div class="hero-actions">
    {#if state?.initialized}
      <a class="btn btn-primary" href={nextActionHref}>{nextActionLabel}</a>
      {#if nextActionHref !== '/import'}
        <a class="btn btn-subtle" href="/import">Import</a>
      {/if}
      {#if nextActionHref !== '/unknowns'}
        <a class="btn btn-subtle" href="/unknowns">Categorize</a>
      {/if}
      {#if nextActionHref !== '/rules'}
        <a class="btn btn-subtle" href="/rules">Automation</a>
      {/if}
    {:else}
      <a class="btn btn-primary" href="/setup">Create Workspace</a>
    {/if}
  </div>
</section>

{#if error}
  <section class="view-card"><p class="error-text">{error}</p></section>
{:else}
  {#if state?.initialized}
    <section class="view-card stat-strip">
      <article class="stat">
        <p class="stat-label">Statements</p>
        <p class="stat-value">{inboxCount}</p>
        <p class="stat-note">{inboxCount > 0 ? 'Waiting to import' : 'Inbox is clear'}</p>
      </article>

      <article class="stat">
        <p class="stat-label">Institutions</p>
        <p class="stat-value">{institutionCount}</p>
        <p class="stat-note">{institutionCount > 0 ? 'Configured' : 'Needs setup'}</p>
      </article>

      <article class="stat">
        <p class="stat-label">History</p>
        <p class="stat-value">{journalCount}</p>
        <p class="stat-note">{journalCount === 1 ? 'Year loaded' : 'Years loaded'}</p>
      </article>
    </section>

    <section class="home-grid">
      <article class="view-card primary-panel">
        <p class="eyebrow">Next Up</p>
        <h3 class="primary-title">{nextActionTitle}</h3>
        <p class="primary-copy">{nextActionCopy}</p>
        <a class="btn btn-primary" href={nextActionHref}>{nextActionLabel}</a>
      </article>

      <article class="view-card secondary-panel">
        <p class="eyebrow">Workflows</p>
        <nav class="link-list" aria-label="Home workflows">
          <a class="link-row" href="/import">
            <span>Import activity</span>
            <small>Bring in the latest statements</small>
          </a>
          <a class="link-row" href="/unknowns">
            <span>Review categories</span>
            <small>Resolve uncategorized transactions</small>
          </a>
          <a class="link-row" href="/rules">
            <span>Automation rules</span>
            <small>Save repeat decisions once</small>
          </a>
        </nav>

        <div class="workspace-meta">
          <p class="workspace-name">{state.workspaceName}</p>
          <p class="workspace-path">{state.workspacePath}</p>
          <div class="workspace-pills">
            <span class="pill ok">Ready</span>
            {#if health}
              <span class="pill ok">Connected</span>
            {:else if healthWarning}
              <span class="pill warn">{healthWarning}</span>
            {/if}
          </div>
        </div>
      </article>
    </section>
  {:else}
    <section class="home-grid">
      <article class="view-card primary-panel">
        <p class="eyebrow">Get Started</p>
        <h3 class="primary-title">Create your workspace once</h3>
        <p class="primary-copy">
          Setup should feel like using a modern finance app, not assembling folders by hand. The UI handles the structure for you.
        </p>
        <a class="btn btn-primary" href="/setup">Open setup</a>
      </article>

      <article class="view-card secondary-panel">
        <p class="eyebrow">Principle</p>
        <p class="workspace-name">Open underneath when needed</p>
        <p class="workspace-path">
          The plain-text model is still valuable for portability and control, but it should remain optional knowledge for most users.
        </p>
      </article>
    </section>
  {/if}
{/if}

<style>
  .home-hero {
    padding: 1.5rem;
  }

  .hero-actions {
    margin-top: 1rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }

  .page-title-xl {
    font-size: clamp(2rem, 4vw, 3.2rem);
    line-height: 0.98;
    max-width: 11ch;
  }

  .hero-subtitle {
    max-width: 40rem;
    font-size: 1rem;
    line-height: 1.6;
  }

  .btn-subtle {
    background: rgba(255, 255, 255, 0.62);
    border-color: rgba(15, 95, 136, 0.12);
  }

  .stat-strip {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0;
    padding: 0.35rem 0;
  }

  .stat {
    padding: 1rem 1.2rem;
  }

  .stat + .stat {
    border-left: 1px solid rgba(15, 95, 136, 0.08);
  }

  .stat-label {
    margin: 0;
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted-foreground);
    font-weight: 700;
  }

  .stat-value {
    margin: 0.5rem 0 0.2rem;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 2.2rem;
    line-height: 1;
  }

  .stat-note {
    margin: 0;
    color: var(--muted-foreground);
  }

  .home-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.85fr);
    gap: 1rem;
    align-items: start;
  }

  .primary-panel {
    padding: 1.35rem 1.4rem;
  }

  .primary-title {
    margin: 0;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.7rem;
    line-height: 1.05;
    max-width: 14ch;
  }

  .primary-copy {
    margin: 0.75rem 0 1.2rem;
    color: var(--muted-foreground);
    line-height: 1.65;
    max-width: 38rem;
  }

  .secondary-panel {
    display: grid;
    gap: 1.2rem;
  }

  .link-list {
    display: grid;
  }

  .link-row {
    display: grid;
    gap: 0.18rem;
    text-decoration: none;
    color: var(--foreground);
    padding: 0.9rem 0;
    border-top: 1px solid rgba(15, 95, 136, 0.08);
  }

  .link-row:first-child {
    border-top: 0;
    padding-top: 0.2rem;
  }

  .link-row span {
    font-weight: 700;
  }

  .link-row small {
    color: var(--muted-foreground);
    font-size: 0.9rem;
  }

  .link-row:hover span {
    color: var(--brand-strong);
  }

  .workspace-meta {
    border-top: 1px solid rgba(15, 95, 136, 0.08);
    padding-top: 1rem;
  }

  .workspace-name {
    margin: 0;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.1rem;
  }

  .workspace-path {
    margin: 0.35rem 0 0;
    color: var(--muted-foreground);
    font-size: 0.92rem;
    line-height: 1.55;
    word-break: break-word;
  }

  .workspace-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-top: 0.9rem;
  }

  @media (max-width: 900px) {
    .stat-strip,
    .home-grid {
      grid-template-columns: 1fr;
    }

    .stat + .stat {
      border-left: 0;
      border-top: 1px solid rgba(15, 95, 136, 0.08);
    }

    .page-title-xl {
      max-width: none;
    }
  }
</style>
