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

  type ActionLink = {
    href: string;
    label: string;
  };

  let health: Health | null = null;
  let state: AppState | null = null;
  let error = '';
  let healthWarning = '';

  let heroEyebrow = 'Get Started';
  let heroTitle = 'Create your workspace';
  let heroCopy = 'Start by creating a workspace so Ledger Flow can manage your finances through the app.';
  let primaryAction: ActionLink = { href: '/setup', label: 'Create workspace' };
  let secondaryActions: ActionLink[] = [{ href: '/setup#existing', label: 'Use existing workspace' }];

  $: inboxCount = state?.csvInbox ?? 0;
  $: journalCount = state?.journals ?? 0;
  $: institutionCount = state?.institutions?.length ?? 0;

  $: {
    if (!state?.initialized) {
      heroEyebrow = 'Get Started';
      heroTitle = 'Create your workspace';
      heroCopy = 'Start with a new workspace. If you already have one, connect it instead.';
      primaryAction = { href: '/setup', label: 'Create workspace' };
      secondaryActions = [{ href: '/setup#existing', label: 'Use existing workspace' }];
    } else if (inboxCount > 0) {
      heroEyebrow = 'Import';
      heroTitle = inboxCount === 1 ? 'One statement is waiting' : `${inboxCount} statements are waiting`;
      heroCopy = 'Bring in the latest activity first. After that, review any categories that still need attention.';
      primaryAction = { href: '/import', label: 'Import statements' };
      secondaryActions = [{ href: '/unknowns', label: 'Review categories' }];
    } else if (journalCount === 0) {
      heroEyebrow = 'First Import';
      heroTitle = 'Bring in your first statement';
      heroCopy = 'Your workspace is ready. Import a statement to start building account history and make the app useful day to day.';
      primaryAction = { href: '/import', label: 'Import activity' };
      secondaryActions = [{ href: '/setup', label: 'Review setup' }];
    } else {
      heroEyebrow = 'Review';
      heroTitle = 'Keep recent activity clean';
      heroCopy = 'Nothing is waiting to import. Review uncategorized activity and save repeat decisions as automation rules.';
      primaryAction = { href: '/unknowns', label: 'Review categories' };
      secondaryActions = [
        { href: '/import', label: 'Import activity' },
        { href: '/rules', label: 'Automation rules' }
      ];
    }
  }

  onMount(async () => {
    try {
      state = await apiGet<AppState>('/api/app/state');
    } catch (e) {
      error = String(e);
      return;
    }

    if (!state?.initialized) return;

    try {
      health = await apiGet<Health>('/api/health');
    } catch (_e) {
      healthWarning = 'Version checks unavailable';
    }
  });
</script>

<section class="view-card hero home-hero">
  <p class="eyebrow">{heroEyebrow}</p>
  <h2 class="page-title page-title-xl">{heroTitle}</h2>
  <p class="subtitle hero-subtitle">{heroCopy}</p>
  <div class="hero-actions">
    <a class="btn btn-primary" href={primaryAction.href}>{primaryAction.label}</a>
    {#each secondaryActions as action}
      <a class="text-link" href={action.href}>{action.label}</a>
    {/each}
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

    <section class="view-card workspace-strip">
      <div>
        <p class="eyebrow">Workspace</p>
        <p class="workspace-name">{state.workspaceName}</p>
        <p class="workspace-path">{state.workspacePath}</p>
      </div>

      <div class="workspace-pills">
        <span class="pill ok">Ready</span>
        {#if health}
          <span class="pill ok">Connected</span>
        {:else if healthWarning}
          <span class="pill warn">{healthWarning}</span>
        {/if}
      </div>
    </section>
  {:else}
    <section class="view-card minimal-note">
      <p class="minimal-title">The default path is simple: create a workspace, import a statement, then review any missing categories.</p>
      <p class="workspace-path">The plain-text foundation stays behind the scenes unless you want to engage with it.</p>
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
    gap: 0.8rem 1rem;
    align-items: center;
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

  .text-link {
    color: var(--brand-strong);
    text-decoration: none;
    font-weight: 700;
  }

  .text-link:hover {
    text-decoration: underline;
  }

  .stat-strip {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0;
    padding: 0.3rem 0;
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

  .workspace-strip {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
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

  .minimal-note {
    padding: 1.2rem 1.4rem;
  }

  .minimal-title {
    margin: 0;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.2rem;
    line-height: 1.25;
    max-width: 38rem;
  }

  .workspace-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
  }

  @media (max-width: 900px) {
    .stat-strip {
      grid-template-columns: 1fr;
    }

    .stat + .stat {
      border-left: 0;
      border-top: 1px solid rgba(15, 95, 136, 0.08);
    }

    .page-title-xl {
      max-width: none;
    }

    .workspace-strip {
      flex-direction: column;
      align-items: flex-start;
    }
  }
</style>
