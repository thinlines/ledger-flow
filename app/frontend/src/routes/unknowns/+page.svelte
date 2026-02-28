<script lang="ts">
  import { apiPost } from '$lib/api';

  let journalPath = '';
  let stage: any = null;
  let error = '';
  let loading = false;
  let mappings: Record<string, string> = {};

  async function scan() {
    error = '';
    stage = null;
    loading = true;
    try {
      stage = await apiPost('/api/unknowns/scan', { journalPath });
      mappings = {};
      for (const g of stage.groups ?? []) {
        if (g.suggestedAccount) {
          mappings[g.groupKey] = g.suggestedAccount;
        }
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
      stage = await apiPost('/api/unknowns/stage-mappings', {
        stageId: stage.stageId,
        mappings: payload
      });
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

<section>
  <h2>Unknown Account Reconciliation</h2>
  {#if error}<p class="error">{error}</p>{/if}

  <div class="panel">
    <label>Journal path <input bind:value={journalPath} placeholder="/abs/path/to/Journals/2026-wfchk.journal" /></label>
    <button disabled={loading || !journalPath} on:click={scan}>Scan Unknowns</button>
  </div>

  {#if stage}
    <div class="panel">
      <h3>Stage {stage.stageId}</h3>
      <p>Groups: {stage.groups?.length ?? 0}</p>

      {#if (stage.groups?.length ?? 0) === 0}
        <p>No unknown account postings found.</p>
      {/if}

      {#each stage.groups ?? [] as g}
        <div class="group">
          <strong>{g.payeeDisplay}</strong>
          <p>Transactions: {g.txns.length}</p>
          <label>
            Assign account
            <input bind:value={mappings[g.groupKey]} placeholder="Expenses:Groceries" />
          </label>
        </div>
      {/each}

      {#if stage.summary}
        <p>Staged updates: {stage.summary.txnUpdates}</p>
      {/if}

      {#if stage.result}
        <p>Applied. Updated txns: {stage.result.updatedTxnCount}; learned rules: {stage.result.addedRuleCount}</p>
        {#if stage.result.warnings?.length}
          <h4>Warnings</h4>
          <ul>
            {#each stage.result.warnings as w}
              <li>{w.groupKey}: {w.warning}</li>
            {/each}
          </ul>
        {/if}
      {:else}
        <div class="buttons">
          <button disabled={loading} on:click={stageMappings}>Stage Mappings</button>
          <button disabled={loading} on:click={applyMappings}>Apply Mappings</button>
        </div>
      {/if}
    </div>
  {/if}
</section>

<style>
  .panel {
    background: #fff;
    border: 1px solid #d2e0ee;
    border-radius: 10px;
    padding: 1rem;
    margin-bottom: 1rem;
  }

  .group {
    border: 1px solid #e7eff5;
    border-radius: 8px;
    padding: 0.75rem;
    margin-bottom: 0.75rem;
    background: #fefefe;
  }

  label {
    display: block;
  }

  input {
    width: min(40rem, 100%);
    padding: 0.45rem;
    margin-top: 0.25rem;
  }

  .buttons {
    display: flex;
    gap: 0.6rem;
  }

  .error {
    color: #9f1c1c;
  }
</style>
