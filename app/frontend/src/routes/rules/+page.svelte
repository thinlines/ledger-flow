<script lang="ts">
  import { onMount } from 'svelte';
  import { apiDelete, apiGet, apiPost } from '$lib/api';

  type RuleCondition = {
    field: 'payee';
    operator: 'exact' | 'contains';
    value: string;
  };

  type Rule = {
    id: string;
    type: 'match';
    conditions: RuleCondition[];
    account: string;
    enabled: boolean;
    position: number;
    updatedAt: string;
  };

  let initialized = false;
  let error = '';
  let loading = false;
  let rules: Rule[] = [];
  let accounts: string[] = [];

  let newConditions: RuleCondition[] = [{ field: 'payee', operator: 'exact', value: '' }];
  let newAccount = '';
  let dragIndex: number | null = null;

  onMount(async () => {
    await refresh();
  });

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
      rules = rulesData.rules;
      accounts = accountsData.accounts;
      if (!newAccount && accounts.length) newAccount = accounts[0];
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function addNewCondition() {
    newConditions = [...newConditions, { field: 'payee', operator: 'contains', value: '' }];
  }

  function removeNewCondition(index: number) {
    if (newConditions.length <= 1) return;
    newConditions = newConditions.filter((_, i) => i !== index);
  }

  function addConditionToRule(rule: Rule) {
    rule.conditions = [...rule.conditions, { field: 'payee', operator: 'contains', value: '' }];
    rules = [...rules];
  }

  function removeConditionFromRule(rule: Rule, index: number) {
    if (rule.conditions.length <= 1) return;
    rule.conditions = rule.conditions.filter((_, i) => i !== index);
    rules = [...rules];
  }

  function sanitizedConditions(conditions: RuleCondition[]): RuleCondition[] {
    return conditions.map((c) => ({ ...c, value: c.value.trim() })).filter((c) => c.value.length > 0);
  }

  async function createRule() {
    const cleaned = sanitizedConditions(newConditions);
    if (!cleaned.length || !newAccount) return;
    loading = true;
    error = '';
    try {
      await apiPost('/api/rules', { conditions: cleaned, account: newAccount, enabled: true });
      newConditions = [{ field: 'payee', operator: 'exact', value: '' }];
      await refresh();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function saveRule(rule: Rule) {
    const cleaned = sanitizedConditions(rule.conditions);
    loading = true;
    error = '';
    try {
      await apiPost(`/api/rules/${rule.id}`, {
        conditions: cleaned,
        account: rule.account,
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
      rules = data.rules;
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

  function onDrop(index: number) {
    if (dragIndex === null || dragIndex === index) return;
    const reordered = [...rules];
    const [moved] = reordered.splice(dragIndex, 1);
    reordered.splice(index, 0, moved);
    rules = reordered;
    dragIndex = null;
  }
</script>

<section class="view-card hero">
  <p class="eyebrow">Rules</p>
  <h2 class="page-title">Match Rule Manager</h2>
  <p class="subtitle">Create Outlook-style conditions and order rules top-to-bottom. First match wins.</p>
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
    <p class="eyebrow">Create Rule</p>
    <div class="conditions-block">
      {#each newConditions as condition, i}
        <div class="condition-row">
          <select bind:value={condition.field}>
            <option value="payee">Payee</option>
          </select>
          <select bind:value={condition.operator}>
            <option value="exact">is exactly</option>
            <option value="contains">contains</option>
          </select>
          <input bind:value={condition.value} placeholder="abc123" on:keydown={(e) => (e.key === 'Enter' ? createRule() : undefined)} />
          <button class="btn" on:click={() => removeNewCondition(i)} disabled={newConditions.length <= 1}>Remove</button>
        </div>
      {/each}
      <button class="btn" on:click={addNewCondition}>Add Condition...</button>
    </div>
    <div class="create-actions">
      <div class="field">
        <label for="newAccount">Then map to account</label>
        <select id="newAccount" bind:value={newAccount}>
          <option value="">Select account...</option>
          {#each accounts as acct}
            <option value={acct}>{acct}</option>
          {/each}
        </select>
      </div>
      <button class="btn btn-primary" disabled={loading || !newAccount || !sanitizedConditions(newConditions).length} on:click={createRule}>
        Add Rule
      </button>
    </div>
  </section>

  <section class="view-card">
    <p class="eyebrow">Evaluation Order</p>
    <p class="muted">Drag rows or use move buttons. Save Order persists priority.</p>
    <div class="rule-list">
      {#each rules as rule, i (rule.id)}
        <article
          class="rule-card"
          draggable="true"
          on:dragstart={() => onDragStart(i)}
          on:dragover|preventDefault
          on:drop={() => onDrop(i)}
        >
          <div class="rule-head">
            <p><strong>#{i + 1}</strong> Rule {rule.id}</p>
            <p class="muted">Updated: {rule.updatedAt}</p>
          </div>
          <div class="conditions-block">
            {#each rule.conditions as condition, cIndex}
              <div class="condition-row">
                <select bind:value={condition.field}>
                  <option value="payee">Payee</option>
                </select>
                <select bind:value={condition.operator}>
                  <option value="exact">is exactly</option>
                  <option value="contains">contains</option>
                </select>
                <input bind:value={condition.value} placeholder="abc123" />
                <button class="btn" on:click={() => removeConditionFromRule(rule, cIndex)} disabled={rule.conditions.length <= 1}>Remove</button>
              </div>
            {/each}
            <button class="btn" on:click={() => addConditionToRule(rule)}>Add Condition...</button>
          </div>
          <div class="rule-actions">
            <div class="field">
              <label for={`rule-account-${rule.id}`}>Then map to account</label>
              <select id={`rule-account-${rule.id}`} bind:value={rule.account}>
                {#each accounts as acct}
                  <option value={acct}>{acct}</option>
                {/each}
              </select>
            </div>
            <label class="enabled">
              <input type="checkbox" bind:checked={rule.enabled} />
              Enabled
            </label>
            <button class="btn" on:click={() => moveRule(i, -1)} disabled={i === 0}>Up</button>
            <button class="btn" on:click={() => moveRule(i, 1)} disabled={i === rules.length - 1}>Down</button>
            <button class="btn btn-primary" on:click={() => saveRule(rule)} disabled={loading}>Save</button>
            <button class="btn" on:click={() => removeRule(rule.id)} disabled={loading}>Delete</button>
          </div>
        </article>
      {/each}
    </div>
    <div class="actions">
      <button class="btn btn-primary" on:click={persistOrder} disabled={loading || rules.length < 2}>Save Order</button>
      <button class="btn" on:click={refresh} disabled={loading}>Reload</button>
    </div>
  </section>
{/if}

<style>
  .conditions-block {
    display: grid;
    gap: 0.45rem;
  }

  .condition-row {
    display: grid;
    grid-template-columns: 10rem 9rem 1fr auto;
    gap: 0.45rem;
    align-items: center;
  }

  .create-actions {
    margin-top: 0.7rem;
    display: flex;
    gap: 0.6rem;
    align-items: end;
    flex-wrap: wrap;
  }

  .rule-list {
    display: grid;
    gap: 0.75rem;
  }

  .rule-card {
    border: 1px solid var(--line);
    border-radius: 12px;
    background: #fdfefe;
    padding: 0.7rem;
    display: grid;
    gap: 0.6rem;
  }

  .rule-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .rule-head p {
    margin: 0;
  }

  .rule-actions {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    align-items: end;
  }

  .enabled {
    display: inline-flex;
    gap: 0.3rem;
    align-items: center;
    font-weight: 600;
  }

  @media (max-width: 760px) {
    .condition-row {
      grid-template-columns: 1fr;
    }
  }
</style>
