<script lang="ts">
  import AccountCombobox from '$lib/components/AccountCombobox.svelte';
  import type { RuleAction, RuleCondition } from '$lib/components/rule-editor-types';

  export let conditions: RuleCondition[] = [{ field: 'payee', operator: 'exact', value: '', joiner: 'and' }];
  export let actions: RuleAction[] = [{ type: 'set_account', account: '' }];
  export let accounts: string[] = [];
  export let accountLabel = 'Then map to account';
  export let actionsTitle = 'Additional actions';
  export let allowAccountCreate = false;
  export let onAccountCreate: ((seed: string) => void) | null = null;

  function normalizeConditions(items: RuleCondition[]): RuleCondition[] {
    return items.map((c, i) => ({
      field: c.field ?? 'payee',
      operator: c.operator ?? 'exact',
      value: c.value ?? '',
      joiner: i === 0 ? 'and' : (c.joiner ?? 'and')
    }));
  }

  function getAccount(): string {
    return actions.find((a) => a.type === 'set_account')?.account ?? '';
  }

  function setAccount(account: string) {
    const idx = actions.findIndex((a) => a.type === 'set_account');
    if (idx >= 0) {
      actions[idx] = { type: 'set_account', account };
    } else {
      actions = [{ type: 'set_account', account }, ...actions];
    }
    actions = [...actions];
  }

  function addCondition() {
    conditions = [...conditions, { field: 'payee', operator: 'contains', value: '', joiner: 'and' }];
  }

  function removeCondition(index: number) {
    if (conditions.length <= 1) return;
    conditions = normalizeConditions(conditions.filter((_, i) => i !== index));
  }

  function toggleJoiner(index: number) {
    if (index <= 0) return;
    conditions = conditions.map((condition, i) =>
      i === index ? { ...condition, joiner: condition.joiner === 'and' ? 'or' : 'and' } : condition
    );
  }

  function createExtraAction(type: RuleAction['type'] = 'add_tag'): RuleAction {
    if (type === 'set_kv') return { type, key: '', value: '' };
    if (type === 'append_comment') return { type, text: '' };
    return { type, tag: '' };
  }

  function extraActions(): Array<{ action: RuleAction; index: number }> {
    return actions.map((action, index) => ({ action, index })).filter((item) => item.action.type !== 'set_account');
  }

  function addAction() {
    actions = [...actions, createExtraAction()];
  }

  function removeAction(index: number) {
    actions = actions.filter((_, i) => i !== index);
  }

  function setActionType(index: number, type: RuleAction['type']) {
    if (type === 'set_account') return;
    actions[index] = createExtraAction(type);
    actions = [...actions];
  }

  function setActionField(index: number, field: 'tag' | 'key' | 'value' | 'text', value: string) {
    actions[index] = { ...actions[index], [field]: value };
    actions = [...actions];
  }

  function handleAccountCreate(seed: string) {
    onAccountCreate?.(seed);
  }
</script>

<div class="conditions-block">
  {#each conditions as condition, i}
    <div class="condition-row">
      {#if i === 0}
        <span class="joiner-spacer" aria-hidden="true"></span>
      {:else}
        <button class="joiner-pill" type="button" on:click={() => toggleJoiner(i)}>{condition.joiner.toUpperCase()}</button>
      {/if}
      <select class="condition-field-select" bind:value={condition.field}>
        <option value="payee">Payee</option>
      </select>
      <select class="condition-operator-select" bind:value={condition.operator}>
        <option value="exact">is exactly</option>
        <option value="contains">contains</option>
      </select>
      <input class="condition-value-input" bind:value={condition.value} placeholder="abc123" />
      <button class="btn row-button" on:click={() => removeCondition(i)} disabled={conditions.length <= 1}>Remove</button>
    </div>
  {/each}
  <button class="btn" on:click={addCondition}>Add Condition...</button>
</div>

<div class="field">
  <p class="muted">{accountLabel}</p>
  <AccountCombobox
    {accounts}
    value={getAccount()}
    placeholder="Select account..."
    allowCreate={allowAccountCreate}
    onChange={setAccount}
    onCreate={handleAccountCreate}
  />
</div>

<div class="actions-block">
  <p class="muted">{actionsTitle}</p>
  {#each extraActions() as item}
    <div class="action-row">
      <select
        class="action-type-select"
        value={item.action.type}
        on:change={(e) => setActionType(item.index, (e.currentTarget as HTMLSelectElement).value as RuleAction['type'])}
      >
        <option value="add_tag">Add tag</option>
        <option value="set_kv">Set key/value</option>
        <option value="append_comment">Append comment</option>
      </select>
      {#if item.action.type === 'add_tag'}
        <input
          class="action-input"
          value={item.action.tag ?? ''}
          placeholder="reimbursable"
          on:input={(e) => setActionField(item.index, 'tag', (e.currentTarget as HTMLInputElement).value)}
        />
        <span class="action-spacer" aria-hidden="true"></span>
      {:else if item.action.type === 'set_kv'}
        <input
          class="action-input"
          value={item.action.key ?? ''}
          placeholder="project"
          on:input={(e) => setActionField(item.index, 'key', (e.currentTarget as HTMLInputElement).value)}
        />
        <input
          class="action-input"
          value={item.action.value ?? ''}
          placeholder="client-x"
          on:input={(e) => setActionField(item.index, 'value', (e.currentTarget as HTMLInputElement).value)}
        />
      {:else}
        <input
          class="action-input"
          value={item.action.text ?? ''}
          placeholder="auto-note text"
          on:input={(e) => setActionField(item.index, 'text', (e.currentTarget as HTMLInputElement).value)}
        />
        <span class="action-spacer" aria-hidden="true"></span>
      {/if}
      <button class="btn row-button" on:click={() => removeAction(item.index)}>Remove</button>
    </div>
  {/each}
  <button class="btn" on:click={addAction}>Add Action...</button>
</div>

<style>
  .conditions-block {
    display: grid;
    gap: 0.45rem;
    margin-bottom: 0.8rem;
  }

  .condition-row {
    display: grid;
    grid-template-columns: max-content max-content max-content minmax(20rem, 1fr) auto;
    gap: 0.45rem;
    align-items: center;
    min-width: 0;
  }

  .condition-row select,
  .condition-row input,
  .action-row select,
  .action-row input {
    width: 100%;
    min-width: 0;
  }

  .condition-field-select {
    min-width: 6.5rem;
  }

  .condition-operator-select {
    min-width: 8rem;
  }

  .condition-value-input {
    min-width: 20rem;
  }

  .joiner-spacer {
    display: block;
    width: 100%;
  }

  .joiner-pill {
    border: 1px solid var(--line);
    background: #eef6f4;
    border-radius: 999px;
    font-weight: 700;
    letter-spacing: 0.02em;
    padding: 0.25rem 0.5rem;
    cursor: pointer;
  }

  .joiner-pill:hover {
    background: #e2f0ec;
  }

  .actions-block {
    display: grid;
    gap: 0.45rem;
    margin-top: 0.5rem;
  }

  .action-row {
    display: grid;
    grid-template-columns: max-content minmax(12rem, 1fr) minmax(12rem, 1fr) auto;
    gap: 0.45rem;
    align-items: center;
    min-width: 0;
  }

  .action-type-select {
    min-width: 10rem;
  }

  .action-spacer {
    display: block;
    width: 100%;
  }

  .row-button {
    white-space: nowrap;
  }

  @media (max-width: 760px) {
    .condition-row,
    .action-row {
      grid-template-columns: 1fr;
    }

    .condition-value-input {
      min-width: 0;
    }
  }
</style>
