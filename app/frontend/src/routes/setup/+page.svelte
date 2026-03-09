<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';

  type AppState = {
    initialized: boolean;
    workspacePath: string | null;
    workspaceName: string | null;
    institutions: Array<{ id: string; displayName: string }>;
    journals: number;
    csvInbox: number;
    institutionTemplates: Array<{ id: string; displayName: string } | string>;
  };

  let state: AppState | null = null;
  let error = '';
  let loading = false;

  let workspacePath = '/home/randy/Desktop/tmp-books/workspace';
  let workspaceName = 'My Books';
  let baseCurrency = '$';
  let startYear = new Date().getFullYear();
  let selectedInstitutions: string[] = [];

  function templateId(tpl: { id: string; displayName: string } | string): string {
    return typeof tpl === 'string' ? tpl : tpl.id;
  }

  function templateLabel(tpl: { id: string; displayName: string } | string): string {
    return typeof tpl === 'string' ? tpl : tpl.displayName;
  }

  async function loadState() {
    state = await apiGet<AppState>('/api/app/state');
  }

  function toggleInstitution(inst: string) {
    selectedInstitutions = selectedInstitutions.includes(inst)
      ? selectedInstitutions.filter((x) => x !== inst)
      : [...selectedInstitutions, inst];
  }

  async function bootstrap() {
    loading = true;
    error = '';
    try {
      await apiPost('/api/workspace/bootstrap', {
        workspacePath,
        workspaceName,
        baseCurrency,
        startYear,
        institutions: selectedInstitutions
      });
      await loadState();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function selectExisting() {
    loading = true;
    error = '';
    try {
      await apiPost('/api/workspace/select', { workspacePath });
      await loadState();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(async () => {
    try {
      await loadState();
    } catch (e) {
      error = String(e);
    }
  });
</script>

<section class="view-card hero">
  <p class="eyebrow">Setup</p>
  <h2 class="page-title">Initialize Your Financial Workspace</h2>
  <p class="subtitle">Create or select a workspace for your finances. The app handles the underlying structure for you.</p>
</section>

{#if error}
  <section class="view-card"><p class="error-text">{error}</p></section>
{/if}

{#if state?.initialized}
  <section class="view-card">
    <p class="eyebrow">Active Workspace</p>
    <h3>{state.workspaceName}</h3>
    <p class="muted">{state.workspacePath}</p>
    <p>
      <span class="pill ok">{state.institutions.length} institutions</span>
      <span class="pill">{state.journals} years loaded</span>
      <span class="pill">{state.csvInbox} statements waiting</span>
    </p>
    <div class="actions">
      <a class="btn btn-primary" href="/">Open Overview</a>
      <a class="btn" href="/import">Import Activity</a>
      <a class="btn" href="/unknowns">Review Categories</a>
    </div>
  </section>
{/if}

<section class="grid-2">
  <article class="view-card">
    <p class="eyebrow">Create New</p>
    <h3>Create a New Workspace</h3>

    <div class="field"><label for="newWorkspacePath">Workspace Path</label><input id="newWorkspacePath" bind:value={workspacePath} /></div>
    <div class="field"><label for="workspaceName">Workspace Name</label><input id="workspaceName" bind:value={workspaceName} /></div>
    <div class="field grid-2 compact">
      <div class="field"><label for="baseCurrency">Base Currency</label><input id="baseCurrency" bind:value={baseCurrency} /></div>
      <div class="field"><label for="startYear">Start Year</label><input id="startYear" type="number" bind:value={startYear} /></div>
    </div>

    <div class="field">
      <p class="muted section-label">Institution Templates (optional)</p>
      <div class="chips">
        {#each state?.institutionTemplates ?? [] as inst}
          <button
            type="button"
            class:selected={selectedInstitutions.includes(templateId(inst))}
            on:click={() => toggleInstitution(templateId(inst))}>{templateLabel(inst)}</button>
        {/each}
      </div>
    </div>

    <button class="btn btn-primary" disabled={loading} on:click={bootstrap}>
      {loading ? 'Creating...' : 'Create Workspace'}
    </button>
  </article>

  <article class="view-card">
    <p class="eyebrow">Use Existing</p>
    <h3>Select Existing Workspace</h3>
    <div class="field"><label for="existingWorkspacePath">Workspace Path</label><input id="existingWorkspacePath" bind:value={workspacePath} /></div>
    <button class="btn" disabled={loading} on:click={selectExisting}>Select Workspace</button>
    <p class="muted">Path must contain `settings/workspace.toml`.</p>
  </article>
</section>

<style>
  h3 {
    margin: 0.1rem 0 0.8rem;
  }

  .actions {
    margin-top: 0.8rem;
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .compact {
    gap: 0.8rem;
  }

  .chips {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .chips button {
    border: 1px solid var(--line);
    border-radius: 999px;
    background: #f4f8fd;
    padding: 0.3rem 0.65rem;
    cursor: pointer;
    font-weight: 600;
  }

  .chips button.selected {
    background: #d8efff;
    border-color: #93c6e8;
    color: #0a4664;
    font-weight: 700;
  }

  .section-label {
    margin: 0;
    font-size: 0.86rem;
    font-weight: 600;
  }
</style>
