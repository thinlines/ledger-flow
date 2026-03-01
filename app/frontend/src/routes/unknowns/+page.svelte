<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';

  let journalPath = '';
  let journals: Array<{ fileName: string; absPath: string }> = [];
  let stage: any = null;
  let error = '';
  let loading = false;
  let mappings: Record<string, string> = {};

  onMount(async () => {
    try {
      const data = await apiGet<{ journals: Array<{ fileName: string; absPath: string }> }>('/api/journals');
      journals = data.journals;
      if (journals.length) {
        journalPath = journals[journals.length - 1].absPath;
      }
    } catch (e) {
      error = String(e);
    }
  });

  async function scan() {
    error = '';
    stage = null;
    loading = true;
    try {
      stage = await apiPost('/api/unknowns/scan', { journalPath });
      mappings = {};
      for (const g of stage.groups ?? []) {
        if (g.suggestedAccount) mappings[g.groupKey] = g.suggestedAccount;
      }
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function stageMappings() {
    if (!stage?.stageId) return;
    loading = true;
    try {
      const payload = Object.entries(mappings)
        .filter(([, v]) => v && v.trim().length > 0)
        .map(([groupKey, chosenAccount]) => ({ groupKey, chosenAccount }));
      stage = await apiPost('/api/unknowns/stage-mappings', { stageId: stage.stageId, mappings: payload });
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function applyMappings() {
    if (!stage?.stageId) return;
    loading = true;
    try {
      stage = await apiPost('/api/unknowns/apply', { stageId: stage.stageId });
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }
</script>

<section class="view-card hero">
  <p class="eyebrow">Review Queue</p>
  <h2 class="page-title">Unknown Account Reconciliation</h2>
  <p class="subtitle">Scan a journal, assign accounts by payee group, and apply staged mappings.</p>
</section>

{#if error}
  <section class="view-card"><p class="error-text">{error}</p></section>
{/if}

<section class="view-card">
  <p class="eyebrow">Scan Input</p>
  <h3>Choose Journal</h3>

  <div class="field grid-2 compact">
    <div class="field">
      <label for="journalSelect">Detected Journals</label>
      <select id="journalSelect" bind:value={journalPath}>
        <option value="">Select...</option>
        {#each journals as j}
          <option value={j.absPath}>{j.fileName}</option>
        {/each}
      </select>
    </div>

    <div class="field">
      <label for="journalPath">Journal Path</label>
      <input id="journalPath" bind:value={journalPath} placeholder="/abs/path/to/journal" />
    </div>
  </div>

  <button class="btn btn-primary" disabled={loading || !journalPath} on:click={scan}>Scan Unknowns</button>
</section>

{#if stage}
  <section class="view-card">
    <p class="eyebrow">Stage</p>
    <h3>Stage {stage.stageId}</h3>
    <p class="muted">Payee groups: {stage.groups?.length ?? 0}</p>

    {#if (stage.groups?.length ?? 0) === 0}
      <p><span class="pill ok">No unknown postings found</span></p>
    {/if}

    <div class="groups">
      {#each stage.groups ?? [] as g}
        <article class="group">
          <header>
            <strong>{g.payeeDisplay}</strong>
            <span class="pill">{g.txns.length} transactions</span>
          </header>
          <div class="field">
            <label for={"acct-" + g.groupKey}>Assign account</label>
            <input id={"acct-" + g.groupKey} bind:value={mappings[g.groupKey]} placeholder="Expenses:Groceries" />
          </div>
        </article>
      {/each}
    </div>

    {#if stage.summary}
      <p class="muted">Staged updates: {stage.summary.txnUpdates}</p>
    {/if}

    {#if stage.result}
      <p><span class="pill ok">Applied</span></p>
      <p>
        Updated transactions: {stage.result.updatedTxnCount} | Learned rules: {stage.result.addedRuleCount}
      </p>
      {#if stage.result.warnings?.length}
        <h4>Warnings</h4>
        <ul>
          {#each stage.result.warnings as w}
            <li>{w.groupKey}: {w.warning}</li>
          {/each}
        </ul>
      {/if}
    {:else}
      <div class="actions">
        <button class="btn" disabled={loading} on:click={stageMappings}>Stage Mappings</button>
        <button class="btn btn-primary" disabled={loading} on:click={applyMappings}>Apply Mappings</button>
      </div>
    {/if}
  </section>
{/if}

<style>
  h3 {
    margin: 0.1rem 0 0.8rem;
  }

  .compact {
    gap: 0.8rem;
    margin: 0.3rem 0 0.8rem;
  }

  .groups {
    display: grid;
    gap: 0.6rem;
    margin-bottom: 0.8rem;
  }

  .group {
    border: 1px solid var(--line);
    border-radius: 12px;
    background: var(--card-2);
    padding: 0.75rem;
  }

  .group header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
  }

  .actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }
</style>
