<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import AccountCombobox from '$lib/components/AccountCombobox.svelte';
  import RuleEditor from '$lib/components/RuleEditor.svelte';
  import type { RuleAction, RuleCondition } from '$lib/components/rule-editor-types';
  import {
    createDefaultRuleActions,
    createDefaultRuleConditions,
    ensureSetAccountAction,
    extractSetAccount,
    findMatchingRule,
    normalizeRule,
    sanitizedActions,
    sanitizedConditions
  } from '$lib/rules';

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

  type Rule = {
    id: string;
    type: 'match';
    conditions: RuleCondition[];
    actions: RuleAction[];
    enabled: boolean;
    position: number;
    updatedAt: string;
  };

  let initialized = false;
  let journalPath = '';
  let journals: Array<{ fileName: string; absPath: string }> = [];
  let accounts: string[] = [];
  let rules: Rule[] = [];

  let stage: { stageId: string; groups: UnknownGroup[]; summary?: { txnUpdates: number }; result?: any } | null = null;
  let error = '';
  let loading = false;
  let mappings: Record<string, string> = {};

  let showRuleModal = false;
  let ruleMode: 'create' | 'edit' = 'create';
  let ruleError = '';
  let ruleGroupKey: string | null = null;
  let ruleSourcePayee = '';
  let ruleId: string | null = null;
  let ruleEnabled = true;
  let ruleConditions: RuleCondition[] = createDefaultRuleConditions();
  let ruleActions: RuleAction[] = createDefaultRuleActions();

  let showCreateAccountModal = false;
  let newAccountName = '';
  let newAccountType = 'Expense';
  let createAccountError = '';
  let newAccountInputEl: HTMLInputElement | null = null;
  let createAccountContext: { mode: 'rule' | 'group'; groupKey: string | null } = { mode: 'rule', groupKey: null };
  let statusFilter: 'all' | 'matched' | 'needs' = 'all';

  function pathLabel(path: string): string {
    const parts = path.split('/').filter(Boolean);
    return parts.at(-1) ?? path;
  }

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

  async function loadRules() {
    const rulesData = await apiGet<{ rules: Rule[] }>('/api/rules');
    rules = rulesData.rules.map(normalizeRule);
    return rules;
  }

  onMount(async () => {
    try {
      const state = await apiGet<{ initialized: boolean }>('/api/app/state');
      initialized = state.initialized;
      if (!initialized) return;

      const [journalsData, accountsData, rulesData] = await Promise.all([
        apiGet<{ journals: Array<{ fileName: string; absPath: string }> }>('/api/journals'),
        apiGet<{ accounts: string[] }>('/api/accounts'),
        apiGet<{ rules: Rule[] }>('/api/rules')
      ]);

      journals = journalsData.journals;
      accounts = accountsData.accounts;
      rules = rulesData.rules.map(normalizeRule);
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

    for (const group of stage?.groups ?? []) {
      const selected = effectiveAccountFor(group);
      const status = selected ? 'matched' : 'needs';
      for (const txn of group.txns) {
        rows.push({
          rowId: txn.txnId,
          groupKey: group.groupKey,
          payee: group.payeeDisplay,
          date: txn.date,
          amount: txn.amount || '-',
          counterparty: txn.counterpartyAccount || '-',
          currentAccount: txn.currentAccount,
          selectedAccount: selected,
          status,
          hasExistingRule: !!group.matchedRuleId,
          matchedRuleId: group.matchedRuleId || null
        });
      }
    }

    if (statusFilter === 'all') return rows;
    if (statusFilter === 'matched') return rows.filter((row) => row.status === 'matched');
    return rows.filter((row) => row.status === 'needs');
  }

  function syncGroupsFromRules(nextRules: Rule[]) {
    if (!stage) return;

    const nextMappings = { ...mappings };
    for (const group of stage.groups ?? []) {
      const previousSuggested = (group.suggestedAccount ?? '').trim();
      const currentSelected = (nextMappings[group.groupKey] ?? '').trim();
      const matchedRule = findMatchingRule({ payee: group.payeeDisplay }, nextRules);
      const suggestedAccount = matchedRule ? extractSetAccount(matchedRule.actions) || null : null;
      const shouldFollowSuggestion = !currentSelected || currentSelected === previousSuggested;
      group.suggestedAccount = suggestedAccount;
      group.matchedRuleId = matchedRule?.id ?? null;
      group.matchedRulePattern = matchedRule?.conditions?.[0]?.value ?? null;
      if (shouldFollowSuggestion && suggestedAccount) {
        nextMappings[group.groupKey] = suggestedAccount;
      } else if (shouldFollowSuggestion) {
        delete nextMappings[group.groupKey];
      }
    }

    mappings = nextMappings;
    stage = { ...stage, groups: [...stage.groups] };
  }

  async function stageMappings() {
    if (!stage?.stageId) return;
    loading = true;
    error = '';
    try {
      const payload = Object.entries(mappings)
        .filter(([, value]) => value && value.trim().length > 0)
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
        .filter(([, value]) => value && value.trim().length > 0)
        .map(([groupKey, chosenAccount]) => ({ groupKey, chosenAccount }));
      stage = await apiPost('/api/unknowns/stage-mappings', { stageId, mappings: payload });
      stage = await apiPost('/api/unknowns/apply', { stageId });
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function setRuleAccount(account: string) {
    const nextActions = ensureSetAccountAction(ruleActions, account);
    const setAccountIndex = nextActions.findIndex((action) => action.type === 'set_account');
    nextActions[setAccountIndex] = { type: 'set_account', account };
    ruleActions = nextActions;
  }

  async function openRuleModal(groupKey: string) {
    const group = stage?.groups.find((candidate) => candidate.groupKey === groupKey);
    if (!group) return;

    let matchedRule = group.matchedRuleId ? rules.find((candidate) => candidate.id === group.matchedRuleId) ?? null : null;
    if (group.matchedRuleId && !matchedRule) {
      try {
        const refreshedRules = await loadRules();
        matchedRule = refreshedRules.find((candidate) => candidate.id === group.matchedRuleId) ?? null;
      } catch (e) {
        error = String(e);
        return;
      }
    }

    const fallbackAccount = mappings[group.groupKey] || group.suggestedAccount || '';

    ruleGroupKey = group.groupKey;
    ruleSourcePayee = group.payeeDisplay;
    ruleMode = matchedRule ? 'edit' : 'create';
    ruleId = matchedRule?.id ?? null;
    ruleEnabled = matchedRule?.enabled ?? true;
    ruleConditions = matchedRule
      ? matchedRule.conditions.map((condition) => ({ ...condition }))
      : createDefaultRuleConditions(group.payeeDisplay);
    ruleActions = matchedRule
      ? ensureSetAccountAction(matchedRule.actions, fallbackAccount)
      : createDefaultRuleActions(fallbackAccount);
    ruleError = '';
    showRuleModal = true;
    await tick();
  }

  async function persistRule({ allowCreateAccountModal }: { allowCreateAccountModal: boolean }) {
    const cleanedConditions = sanitizedConditions(ruleConditions);
    const cleanedActions = sanitizedActions(ruleActions);
    const selectedAccount = extractSetAccount(cleanedActions);

    if (!cleanedConditions.length) {
      ruleError = 'At least one rule condition is required.';
      return false;
    }
    if (!selectedAccount) {
      ruleError = 'Rule must map to an account.';
      return false;
    }

    ruleError = '';

    if (allowCreateAccountModal && !accounts.includes(selectedAccount)) {
      showRuleModal = false;
      await openCreateAccountModal(selectedAccount, { mode: 'rule', groupKey: ruleGroupKey });
      return false;
    }

    loading = true;
    try {
      const currentRuleId = ruleId;
      let savedRule: Rule;
      if (currentRuleId) {
        const response = await apiPost<{ rule: Rule }>(`/api/rules/${currentRuleId}`, {
          conditions: cleanedConditions,
          actions: cleanedActions,
          enabled: ruleEnabled
        });
        savedRule = normalizeRule(response.rule);
      } else {
        const response = await apiPost<{ rule: Rule }>('/api/rules', {
          conditions: cleanedConditions,
          actions: cleanedActions,
          enabled: true
        });
        savedRule = normalizeRule(response.rule);
      }

      const existingIndex = rules.findIndex((existingRule) => existingRule.id === savedRule.id);
      const nextRules =
        existingIndex >= 0
          ? rules.map((existingRule) => (existingRule.id === savedRule.id ? savedRule : existingRule))
          : [...rules, savedRule];
      rules = nextRules;
      ruleId = savedRule.id;
      ruleEnabled = savedRule.enabled;
      ruleMode = 'edit';
      syncGroupsFromRules(nextRules);
      if (ruleGroupKey) {
        mappings = { ...mappings, [ruleGroupKey]: selectedAccount };
      }
      showRuleModal = false;
      return true;
    } catch (e) {
      ruleError = String(e);
      showRuleModal = true;
      return false;
    } finally {
      loading = false;
    }
  }

  async function saveRule() {
    await persistRule({ allowCreateAccountModal: true });
  }

  function setAccountForGroup(groupKey: string, account: string) {
    mappings = { ...mappings, [groupKey]: account };
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

  function closeCreateAccountModal() {
    createAccountError = '';
    showCreateAccountModal = false;
    if (createAccountContext.mode === 'rule') {
      showRuleModal = true;
    }
  }

  async function openCreateAccountForGroup(groupKey: string, initialName = '') {
    await openCreateAccountModal(initialName, { mode: 'group', groupKey });
  }

  async function openCreateAccountForRule(initialName = '') {
    showRuleModal = false;
    await openCreateAccountModal(initialName, { mode: 'rule', groupKey: ruleGroupKey });
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
          mappings = { ...mappings, [createAccountContext.groupKey]: newAccountName };
        }
        showCreateAccountModal = false;
        return;
      }

      setRuleAccount(newAccountName);
      showCreateAccountModal = false;
      showRuleModal = true;
      await persistRule({ allowCreateAccountModal: false });
    } catch (e) {
      createAccountError = String(e);
    } finally {
      loading = false;
    }
  }
</script>

<section class="view-card hero">
  <p class="eyebrow">Categorization</p>
  <h2 class="page-title">Review uncategorized activity</h2>
  <p class="subtitle">Fill in missing categories, save repeat decisions as rules, and keep recent activity clean.</p>
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
    <p class="eyebrow">Review Scope</p>
    <h3>Choose Activity to Review</h3>

    <div class="field compact">
      <div class="field">
        <label for="journalSelect">Available Years</label>
        <select id="journalSelect" bind:value={journalPath}>
          <option value="">Select...</option>
          {#each journals as j}
            <option value={j.absPath}>{j.fileName}</option>
          {/each}
        </select>
      </div>
    </div>

    {#if journalPath}
      <p class="muted">Selected file: {pathLabel(journalPath)}</p>
    {/if}

    <details class="advanced-panel">
      <summary>Advanced file selection</summary>
      <div class="field">
        <label for="journalPath">Custom Journal Path</label>
        <input id="journalPath" bind:value={journalPath} placeholder="/abs/path/to/journal" />
      </div>
    </details>

    <button class="btn btn-primary" disabled={loading || !journalPath} on:click={scan}>
      {loading ? 'Scanning...' : 'Find Transactions to Review'}
    </button>
  </section>

  {#if stage}
    <section class="view-card">
      <p class="eyebrow">Review</p>
      <h3>Transactions Needing Attention</h3>

      {#if (stage.groups?.length ?? 0) === 0}
        <p><span class="pill ok">No uncategorized transactions found</span></p>
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
              <th>Current Category</th>
              <th>Category</th>
              <th>Automation</th>
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
                  <button class="btn" on:click={() => openRuleModal(r.groupKey)}>
                    {r.hasExistingRule ? 'Edit Rule...' : 'Create Rule...'}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      {#if stage.summary}
        <p class="muted">Estimated updates: {stage.summary.txnUpdates}</p>
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
        <p class="muted">Preview Changes estimates how many transactions will be updated. Apply Changes writes those updates safely.</p>
        <div class="actions">
          <button class="btn" disabled={loading} on:click={stageMappings}>Preview Changes</button>
          <button class="btn btn-primary" disabled={loading} on:click={applyMappings}>Apply Changes</button>
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
    on:keydown={(e) => (e.key === 'Escape' ? (showRuleModal = false) : undefined)}
  >
    <div class="modal rule-modal" role="dialog" tabindex="-1" aria-modal="true" aria-label="Automation Rule">
      <h3>{ruleMode === 'edit' ? 'Edit Rule' : 'Create Rule'}</h3>
      <p class="muted">
        {ruleMode === 'edit'
          ? 'Update the reusable rule that matched this transaction group.'
          : 'Create a reusable rule from this transaction group.'}
      </p>
      <p class="rule-modal-meta">
        <strong>Source payee:</strong> {ruleSourcePayee}
      </p>
      <RuleEditor
        bind:conditions={ruleConditions}
        bind:actions={ruleActions}
        {accounts}
        allowAccountCreate={true}
        onAccountCreate={(seed) => void openCreateAccountForRule(seed)}
      />
      {#if ruleError}<p class="error-text">{ruleError}</p>{/if}
      <div class="actions">
        <button class="btn" on:click={() => (showRuleModal = false)}>Cancel</button>
        <button
          class="btn btn-primary"
          disabled={loading || !sanitizedConditions(ruleConditions).length || !extractSetAccount(ruleActions)}
          on:click={saveRule}
        >
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
    on:click={(e) => ((e.target as HTMLElement) === (e.currentTarget as HTMLElement) ? closeCreateAccountModal() : undefined)}
    on:keydown={(e) => (e.key === 'Escape' ? closeCreateAccountModal() : undefined)}
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
        <button class="btn" on:click={closeCreateAccountModal}>Cancel</button>
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

  .advanced-panel {
    margin: 0 0 0.9rem;
    border: 1px solid rgba(15, 95, 136, 0.12);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.7);
    padding: 0.8rem;
  }

  .advanced-panel summary {
    cursor: pointer;
    font-weight: 700;
    color: var(--brand-strong);
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

  .rule-modal {
    width: min(760px, 100%);
  }

  .rule-modal-meta {
    margin: 0 0 0.7rem;
    color: var(--muted);
    font-size: 0.92rem;
  }
</style>
