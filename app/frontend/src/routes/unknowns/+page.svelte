<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import AccountCombobox from '$lib/components/AccountCombobox.svelte';

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
    matchedRuleId?: string | null;
    matchedRulePattern?: string | null;
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
  let ruleMode: 'create' | 'edit' = 'create';
  let ruleError = '';
  let ruleAccountInputEl: HTMLInputElement | null = null;

  let showCreateAccountModal = false;
  let newAccountName = '';
  let newAccountType = 'Expense';
  let createAccountError = '';
  let newAccountInputEl: HTMLInputElement | null = null;
  let createAccountContext: { mode: 'rule' | 'group'; groupKey: string | null } = { mode: 'rule', groupKey: null };
  let statusFilter: 'all' | 'matched' | 'needs' = 'all';

  function inferAccountType(accountName: string): string {
    const prefix = accountName.split(':', 1)[0]?.trim().toLowerCase() || '';
    if (prefix === 'assets') return 'Asset';
    if (prefix === 'liabilities' || prefix === 'liability') return 'Liability';
    if (prefix === 'expenses' || prefix === 'expense') return 'Expense';
    if (prefix === 'income' || prefix === 'revenue') return 'Revenue';
    if (prefix === 'equity') return 'Equity';
    return 'Expense';
  }

  function updateInferredTypeFromName() {
    newAccountType = inferAccountType(newAccountName);
  }

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

  function effectiveAccountFor(group: UnknownGroup): string {
    return (mappings[group.groupKey] || '').trim();
  }

  function statusFor(group: UnknownGroup): 'matched' | 'needs' {
    return effectiveAccountFor(group) ? 'matched' : 'needs';
  }

  function transactionRows(): Array<{
    rowId: string;
    groupKey: string;
    payee: string;
    date: string;
    amount: string;
    counterparty: string;
    currentAccount: string;
    selectedAccount: string;
    status: 'matched' | 'needs';
    hasExistingRule: boolean;
    matchedRuleId: string | null;
  }> {
    const rows: Array<{
      rowId: string;
      groupKey: string;
      payee: string;
      date: string;
      amount: string;
      counterparty: string;
      currentAccount: string;
      selectedAccount: string;
      status: 'matched' | 'needs';
      hasExistingRule: boolean;
      matchedRuleId: string | null;
    }> = [];
    for (const g of stage?.groups ?? []) {
      const selected = effectiveAccountFor(g);
      const status = selected ? 'matched' : 'needs';
      for (const t of g.txns) {
        rows.push({
          rowId: t.txnId,
          groupKey: g.groupKey,
          payee: g.payeeDisplay,
          date: t.date,
          amount: t.amount || '-',
          counterparty: t.counterpartyAccount || '-',
          currentAccount: t.currentAccount,
          selectedAccount: selected,
          status,
          hasExistingRule: !!g.suggestedAccount,
          matchedRuleId: g.matchedRuleId || null
        });
      }
    }
    if (statusFilter === 'all') return rows;
    if (statusFilter === 'matched') return rows.filter((r) => r.status === 'matched');
    return rows.filter((r) => r.status === 'needs');
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

  async function openRuleModal(group: UnknownGroup) {
    rulePayee = group.payeeDisplay;
    ruleAccount = mappings[group.groupKey] || group.suggestedAccount || '';
    ruleMode = group.suggestedAccount ? 'edit' : 'create';
    ruleError = '';
    showRuleModal = true;
    await tick();
    ruleAccountInputEl?.focus();
    ruleAccountInputEl?.select();
  }

  async function saveRule() {
    if (!rulePayee || !ruleAccount) return;
    ruleError = '';

    if (!accounts.includes(ruleAccount)) {
      showRuleModal = false;
      await openCreateAccountModal(ruleAccount, { mode: 'rule', groupKey: null });
      return;
    }

    loading = true;
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

  function setAccountForGroup(groupKey: string, account: string) {
    mappings[groupKey] = account;
  }

  async function openCreateAccountModal(initialName = '', context: { mode: 'rule' | 'group'; groupKey: string | null }) {
    createAccountContext = context;
    newAccountName = initialName;
    updateInferredTypeFromName();
    createAccountError = '';
    showCreateAccountModal = true;
    await tick();
    newAccountInputEl?.focus();
    newAccountInputEl?.select();
  }

  async function openCreateAccountForGroup(groupKey: string, initialName = '') {
    await openCreateAccountModal(initialName, { mode: 'group', groupKey });
  }

  async function createAccountAndContinue() {
    if (!newAccountName || !newAccountType) return;
    loading = true;
    createAccountError = '';
    try {
      const created = await apiPost<{ added: boolean; warning: string | null }>('/api/accounts', {
        account: newAccountName,
        accountType: newAccountType
      });
      if (created.warning) {
        createAccountError = created.warning;
        return;
      }

      const refreshed = await apiGet<{ accounts: string[] }>('/api/accounts');
      accounts = refreshed.accounts;

      if (createAccountContext.mode === 'group') {
        if (createAccountContext.groupKey) {
          mappings[createAccountContext.groupKey] = newAccountName;
        }
        showCreateAccountModal = false;
        return;
      }

      ruleAccount = newAccountName;

      const rule = await apiPost<{ added: boolean; warning: string | null }>('/api/rules/payee', {
        payee: rulePayee,
        account: ruleAccount
      });
      if (rule.warning) {
        createAccountError = rule.warning;
        return;
      }

      for (const g of stage?.groups ?? []) {
        if (g.payeeDisplay === rulePayee) {
          mappings[g.groupKey] = ruleAccount;
          g.suggestedAccount = ruleAccount;
        }
      }

      showCreateAccountModal = false;
      showRuleModal = false;
    } catch (e) {
      createAccountError = String(e);
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
      <h3>Transactions To Review</h3>

      {#if (stage.groups?.length ?? 0) === 0}
        <p><span class="pill ok">No unknown postings found</span></p>
      {/if}

      <div class="filters">
        <button class="btn" class:active-filter={statusFilter === 'needs'} on:click={() => (statusFilter = 'needs')}>
          Needs Matching
        </button>
        <button class="btn" class:active-filter={statusFilter === 'matched'} on:click={() => (statusFilter = 'matched')}>
          Matched
        </button>
        <button class="btn" class:active-filter={statusFilter === 'all'} on:click={() => (statusFilter = 'all')}>
          All
        </button>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Date</th>
              <th>Payee</th>
              <th>Amount</th>
              <th>From/To</th>
              <th>Current</th>
              <th>Match To</th>
              <th>Rule</th>
              <th>Rule ID</th>
            </tr>
          </thead>
          <tbody>
            {#each transactionRows() as r}
              <tr>
                <td>
                  {#if r.status === 'matched'}
                    <span class="pill ok">Matched</span>
                  {:else}
                    <span class="pill warn">Needs Match</span>
                  {/if}
                </td>
                <td>{r.date}</td>
                <td>{r.payee}</td>
                <td>{r.amount}</td>
                <td>{r.counterparty}</td>
                <td>{r.currentAccount}</td>
                <td>
                  <AccountCombobox
                    accounts={accounts}
                    value={r.selectedAccount}
                    onChange={(account) => setAccountForGroup(r.groupKey, account)}
                    onCreate={(seed) => void openCreateAccountForGroup(r.groupKey, seed)}
                  />
                </td>
                <td>
                  <button
                    class="btn"
                    on:click={() =>
                      openRuleModal({
                        groupKey: r.groupKey,
                        payeeDisplay: r.payee,
                        suggestedAccount: r.hasExistingRule ? r.selectedAccount || null : null,
                        txns: []
                      })}
                  >
                    {r.hasExistingRule ? 'Edit Rule...' : 'Make Rule...'}
                  </button>
                </td>
                <td>{r.matchedRuleId ?? '-'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
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
      <h3>{ruleMode === 'edit' ? 'Edit Rule' : 'Make Rule'}</h3>
      <p class="muted">
        {ruleMode === 'edit'
          ? 'Update the reusable mapping for this payee.'
          : 'Create a reusable mapping from payee to account.'}
      </p>
      <div class="field">
        <label for="rulePayee">Payee</label>
        <input
          id="rulePayee"
          bind:value={rulePayee}
          on:keydown={(e) => (e.key === 'Enter' ? (e.preventDefault(), saveRule()) : undefined)}
        />
      </div>
      <div class="field">
        <label for="ruleAccount">Account</label>
        <input
          id="ruleAccount"
          bind:this={ruleAccountInputEl}
          bind:value={ruleAccount}
          placeholder="Type to filter accounts"
          on:keydown={(e) => (e.key === 'Enter' ? (e.preventDefault(), saveRule()) : undefined)}
        />
        <div class="suggestions">
          {#each filteredAccounts(ruleAccount) as acct}
            <button type="button" class="suggestion" on:click={() => (ruleAccount = acct)}>{acct}</button>
          {/each}
        </div>
      </div>
      {#if ruleError}<p class="error-text">{ruleError}</p>{/if}
      <div class="actions">
        <button class="btn" on:click={() => (showRuleModal = false)}>Cancel</button>
        <button class="btn btn-primary" disabled={loading || !rulePayee || !ruleAccount} on:click={saveRule}>
          {ruleMode === 'edit' ? 'Save Rule Changes' : 'Save Rule'}
        </button>
      </div>
    </div>
  </div>
{/if}

{#if showCreateAccountModal}
  <div
    class="modal-backdrop"
    role="button"
    aria-label="Close dialog"
    tabindex="0"
    on:click={(e) => ((e.target as HTMLElement) === (e.currentTarget as HTMLElement) ? (showCreateAccountModal = false) : undefined)}
    on:keydown={(e) => (e.key === 'Escape' || e.key === 'Enter' ? (showCreateAccountModal = false) : undefined)}
  >
    <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label="Create Account">
      <h3>Create New Account</h3>
      <p class="muted">Enter a fully qualified account name.</p>
      <div class="field">
        <label for="newAccountName">Account Name</label>
        <input
          id="newAccountName"
          bind:this={newAccountInputEl}
          bind:value={newAccountName}
          placeholder="Assets:Transfers"
          on:input={updateInferredTypeFromName}
          on:keydown={(e) => (e.key === 'Enter' ? (e.preventDefault(), createAccountAndContinue()) : undefined)}
        />
      </div>
      <div class="field">
        <label for="newAccountType">Account Type</label>
        <select id="newAccountType" bind:value={newAccountType}>
          <option value="Asset">Asset</option>
          <option value="Cash">Cash</option>
          <option value="Liability">Liability</option>
          <option value="Expense">Expense</option>
          <option value="Revenue">Revenue</option>
          <option value="Equity">Equity</option>
        </select>
      </div>
      {#if createAccountError}<p class="error-text">{createAccountError}</p>{/if}
      <div class="actions">
        <button class="btn" on:click={() => (showCreateAccountModal = false)}>Cancel</button>
        <button class="btn btn-primary" disabled={loading || !newAccountName || !newAccountType} on:click={createAccountAndContinue}>
          {createAccountContext.mode === 'rule' ? 'Create Account and Save Rule' : 'Create Account'}
        </button>
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

  .filters {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.7rem;
    flex-wrap: wrap;
  }

  .active-filter {
    background: #d8efff;
    border-color: #9ecfe9;
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
    vertical-align: top;
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
