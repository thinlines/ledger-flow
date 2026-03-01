<script lang="ts">
  import { onMount } from 'svelte';
  import { apiDelete, apiGet, apiPost } from '$lib/api';

  type Rule = {
    id: string;
    type: 'payee';
    pattern: string;
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

  let newPattern = '';
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

  async function createRule() {
    if (!newPattern || !newAccount) return;
    loading = true;
    error = '';
    try {
      await apiPost('/api/rules/payee', { payee: newPattern, account: newAccount });
      newPattern = '';
      await refresh();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function saveRule(rule: Rule) {
    loading = true;
    error = '';
    try {
      await apiPost(`/api/rules/${rule.id}`, {
        pattern: rule.pattern,
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
  <p class="subtitle">Order rules top-to-bottom. First matching rule wins.</p>
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
    <div class="grid-3 compact">
      <div class="field">
        <label for="newPattern">Payee Pattern</label>
        <input id="newPattern" bind:value={newPattern} placeholder="Coffee Shop" on:keydown={(e) => (e.key === 'Enter' ? createRule() : undefined)} />
      </div>
      <div class="field">
        <label for="newAccount">Target Account</label>
        <select id="newAccount" bind:value={newAccount}>
          <option value="">Select account...</option>
          {#each accounts as acct}
            <option value={acct}>{acct}</option>
          {/each}
        </select>
      </div>
      <div class="field end">
        <button class="btn btn-primary" disabled={loading || !newPattern || !newAccount} on:click={createRule}>Add Rule</button>
      </div>
    </div>
  </section>

  <section class="view-card">
    <p class="eyebrow">Evaluation Order</p>
    <p class="muted">Drag rows or use move buttons. Save Order persists priority.</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Payee Pattern</th>
            <th>Account</th>
            <th>Enabled</th>
            <th>Updated</th>
            <th>Move</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each rules as rule, i (rule.id)}
            <tr
              draggable="true"
              on:dragstart={() => onDragStart(i)}
              on:dragover|preventDefault
              on:drop={() => onDrop(i)}
            >
              <td>{i + 1}</td>
              <td><input bind:value={rule.pattern} /></td>
              <td>
                <select bind:value={rule.account}>
                  {#each accounts as acct}
                    <option value={acct}>{acct}</option>
                  {/each}
                </select>
              </td>
              <td><input type="checkbox" bind:checked={rule.enabled} /></td>
              <td>{rule.updatedAt}</td>
              <td class="moves">
                <button class="btn" on:click={() => moveRule(i, -1)} disabled={i === 0}>Up</button>
                <button class="btn" on:click={() => moveRule(i, 1)} disabled={i === rules.length - 1}>Down</button>
              </td>
              <td class="actions">
                <button class="btn" on:click={() => saveRule(rule)} disabled={loading}>Save</button>
                <button class="btn" on:click={() => removeRule(rule.id)} disabled={loading}>Delete</button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="actions">
      <button class="btn btn-primary" on:click={persistOrder} disabled={loading || rules.length < 2}>Save Order</button>
      <button class="btn" on:click={refresh} disabled={loading}>Reload</button>
    </div>
  </section>
{/if}

<style>
  .compact {
    gap: 0.8rem;
    align-items: end;
  }

  .end {
    display: flex;
    align-items: end;
  }

  .table-wrap {
    overflow: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  th, td {
    border-bottom: 1px solid var(--line);
    padding: 0.4rem;
    vertical-align: middle;
    text-align: left;
  }

  .moves, .actions {
    display: flex;
    gap: 0.35rem;
    flex-wrap: wrap;
  }
</style>
