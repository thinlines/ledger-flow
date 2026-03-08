<script lang="ts">
  import { onMount } from 'svelte';
  import RuleEditor from '$lib/components/RuleEditor.svelte';
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

  let newConditions: RuleCondition[] = createDefaultRuleConditions();
  let newActions: RuleAction[] = createDefaultRuleActions();
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
      rules = rulesData.rules.map(normalizeRule);
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
      rules = data.rules.map(normalizeRule);
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
    <RuleEditor bind:conditions={newConditions} bind:actions={newActions} {accounts} />
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

          <RuleEditor bind:conditions={rule.conditions} bind:actions={rule.actions} {accounts} />

          <div class="rule-actions">
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
</style>
