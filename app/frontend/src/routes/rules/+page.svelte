<script lang="ts">
  import { onMount } from 'svelte';
  import CreateAccountModal from '$lib/components/CreateAccountModal.svelte';
  import RuleEditor from '$lib/components/RuleEditor.svelte';
  import SavedRuleAccordionItem from '$lib/components/SavedRuleAccordionItem.svelte';
  import type { RuleAction, RuleCondition } from '$lib/components/rule-editor-types';
  import { apiDelete, apiGet, apiPost } from '$lib/api';
  import {
    createDefaultRuleActions,
    createDefaultRuleConditions,
    ensureSetAccountAction,
    normalizeRule,
    sanitizedActions,
    sanitizedConditions
  } from '$lib/rules';

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
  let error = '';
  let loading = false;
  let rules: Rule[] = [];
  let accounts: string[] = [];
  let expandedRuleId: string | null = null;

  let newConditions: RuleCondition[] = createDefaultRuleConditions();
  let newActions: RuleAction[] = createDefaultRuleActions();
  let dragIndex: number | null = null;

  let showCreateAccountModal = false;
  let newAccountName = '';
  let newAccountType = 'Expense';
  let createAccountError = '';
  let createAccountContext: { mode: 'new-rule' | 'existing-rule'; ruleId: string | null } = {
    mode: 'new-rule',
    ruleId: null
  };

  onMount(async () => {
    await refresh();
  });

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

  function setActionsAccount(actions: RuleAction[], account: string): RuleAction[] {
    const nextActions = ensureSetAccountAction(actions, account);
    const setAccountIndex = nextActions.findIndex((action) => action.type === 'set_account');
    nextActions[setAccountIndex] = { type: 'set_account', account };
    return nextActions;
  }

  function syncExpandedRule(nextRules: Rule[]) {
    if (expandedRuleId && nextRules.some((rule) => rule.id === expandedRuleId)) return;
    expandedRuleId = nextRules[0]?.id ?? null;
  }

  async function refresh() {
    error = '';
    loading = true;
    try {
      const state = await apiGet<{ initialized: boolean }>('/api/app/state');
      initialized = state.initialized;
      if (!initialized) return;
      const [rulesData, accountsData] = await Promise.all([
        apiGet<{ rules: Rule[] }>('/api/rules'),
        apiGet<{ accounts: string[] }>('/api/accounts')
      ]);
      const nextRules = rulesData.rules.map(normalizeRule);
      rules = nextRules;
      syncExpandedRule(nextRules);
      accounts = accountsData.accounts;
      newActions = ensureSetAccountAction(newActions, accountsData.accounts[0] ?? '');
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function createRule() {
    const cleanedConditions = sanitizedConditions(newConditions);
    const cleanedActions = sanitizedActions(newActions);
    if (!cleanedConditions.length || !cleanedActions.length) return;

    loading = true;
    error = '';
    try {
      await apiPost('/api/rules', { conditions: cleanedConditions, actions: cleanedActions, enabled: true });
      newConditions = createDefaultRuleConditions();
      newActions = createDefaultRuleActions(accounts[0] ?? '');
      await refresh();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function saveRule(rule: Rule) {
    const cleanedConditions = sanitizedConditions(rule.conditions);
    const cleanedActions = sanitizedActions(rule.actions);

    loading = true;
    error = '';
    try {
      await apiPost(`/api/rules/${rule.id}`, {
        conditions: cleanedConditions,
        actions: cleanedActions,
        enabled: rule.enabled
      });
      await refresh();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function removeRule(ruleId: string) {
    loading = true;
    error = '';
    try {
      await apiDelete(`/api/rules/${ruleId}`);
      await refresh();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function persistOrder() {
    loading = true;
    error = '';
    try {
      const orderedIds = rules.map((r) => r.id);
      const data = await apiPost<{ rules: Rule[] }>('/api/rules/reorder', { orderedIds });
      const nextRules = data.rules.map(normalizeRule);
      rules = nextRules;
      syncExpandedRule(nextRules);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function moveRule(index: number, direction: -1 | 1) {
    const next = index + direction;
    if (next < 0 || next >= rules.length) return;
    const reordered = [...rules];
    [reordered[index], reordered[next]] = [reordered[next], reordered[index]];
    rules = reordered;
  }

  function onDragStart(index: number) {
    dragIndex = index;
  }

  function onDragEnd() {
    dragIndex = null;
  }

  function onDrop(index: number) {
    if (dragIndex === null || dragIndex === index) return;
    const reordered = [...rules];
    const [moved] = reordered.splice(dragIndex, 1);
    reordered.splice(index, 0, moved);
    rules = reordered;
    dragIndex = null;
  }

  function toggleRule(ruleId: string) {
    expandedRuleId = expandedRuleId === ruleId ? null : ruleId;
  }

  async function openCreateAccountModal(
    initialName = '',
    context: { mode: 'new-rule' | 'existing-rule'; ruleId: string | null }
  ) {
    createAccountContext = context;
    newAccountName = initialName;
    updateInferredTypeFromName();
    createAccountError = '';
    showCreateAccountModal = true;
  }

  function closeCreateAccountModal() {
    createAccountError = '';
    showCreateAccountModal = false;
  }

  async function openCreateAccountForNewRule(initialName = '') {
    await openCreateAccountModal(initialName, { mode: 'new-rule', ruleId: null });
  }

  async function openCreateAccountForExistingRule(ruleId: string, initialName = '') {
    await openCreateAccountModal(initialName, { mode: 'existing-rule', ruleId });
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

      if (createAccountContext.mode === 'new-rule') {
        newActions = setActionsAccount(newActions, newAccountName);
      } else if (createAccountContext.ruleId) {
        rules = rules.map((rule) =>
          rule.id === createAccountContext.ruleId
            ? { ...rule, actions: setActionsAccount(rule.actions, newAccountName) }
            : rule
        );
      }

      showCreateAccountModal = false;
    } catch (e) {
      createAccountError = String(e);
    } finally {
      loading = false;
    }
  }
</script>

<section class="view-card hero">
  <p class="eyebrow">Automation</p>
  <h2 class="page-title">Reusable categorization rules</h2>
  <p class="subtitle">Save repeat decisions once and let future imports arrive with less cleanup.</p>
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
    <p class="eyebrow">New Rule</p>
    <RuleEditor
      bind:conditions={newConditions}
      bind:actions={newActions}
      {accounts}
      accountLabel="Category"
      actionsTitle="Add another action"
      allowAccountCreate={true}
      onAccountCreate={(seed) => void openCreateAccountForNewRule(seed)}
    />
    <div class="create-actions">
      <button
        class="btn btn-primary"
        disabled={loading || !sanitizedConditions(newConditions).length || !sanitizedActions(newActions).length}
        on:click={createRule}
      >
        Add Rule
      </button>
    </div>
  </section>

  <section class="view-card saved-rules-card">
    <div class="section-head">
      <div class="section-copy">
        <p class="eyebrow">Saved Rules</p>
        <h3>Evaluation order</h3>
        <p class="muted">Use the handle to reorder priority. Expand a rule to edit it.</p>
      </div>
      <div class="section-actions">
        <span class="rule-count">{rules.length} {rules.length === 1 ? 'rule' : 'rules'}</span>
        <button class="btn btn-primary" on:click={persistOrder} disabled={loading || rules.length < 2}>Save Order</button>
        <button class="btn" on:click={refresh} disabled={loading}>Reload</button>
      </div>
    </div>

    {#if rules.length === 0}
      <div class="empty-state">
        <p class="empty-title">No saved rules yet.</p>
        <p class="muted">Create a rule above to start automating categorization.</p>
      </div>
    {:else}
      <div class="rule-list">
        {#each rules as rule, i (rule.id)}
          <SavedRuleAccordionItem
            ruleId={rule.id}
            ruleIndex={i}
            ruleCount={rules.length}
            bind:conditions={rule.conditions}
            bind:actions={rule.actions}
            {accounts}
            expanded={expandedRuleId === rule.id}
            {loading}
            onToggle={() => toggleRule(rule.id)}
            onSave={() => saveRule(rule)}
            onRemove={() => removeRule(rule.id)}
            onMoveUp={() => moveRule(i, -1)}
            onMoveDown={() => moveRule(i, 1)}
            onDragStart={() => onDragStart(i)}
            onDragEnd={onDragEnd}
            onDrop={() => onDrop(i)}
            onAccountCreate={(seed) => void openCreateAccountForExistingRule(rule.id, seed)}
          />
        {/each}
      </div>
    {/if}
  </section>
{/if}

{#if showCreateAccountModal}
  <CreateAccountModal
    bind:accountName={newAccountName}
    bind:accountType={newAccountType}
    error={createAccountError}
    {loading}
    onNameInput={updateInferredTypeFromName}
    onClose={closeCreateAccountModal}
    onSubmit={createAccountAndContinue}
  />
{/if}

<style>
  section.view-card {
    display: grid;
    gap: 0.95rem;
  }

  .create-actions {
    display: flex;
    gap: 0.6rem;
    align-items: end;
    flex-wrap: wrap;
  }

  .saved-rules-card {
    display: grid;
    gap: 0.95rem;
  }

  .section-head {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
    flex-wrap: wrap;
    padding-bottom: 0.1rem;
    border-bottom: 1px solid rgba(10, 61, 89, 0.08);
  }

  .section-copy {
    display: grid;
    gap: 0.28rem;
  }

  .section-copy h3,
  .section-copy p {
    margin: 0;
  }

  .section-copy h3 {
    font-size: 1.22rem;
    line-height: 1.2;
  }

  .section-copy .muted {
    max-width: 40rem;
    font-size: 0.96rem;
  }

  .section-actions {
    display: flex;
    gap: 0.6rem;
    align-items: center;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .rule-count {
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.65);
    border: 1px solid rgba(10, 61, 89, 0.08);
    padding: 0.38rem 0.72rem;
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--muted-foreground);
  }

  .rule-list {
    display: grid;
    gap: 0.75rem;
  }

  .empty-state {
    border: 1px dashed rgba(10, 61, 89, 0.14);
    border-radius: 14px;
    padding: 1rem;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.72), rgba(247, 251, 255, 0.56));
  }

  .empty-state p {
    margin: 0;
  }

  .empty-title {
    font-weight: 700;
    margin-bottom: 0.25rem;
  }

  @media (max-width: 760px) {
    .section-actions {
      justify-content: flex-start;
    }
  }
</style>
