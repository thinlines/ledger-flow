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
    amount: string;
    counterpartyAccount: string;
    line: string;
  };

  type UnknownGroup = {
    groupKey: string;
    payeeDisplay: string;
    importAccountId?: string | null;
    importAccountDisplayName?: string | null;
    importLedgerAccount?: string | null;
    sourceAccountLabel?: string | null;
    sourceLedgerAccount?: string | null;
    suggestedAccount: string | null;
    matchedRuleId?: string | null;
    matchedRulePattern?: string | null;
    txns: TxnRow[];
  };

  type UnknownStage = {
    stageId: string;
    groups: UnknownGroup[];
    summary?: {
      groupCount?: number;
      txnUpdates: number;
    };
    result?: {
      updatedTxnCount: number;
      warnings?: Array<{ groupKey: string; warning: string }>;
    } | null;
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

  let stage: UnknownStage | null = null;
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
  let statusFilter: 'all' | 'ready' | 'needs' = 'all';

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
      const data = await apiPost<UnknownStage>('/api/unknowns/scan', { journalPath });
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

  function groupStatus(group: UnknownGroup): 'ready' | 'needs' {
    return effectiveAccountFor(group) ? 'ready' : 'needs';
  }

  function visibleGroups(): UnknownGroup[] {
    const groups = stage?.groups ?? [];
    if (statusFilter === 'all') return groups;
    return groups.filter((group) => groupStatus(group) === statusFilter);
  }

  function totalTransactionCount(groups: UnknownGroup[] = stage?.groups ?? []): number {
    return groups.reduce((total, group) => total + group.txns.length, 0);
  }

  function readyGroupCount(): number {
    return (stage?.groups ?? []).filter((group) => groupStatus(group) === 'ready').length;
  }

  function needsGroupCount(): number {
    return (stage?.groups ?? []).filter((group) => groupStatus(group) === 'needs').length;
  }

  function parseJournalDate(value: string): number | null {
    const normalized = value.replace(/\//g, '-');
    const parsed = new Date(`${normalized}T00:00:00`);
    const timestamp = parsed.getTime();
    return Number.isNaN(timestamp) ? null : timestamp;
  }

  function formatShortDate(value: string): string {
    const timestamp = parseJournalDate(value);
    if (timestamp === null) return value || '-';
    return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(new Date(timestamp));
  }

  function groupDateRange(group: UnknownGroup): string {
    const validDates = group.txns
      .map((txn) => ({ raw: txn.date, timestamp: parseJournalDate(txn.date) }))
      .filter((item) => item.timestamp !== null) as Array<{ raw: string; timestamp: number }>;

    if (!validDates.length) return group.txns[0]?.date || '-';

    const sorted = validDates.sort((left, right) => left.timestamp - right.timestamp);
    const first = formatShortDate(sorted[0].raw);
    const last = formatShortDate(sorted[sorted.length - 1].raw);
    return first === last ? first : `${first} - ${last}`;
  }

  function sourceAccountPrimary(group: UnknownGroup): string {
    return group.sourceAccountLabel?.trim() || group.sourceLedgerAccount?.trim() || 'Manual entry';
  }

  function sourceAccountSecondary(group: UnknownGroup): string | null {
    const ledgerAccount = group.sourceLedgerAccount?.trim();
    if (!ledgerAccount) return null;
    if (ledgerAccount === sourceAccountPrimary(group)) return null;
    return ledgerAccount;
  }

  function previewTransactions(group: UnknownGroup): TxnRow[] {
    return group.txns.slice(0, 3);
  }

  function remainingTransactionCount(group: UnknownGroup): number {
    return Math.max(0, group.txns.length - previewTransactions(group).length);
  }

  function groupLabel(group: UnknownGroup): string {
    if (group.importAccountId) {
      return `${group.payeeDisplay} · ${sourceAccountPrimary(group)}`;
    }
    return group.payeeDisplay;
  }

  function warningGroupLabel(groupKey: string): string {
    const group = stage?.groups.find((candidate) => candidate.groupKey === groupKey);
    return group ? groupLabel(group) : groupKey;
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
      stage = await apiPost<UnknownStage>('/api/unknowns/stage-mappings', { stageId: stage.stageId, mappings: payload });
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
      stage = await apiPost<UnknownStage>('/api/unknowns/stage-mappings', { stageId, mappings: payload });
      stage = await apiPost<UnknownStage>('/api/unknowns/apply', { stageId });
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
    <section class="view-card review-summary-card">
      <div class="review-summary-head">
        <div>
          <p class="eyebrow">Review Queue</p>
          <h3>{(stage.groups?.length ?? 0) === 0 ? 'Nothing left to categorize' : 'Review by payee and source account'}</h3>
          <p class="muted">
            {(stage.groups?.length ?? 0) === 0
              ? `No uncategorized transactions were found in ${pathLabel(journalPath)}.`
              : `${stage.groups.length} groups across ${totalTransactionCount()} transactions in ${pathLabel(journalPath)}.`}
          </p>
        </div>
        <div class="review-summary-pills">
          <span class="pill warn">{needsGroupCount()} need category</span>
          <span class="pill ok">{readyGroupCount()} ready</span>
          <span class="pill">{totalTransactionCount()} transactions</span>
        </div>
      </div>

      {#if (stage.groups?.length ?? 0) > 0}
        <div class="review-toolbar">
          <div class="filters">
            <button class="btn" class:active-filter={statusFilter === 'needs'} on:click={() => (statusFilter = 'needs')}>
              Needs category
            </button>
            <button class="btn" class:active-filter={statusFilter === 'ready'} on:click={() => (statusFilter = 'ready')}>
              Ready
            </button>
            <button class="btn" class:active-filter={statusFilter === 'all'} on:click={() => (statusFilter = 'all')}>
              All
            </button>
          </div>

          {#if !stage.result}
            <div class="review-actions">
              <p class="muted review-hint">
                {#if stage.summary}
                  {stage.summary.groupCount ?? readyGroupCount()} groups staged. Estimated updates: {stage.summary.txnUpdates}.
                {:else}
                  Assign categories inline, preview the update count, then apply the changes.
                {/if}
              </p>
              <div class="actions">
                <button class="btn" disabled={loading || readyGroupCount() === 0} on:click={stageMappings}>Preview Changes</button>
                <button class="btn btn-primary" disabled={loading || readyGroupCount() === 0} on:click={applyMappings}>
                  Apply Changes
                </button>
              </div>
            </div>
          {/if}
        </div>
      {/if}
    </section>

    {#if stage.result}
      <section class="view-card result-card">
        <p class="eyebrow">Result</p>
        <h3>Changes applied</h3>
        <p class="muted">Updated transactions: {stage.result.updatedTxnCount}</p>
        {#if stage.result.warnings?.length}
          <h4>Warnings</h4>
          <ul class="warning-list">
            {#each stage.result.warnings as w}
              <li>{warningGroupLabel(w.groupKey)}: {w.warning}</li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#if (stage.groups?.length ?? 0) > 0}
      {#if visibleGroups().length === 0}
        <section class="view-card">
          <p class="muted">No review groups match the current filter.</p>
        </section>
      {:else}
        <section class="group-list">
          <div class="desktop-review-header" aria-hidden="true">
            <span>Status</span>
            <span>Activity</span>
            <span>From account</span>
            <span>Category</span>
            <span>Automation</span>
          </div>
          {#each visibleGroups() as group}
            <article class="view-card group-card" class:group-ready={groupStatus(group) === 'ready'} class:group-needs={groupStatus(group) === 'needs'}>
              <div class="group-grid">
                <div class="group-status-panel">
                  <p class="group-status-label">
                    {#if groupStatus(group) === 'ready'}
                      Ready to apply
                    {:else}
                      Needs category
                    {/if}
                  </p>
                  <p class="group-status-meta">
                    {group.txns.length} {group.txns.length === 1 ? 'txn' : 'txns'}
                  </p>
                </div>

                <div class="group-card-copy">
                  <div class="group-title-row">
                    <h4>{group.payeeDisplay}</h4>
                  </div>
                  <p class="group-meta">
                    {group.txns.length} {group.txns.length === 1 ? 'transaction' : 'transactions'} • {groupDateRange(group)}
                  </p>
                  <div class="transaction-peek">
                    {#each previewTransactions(group) as txn}
                      <span class="peek-pill">{formatShortDate(txn.date)} · {txn.amount || '-'}</span>
                    {/each}
                    {#if remainingTransactionCount(group) > 0}
                      <span class="peek-pill muted-pill">+{remainingTransactionCount(group)} more</span>
                    {/if}
                  </div>
                  <div class="group-supporting-pills">
                    {#if group.matchedRuleId}
                      <span class="pill ok">Rule suggestion</span>
                    {/if}
                    {#if group.importAccountDisplayName}
                      <span class="pill">{group.importAccountDisplayName}</span>
                    {/if}
                  </div>
                </div>

                <div class="assignment-side source-side">
                  <p class="assignment-label">From account</p>
                  <p class="assignment-value">{sourceAccountPrimary(group)}</p>
                  {#if sourceAccountSecondary(group)}
                    <p class="muted assignment-subvalue">{sourceAccountSecondary(group)}</p>
                  {/if}
                </div>

                <div class="assignment-side category-side">
                  <p class="assignment-label">Category</p>
                  <AccountCombobox
                    accounts={accounts}
                    value={effectiveAccountFor(group)}
                    placeholder="Choose category..."
                    onChange={(account) => setAccountForGroup(group.groupKey, account)}
                    onCreate={(seed) => void openCreateAccountForGroup(group.groupKey, seed)}
                  />
                  <div class="assignment-notes">
                    {#if group.suggestedAccount}
                      <span class="pill">{group.matchedRuleId ? 'Filled from rule' : 'Suggested'}</span>
                    {/if}
                  </div>
                </div>

                <div class="group-actions">
                  <button class="btn" on:click={() => openRuleModal(group.groupKey)}>
                    {group.matchedRuleId ? 'Edit rule' : 'Save as rule'}
                  </button>
                  <p class="muted action-note">
                    {#if group.matchedRuleId}
                      Refine the existing payee rule.
                    {:else}
                      Save this category for future imports.
                    {/if}
                  </p>
                </div>
              </div>

              <details class="group-details">
                <summary>{group.txns.length === 1 ? 'Show transaction details' : `Show ${group.txns.length} transaction details`}</summary>
                <div class="transaction-list">
                  {#each group.txns as txn}
                    <div class="transaction-item">
                      <div class="transaction-copy">
                        <p class="transaction-date">{formatShortDate(txn.date)}</p>
                        {#if txn.counterpartyAccount}
                          <p class="muted transaction-meta">{txn.counterpartyAccount}</p>
                        {/if}
                        <p class="transaction-line">{txn.line.trim()}</p>
                      </div>
                      <p class="transaction-amount">{txn.amount || '-'}</p>
                    </div>
                  {/each}
                </div>
              </details>
            </article>
          {/each}
        </section>
      {/if}
    {/if}
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
    flex-wrap: wrap;
  }

  .active-filter {
    background: #d8efff;
    border-color: #9ecfe9;
  }

  .review-summary-card,
  .result-card,
  .group-card {
    display: grid;
    gap: 1rem;
  }

  .review-summary-head {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .review-summary-pills,
  .assignment-notes {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
  }

  .review-toolbar {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
    padding-top: 1rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .review-actions {
    display: grid;
    gap: 0.55rem;
    justify-items: end;
  }

  .review-hint,
  .group-meta,
  .action-note,
  .transaction-date,
  .transaction-amount {
    margin: 0;
  }

  .review-hint {
    max-width: 34rem;
    text-align: right;
  }

  .actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .group-list {
    display: grid;
    gap: 1rem;
    margin-top: 1rem;
  }

  .desktop-review-header {
    display: none;
  }

  .group-card {
    border-color: rgba(10, 61, 89, 0.12);
  }

  .group-ready {
    border-color: rgba(12, 123, 89, 0.24);
  }

  .group-needs {
    border-color: rgba(218, 169, 79, 0.28);
  }

  .group-grid {
    display: grid;
    gap: 1rem;
  }

  .group-card-copy {
    min-width: 0;
  }

  .group-status-panel {
    display: grid;
    gap: 0.2rem;
    padding: 0.85rem 0.9rem;
    border-radius: 14px;
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(250, 251, 252, 0.85);
  }

  .group-ready .group-status-panel {
    background: rgba(237, 249, 244, 0.95);
    border-color: #9ad6be;
  }

  .group-needs .group-status-panel {
    background: rgba(255, 247, 234, 0.96);
    border-color: #f3cf96;
  }

  .group-status-label {
    margin: 0;
    font-size: 0.95rem;
    font-weight: 800;
    color: var(--brand-strong);
  }

  .group-status-meta {
    margin: 0;
    color: var(--muted-foreground);
    font-size: 0.82rem;
    font-weight: 600;
  }

  .group-title-row {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    flex-wrap: wrap;
  }

  .group-title-row h4 {
    margin: 0;
    font-size: 1.08rem;
  }

  .group-meta {
    color: var(--muted-foreground);
  }

  .transaction-peek {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    margin-top: 0.6rem;
  }

  .group-supporting-pills {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    margin-top: 0.75rem;
  }

  .peek-pill {
    display: inline-flex;
    align-items: center;
    padding: 0.28rem 0.55rem;
    border-radius: 999px;
    border: 1px solid rgba(10, 61, 89, 0.1);
    background: rgba(255, 255, 255, 0.8);
    color: var(--brand-strong);
    font-size: 0.82rem;
    font-weight: 600;
  }

  .muted-pill {
    color: var(--muted-foreground);
    border-style: dashed;
  }

  .assignment-side,
  .transaction-copy {
    min-width: 0;
  }

  .assignment-label {
    margin: 0 0 0.35rem;
    color: var(--muted-foreground);
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .assignment-value {
    margin: 0;
    font-weight: 700;
    color: var(--brand-strong);
  }

  .assignment-subvalue {
    margin: 0.2rem 0 0;
    font-size: 0.9rem;
  }

  .category-side {
    display: grid;
    gap: 0.55rem;
  }

  .group-actions {
    display: grid;
    gap: 0.55rem;
    justify-items: start;
    align-content: center;
  }

  .group-details {
    border-top: 1px solid rgba(10, 61, 89, 0.08);
    padding-top: 0.9rem;
  }

  .group-details summary {
    cursor: pointer;
    font-weight: 700;
    color: var(--brand-strong);
  }

  .transaction-list {
    display: grid;
    gap: 0.7rem;
    margin-top: 0.8rem;
  }

  .transaction-item {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.8rem 0.9rem;
    border-radius: 12px;
    border: 1px solid rgba(10, 61, 89, 0.08);
    background: rgba(255, 255, 255, 0.72);
  }

  .transaction-meta {
    margin: 0.2rem 0 0;
    font-size: 0.88rem;
  }

  .transaction-line {
    margin: 0.35rem 0 0;
    color: var(--muted-foreground);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.81rem;
    overflow-wrap: anywhere;
  }

  .transaction-amount {
    font-weight: 700;
    white-space: nowrap;
    color: var(--brand-strong);
  }

  .warning-list {
    display: grid;
    gap: 0.45rem;
    margin: 0;
    padding-left: 1.2rem;
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

  @media (min-width: 921px) {
    .desktop-review-header {
      display: grid;
      grid-template-columns: 10rem minmax(13rem, 1.2fr) minmax(12rem, 1fr) minmax(16rem, 1.3fr) minmax(11rem, 0.8fr);
      gap: 1rem;
      padding: 0 0.75rem;
      color: var(--muted-foreground);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .group-card {
      padding: 0.9rem 1rem;
    }

    .group-grid {
      grid-template-columns: 10rem minmax(13rem, 1.2fr) minmax(12rem, 1fr) minmax(16rem, 1.3fr) minmax(11rem, 0.8fr);
      align-items: start;
    }

    .assignment-label {
      font-size: 0.7rem;
    }

    .group-actions {
      padding-top: 1.4rem;
    }

    .group-details {
      margin-top: 0.25rem;
    }
  }

  @media (max-width: 920px) {
    .review-toolbar {
      flex-direction: column;
    }

    .review-actions {
      justify-items: start;
    }

    .review-hint {
      text-align: left;
    }
  }

  @media (max-width: 680px) {
    .review-summary-head,
    .transaction-item {
      flex-direction: column;
    }

    .transaction-amount {
      white-space: normal;
    }
  }
</style>
