<script lang="ts">
  import { tick } from 'svelte';
  import AccountCombobox from '$lib/components/AccountCombobox.svelte';
  import type { RuleAction, RuleCondition } from '$lib/components/rule-editor-types';

  export let conditions: RuleCondition[] = [{ field: 'payee', operator: 'exact', value: '', joiner: 'and' }];
  export let actions: RuleAction[] = [{ type: 'set_account', account: '' }];
  export let accounts: string[] = [];
  export let accountLabel = 'Category';
  export let actionsTitle = 'Action';
  export let allowAccountCreate = false;
  export let onAccountCreate: ((seed: string) => void) | null = null;

  let actionTypeRefs: Array<HTMLSelectElement | null> = [];

  function defaultOperatorForField(field: RuleCondition['field']): RuleCondition['operator'] {
    return field === 'date' ? 'on_or_after' : 'exact';
  }

  function normalizeCondition(condition: RuleCondition, index: number): RuleCondition {
    const field = condition.field === 'date' ? 'date' : 'payee';
    const validOperator =
      field === 'date'
        ? ['on_or_after', 'before', 'between'].includes(condition.operator)
        : ['exact', 'contains'].includes(condition.operator);
    return {
      field,
      operator: validOperator ? condition.operator : defaultOperatorForField(field),
      value: condition.value ?? '',
      secondaryValue: condition.secondaryValue ?? '',
      joiner: index === 0 ? 'and' : (condition.joiner ?? 'and')
    };
  }

  function normalizeConditions(items: RuleCondition[]): RuleCondition[] {
    return items.map((condition, index) => normalizeCondition(condition, index));
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
    const previousJoiner = conditions.at(-1)?.joiner ?? 'and';
    conditions = [...conditions, { field: 'payee', operator: 'contains', value: '', joiner: previousJoiner }];
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

  function setConditionField(index: number, field: RuleCondition['field']) {
    const nextField = field === 'date' ? 'date' : 'payee';
    conditions[index] = {
      ...normalizeCondition(conditions[index], index),
      field: nextField,
      operator: defaultOperatorForField(nextField),
      value: '',
      secondaryValue: ''
    };
    conditions = [...conditions];
  }

  function setConditionOperator(index: number, operator: RuleCondition['operator']) {
    const current = normalizeCondition(conditions[index], index);
    conditions[index] = {
      ...current,
      operator,
      secondaryValue: operator === 'between' ? current.secondaryValue ?? '' : ''
    };
    conditions = [...conditions];
  }

  function createExtraAction(type: RuleAction['type'] = 'add_tag'): RuleAction {
    if (type === 'set_kv') return { type, key: '', value: '' };
    if (type === 'append_comment') return { type, text: '' };
    return { type, tag: '' };
  }

  async function addAction() {
    actions = [...actions, createExtraAction()];
    await tick();
    const lastIndex = actionTypeRefs.length - 1;
    actionTypeRefs[lastIndex]?.focus();
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

  $: extraItems = actions.map((action, index) => ({ action, index })).filter((item) => item.action.type !== 'set_account');
</script>

<section class="mb-4 grid gap-2.5">
  <p class="eyebrow mb-0">Match</p>
  <div class="grid gap-2.5">
    {#each conditions as condition, i}
      <div
        class="condition-row grid min-w-0 items-center gap-2 grid-cols-[max-content_max-content_max-content_minmax(20rem,1fr)_auto] max-[760px]:grid-cols-1"
      >
        {#if i === 0}
          <span class="block w-full" aria-hidden="true"></span>
        {:else}
          <button class="joiner-pill" type="button" on:click={() => toggleJoiner(i)}>{condition.joiner.toUpperCase()}</button>
        {/if}
        <select class="min-w-26" value={condition.field} on:change={(e) => setConditionField(i, (e.currentTarget as HTMLSelectElement).value as RuleCondition['field'])}>
          <option value="payee">Payee</option>
          <option value="date">Date</option>
        </select>
        <select class="min-w-32" value={condition.operator} on:change={(e) => setConditionOperator(i, (e.currentTarget as HTMLSelectElement).value as RuleCondition['operator'])}>
          {#if condition.field === 'date'}
            <option value="on_or_after">is on or after</option>
            <option value="between">is between</option>
            <option value="before">is before</option>
          {:else}
            <option value="exact">is exactly</option>
            <option value="contains">contains</option>
          {/if}
        </select>
        <div class="flex min-w-0 items-center gap-2">
          {#if condition.field === 'date'}
            <input class="min-w-80 max-[760px]:min-w-0" type="date" bind:value={condition.value} />
            {#if condition.operator === 'between'}
              <span class="shrink-0 text-sm text-muted-foreground">and</span>
              <input class="min-w-80 max-[760px]:min-w-0" type="date" bind:value={condition.secondaryValue} />
            {/if}
          {:else}
            <input class="min-w-80 max-[760px]:min-w-0" bind:value={condition.value} placeholder="Type a payee or keyword" />
          {/if}
        </div>
        <button class="btn row-button" type="button" on:click={() => removeCondition(i)} disabled={conditions.length <= 1}>
          Remove
        </button>
      </div>
    {/each}
    <button class="section-link" type="button" on:click|stopPropagation={addCondition}>Add another condition</button>
  </div>
</section>

<section class="grid gap-2.5 border-t border-card-edge pt-4">
  <p class="eyebrow mb-0">{actionsTitle}</p>
  <div class="grid gap-3">
    <div class="grid gap-2">
      <p class="m-0 text-sm font-semibold text-muted-foreground">{accountLabel}</p>
      <AccountCombobox
        {accounts}
        value={getAccount()}
        placeholder="Choose a category"
        allowCreate={allowAccountCreate}
        onChange={setAccount}
        onCreate={handleAccountCreate}
      />
    </div>

    {#if extraItems.length > 0}
      <div class="grid gap-2.5">
        {#each extraItems as item, rowIndex}
          <div
            class="action-row grid min-w-0 items-center gap-2 grid-cols-[max-content_minmax(12rem,1fr)_minmax(12rem,1fr)_auto] max-[760px]:grid-cols-1"
          >
            <select
              bind:this={actionTypeRefs[rowIndex]}
              class="min-w-40"
              value={item.action.type}
              on:change={(e) => setActionType(item.index, (e.currentTarget as HTMLSelectElement).value as RuleAction['type'])}
            >
              <option value="add_tag">Add tag</option>
              <option value="set_kv">Set key/value</option>
              <option value="append_comment">Append comment</option>
            </select>
            {#if item.action.type === 'add_tag'}
              <input
                value={item.action.tag ?? ''}
                placeholder="reimbursable"
                on:input={(e) => setActionField(item.index, 'tag', (e.currentTarget as HTMLInputElement).value)}
              />
              <span class="block w-full" aria-hidden="true"></span>
            {:else if item.action.type === 'set_kv'}
              <input
                value={item.action.key ?? ''}
                placeholder="project"
                on:input={(e) => setActionField(item.index, 'key', (e.currentTarget as HTMLInputElement).value)}
              />
              <input
                value={item.action.value ?? ''}
                placeholder="client-x"
                on:input={(e) => setActionField(item.index, 'value', (e.currentTarget as HTMLInputElement).value)}
              />
            {:else}
              <input
                value={item.action.text ?? ''}
                placeholder="Add a note"
                on:input={(e) => setActionField(item.index, 'text', (e.currentTarget as HTMLInputElement).value)}
              />
              <span class="block w-full" aria-hidden="true"></span>
            {/if}
            <button class="btn row-button" type="button" on:click={() => removeAction(item.index)}>Remove</button>
          </div>
        {/each}
      </div>
    {/if}

    <button class="section-link" type="button" on:click|stopPropagation={() => void addAction()}>Add another action</button>
  </div>
</section>

<style>
  .condition-row select,
  .condition-row input,
  .action-row select,
  .action-row input {
    min-width: 0;
  }

  .joiner-pill {
    border: 1px solid rgba(10, 61, 89, 0.1);
    background: rgba(238, 246, 244, 0.8);
    border-radius: 999px;
    font-weight: 700;
    letter-spacing: 0.02em;
    padding: 0.28rem 0.52rem;
    cursor: pointer;
  }

  .joiner-pill:hover {
    background: #e2f0ec;
  }

  .row-button {
    white-space: nowrap;
    padding: 0.55rem 0.76rem;
    background: transparent;
    border-color: rgba(10, 61, 89, 0.08);
    color: var(--muted-foreground);
    box-shadow: none;
    font-size: 0.92rem;
    font-weight: 600;
  }

  .row-button:hover {
    background: rgba(10, 61, 89, 0.04);
    color: var(--brand-strong);
  }

  .section-link {
    width: fit-content;
    border: 0;
    background: transparent;
    padding: 0.15rem 0;
    color: var(--brand-strong);
    font-weight: 700;
    font-size: 0.95rem;
    cursor: pointer;
  }

  .section-link:hover {
    color: #0c7b59;
  }

  .section-link:focus-visible {
    outline: 2px solid rgba(15, 95, 136, 0.35);
    outline-offset: 4px;
  }
</style>
