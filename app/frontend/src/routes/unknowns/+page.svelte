<script lang="ts">
  import { onMount } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';

  type TxnRow = {
    txnId: string;
    date: string;
    lineNo: number;
    currentAccount: string;
    amount: string;
    counterpartyAccount: string;
  };

  type UnknownGroup = {
    groupKey: string;
    payeeDisplay: string;
    suggestedAccount: string | null;
    txns: TxnRow[];
  };

  let initialized = false;
  let journalPath = '';
  let journals: Array<{ fileName: string; absPath: string }> = [];
  let accounts: string[] = [];

  let stage: { stageId: string; groups: UnknownGroup[]; summary?: { txnUpdates: number }; result?: any } | null = null;
  let error = '';
  let loading = false;
  let mappings: Record<string, string> = {};

  let showRuleModal = false;
  let rulePayee = '';
  let ruleAccount = '';
  let ruleError = '';

  onMount(async () => {
    try {
      const state = await apiGet<{ initialized: boolean }>('/api/app/state');
      initialized = state.initialized;
      if (!initialized) return;

      const [journalsData, accountsData] = await Promise.all([
        apiGet<{ journals: Array<{ fileName: string; absPath: string }> }>('/api/journals'),
        apiGet<{ accounts: string[] }>('/api/accounts')
      ]);

      journals = journalsData.journals;
      accounts = accountsData.accounts;
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
      const data = await apiPost<any>('/api/unknowns/scan', { journalPath });
      stage = data;
      mappings = {};
      for (const g of data.groups ?? []) {
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
    error = '';
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
    error = '';
    try {
      const stageId = stage.stageId;
      const payload = Object.entries(mappings)
        .filter(([, v]) => v && v.trim().length > 0)
        .map(([groupKey, chosenAccount]) => ({ groupKey, chosenAccount }));
      stage = await apiPost('/api/unknowns/stage-mappings', { stageId, mappings: payload });
      stage = await apiPost('/api/unknowns/apply', { stageId });
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function filteredAccounts(query: string): string[] {
    const q = query.trim().toLowerCase();
    if (!q) return accounts.slice(0, 12);
    return accounts.filter((a) => a.toLowerCase().includes(q)).slice(0, 12);
  }

  function openRuleModal(group: UnknownGroup) {
    rulePayee = group.payeeDisplay;
    ruleAccount = mappings[group.groupKey] || group.suggestedAccount || '';
    ruleError = '';
    showRuleModal = true;
  }

  async function createRule() {
    if (!rulePayee || !ruleAccount) return;
    loading = true;
    ruleError = '';
    try {
      const result = await apiPost<{ added: boolean; warning: string | null }>('/api/rules/payee', {
        payee: rulePayee,
        account: ruleAccount
      });
      if (result.warning) {
        ruleError = result.warning;
      } else {
        for (const g of stage?.groups ?? []) {
          if (g.payeeDisplay === rulePayee) {
            mappings[g.groupKey] = ruleAccount;
            g.suggestedAccount = ruleAccount;
          }
        }
        showRuleModal = false;
      }
    } catch (e) {
      ruleError = String(e);
    } finally {
      loading = false;
    }
  }
</script>

<section class="view-card hero">
  <p class="eyebrow">Review Queue</p>
  <h2 class="page-title">Review and Categorize Transactions</h2>
  <p class="subtitle">See unknown transactions line-by-line, choose categories quickly, and apply updates safely.</p>
</section>

{#if !initialized}
  <section class="view-card">
    <p class="error-text">Workspace not initialized yet.</p>
    <a class="btn btn-primary" href="/setup">Go to Setup</a>
  </section>
{:else}
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
      <p class="eyebrow">Review</p>
      <h3>Unknown Groups ({stage.groups?.length ?? 0})</h3>

      {#if (stage.groups?.length ?? 0) === 0}
        <p><span class="pill ok">No unknown postings found</span></p>
      {/if}

      <div class="groups">
        {#each stage.groups ?? [] as g}
          <article class="group">
            <header>
              <div>
                <strong>{g.payeeDisplay}</strong>
                <div class="muted">{g.txns.length} transactions</div>
              </div>
              <button class="btn" on:click={() => openRuleModal(g)}>Make Rule...</button>
            </header>

            <div class="field">
              <label for={'acct-' + g.groupKey}>Category Account</label>
              <input id={'acct-' + g.groupKey} bind:value={mappings[g.groupKey]} placeholder="Type to filter accounts" />
              {#if mappings[g.groupKey] !== undefined}
                <div class="suggestions">
                  {#each filteredAccounts(mappings[g.groupKey]) as acct}
                    <button type="button" class="suggestion" on:click={() => (mappings[g.groupKey] = acct)}>{acct}</button>
                  {/each}
                </div>
              {/if}
            </div>

            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Amount</th>
                    <th>From/To</th>
                    <th>Current Category</th>
                  </tr>
                </thead>
                <tbody>
                  {#each g.txns as t}
                    <tr>
                      <td>{t.date}</td>
                      <td>{t.amount || '-'}</td>
                      <td>{t.counterpartyAccount || '-'}</td>
                      <td>{t.currentAccount}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </article>
        {/each}
      </div>

      {#if stage.summary}
        <p class="muted">Staged updates: {stage.summary.txnUpdates}</p>
      {/if}

      {#if stage.result}
        <p><span class="pill ok">Applied</span></p>
        <p>Updated transactions: {stage.result.updatedTxnCount}</p>
        {#if stage.result.warnings?.length}
          <h4>Warnings</h4>
          <ul>
            {#each stage.result.warnings as w}
              <li>{w.groupKey}: {w.warning}</li>
            {/each}
          </ul>
        {/if}
      {:else}
        <p class="muted">Review Update Count previews the number of lines that will change. Apply to Journal writes those changes.</p>
        <div class="actions">
          <button class="btn" disabled={loading} on:click={stageMappings}>Review Update Count</button>
          <button class="btn btn-primary" disabled={loading} on:click={applyMappings}>Apply to Journal</button>
        </div>
      {/if}
    </section>
  {/if}
{/if}

{#if showRuleModal}
  <div
    class="modal-backdrop"
    role="button"
    aria-label="Close dialog"
    tabindex="0"
    on:click={(e) => ((e.target as HTMLElement) === (e.currentTarget as HTMLElement) ? (showRuleModal = false) : undefined)}
    on:keydown={(e) => (e.key === 'Escape' || e.key === 'Enter' ? (showRuleModal = false) : undefined)}
  >
    <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label="Make Rule">
      <h3>Make Rule</h3>
      <p class="muted">Create a reusable mapping from payee to account.</p>
      <div class="field">
        <label for="rulePayee">Payee</label>
        <input id="rulePayee" bind:value={rulePayee} />
      </div>
      <div class="field">
        <label for="ruleAccount">Account</label>
        <input id="ruleAccount" bind:value={ruleAccount} placeholder="Type to filter accounts" />
        <div class="suggestions">
          {#each filteredAccounts(ruleAccount) as acct}
            <button type="button" class="suggestion" on:click={() => (ruleAccount = acct)}>{acct}</button>
          {/each}
        </div>
      </div>
      {#if ruleError}<p class="error-text">{ruleError}</p>{/if}
      <div class="actions">
        <button class="btn" on:click={() => (showRuleModal = false)}>Cancel</button>
        <button class="btn btn-primary" disabled={loading || !rulePayee || !ruleAccount} on:click={createRule}>Save Rule</button>
      </div>
    </div>
  </div>
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
    gap: 0.8rem;
    margin-bottom: 0.8rem;
  }

  .group {
    border: 1px solid var(--line);
    border-radius: 12px;
    background: var(--card-2);
    padding: 0.85rem;
  }

  .group header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.7rem;
  }

  .table-wrap {
    overflow: auto;
    margin-top: 0.55rem;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.92rem;
  }

  th, td {
    border-bottom: 1px solid var(--line);
    text-align: left;
    padding: 0.42rem;
  }

  .suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin-top: 0.35rem;
  }

  .suggestion {
    border: 1px solid var(--line);
    border-radius: 999px;
    background: #f7fbff;
    padding: 0.2rem 0.55rem;
    cursor: pointer;
    font-size: 0.8rem;
  }

  .actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(10, 20, 30, 0.35);
    display: grid;
    place-items: center;
    padding: 1rem;
    z-index: 30;
  }

  .modal {
    width: min(620px, 100%);
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 1rem;
  }
</style>
