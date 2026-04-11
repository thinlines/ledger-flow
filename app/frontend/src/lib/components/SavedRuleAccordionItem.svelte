<script lang="ts">
  import RuleEditor from '$lib/components/RuleEditor.svelte';
  import type { RuleAction, RuleCondition } from '$lib/components/rule-editor-types';
  import { suggestedRuleName } from '$lib/rules';

  export let ruleId = '';
  export let ruleIndex = 0;
  export let ruleCount = 0;
  export let name = '';
  export let conditions: RuleCondition[] = [];
  export let actions: RuleAction[] = [];
  export let accounts: string[] = [];
  export let dirty = false;
  export let expanded = false;
  export let highlighted = false;
  export let loading = false;
  export let onToggle: () => void = () => {};
  export let onSave: () => void | Promise<void> = () => {};
  export let onNameCommit: () => void | Promise<void> = () => {};
  export let onRemove: () => void | Promise<void> = () => {};
  export let onApplyHistory: () => void | Promise<void> = () => {};
  export let onMoveUp: () => void = () => {};
  export let onMoveDown: () => void = () => {};
  export let onDragStart: () => void = () => {};
  export let onDragEnd: () => void = () => {};
  export let onDrop: () => void = () => {};
  export let onAccountCreate: (seed: string) => void = () => {};

  let isDragOver = false;
  let dragDepth = 0;

  $: conditionSummary = summarizeConditions(conditions);
  $: actionSummary = summarizeActions(actions);
  $: namePlaceholder = suggestedRuleName(conditions);

  function summarizeConditions(items: RuleCondition[]): string {
    const parts = items
      .map((condition, index) => {
        const value = condition.value.trim();
        if (!value) return '';
        const joiner = index === 0 ? '' : `${(condition.joiner ?? 'and').toUpperCase()} `;
        if (condition.field === 'date') {
          if (condition.operator === 'on_or_after') return `${joiner}Date is on or after ${value}`;
          if (condition.operator === 'before') return `${joiner}Date is before ${value}`;
          if (condition.operator === 'between' && condition.secondaryValue?.trim()) {
            return `${joiner}Date is between ${value} and ${condition.secondaryValue.trim()}`;
          }
          return `${joiner}Date is ${value}`;
        }
        const operator = condition.operator === 'contains' ? 'contains' : 'is';
        return `${joiner}Payee ${operator} "${value}"`;
      })
      .filter(Boolean);
    return parts.join(' ') || 'No conditions yet';
  }

  function summarizeActions(items: RuleAction[]): string {
    const parts = items
      .map((action) => {
        if (action.type === 'set_account' && action.account?.trim()) return `Maps to ${action.account.trim()}`;
        if (action.type === 'add_tag' && action.tag?.trim()) return `Tag ${action.tag.trim()}`;
        if (action.type === 'set_kv' && action.key?.trim() && action.value?.trim()) {
          return `${action.key.trim()}=${action.value.trim()}`;
        }
        if (action.type === 'append_comment' && action.text?.trim()) return `Note ${truncate(action.text.trim())}`;
        return '';
      })
      .filter(Boolean);
    return parts.join(' • ') || 'No actions yet';
  }

  function truncate(value: string, maxLength = 28): string {
    if (value.length <= maxLength) return value;
    return `${value.slice(0, maxLength - 3)}...`;
  }

  function handleDragStart(event: DragEvent) {
    event.stopPropagation();
    const dataTransfer = event.dataTransfer;
    if (dataTransfer) {
      dataTransfer.setData('text/plain', ruleId);
      dataTransfer.effectAllowed = 'move';
    }
    onDragStart();
  }

  function handleDragEnd() {
    dragDepth = 0;
    isDragOver = false;
    onDragEnd();
  }

  function handleDragEnter(event: DragEvent) {
    event.preventDefault();
    dragDepth += 1;
    isDragOver = true;
  }

  function handleDragLeave() {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) isDragOver = false;
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    dragDepth = 0;
    isDragOver = false;
    onDrop();
  }
</script>

<article
  id={`saved-rule-${ruleId}`}
  class="rule-card"
  class:rule-card-expanded={expanded}
  class:rule-card-highlighted={highlighted}
  class:rule-card-drop-target={isDragOver}
  on:dragenter={handleDragEnter}
  on:dragleave={handleDragLeave}
  on:dragover|preventDefault
  on:drop={handleDrop}
>
  <div class="grid items-start gap-3.5 px-3.5 py-3.5 grid-cols-[auto_minmax(0,1fr)] max-[760px]:gap-2.5 max-[760px]:p-3">
    <button
      type="button"
      class="drag-handle"
      draggable="true"
      aria-label="Drag to reorder rule"
      title="Drag to reorder rule"
      on:dragstart={handleDragStart}
      on:dragend={handleDragEnd}
    >
      <span class="drag-dot"></span>
      <span class="drag-dot"></span>
      <span class="drag-dot"></span>
      <span class="drag-dot"></span>
      <span class="drag-dot"></span>
      <span class="drag-dot"></span>
    </button>

    <div class="min-w-0">
      <button
        type="button"
        class="block w-full cursor-pointer rounded-xl border-0 bg-transparent p-0 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-brand/40"
        aria-expanded={expanded}
        on:click={onToggle}
      >
        <div class="flex items-center justify-between gap-3.5 max-[760px]:flex-col max-[760px]:items-start">
          <div class="grid min-w-0 gap-0.5">
            <div class="flex flex-wrap items-center gap-2">
              <p class="m-0 wrap-anywhere text-base font-bold leading-tight text-brand-strong">
                {name || namePlaceholder || 'Untitled rule'}
              </p>
              {#if highlighted}
                <span class="highlight-pill">History updated</span>
              {/if}
              {#if dirty}
                <span class="dirty-pill">Unsaved changes</span>
              {/if}
            </div>
            {#if !expanded}
              <p
                class="m-0 truncate text-sm leading-snug max-[760px]:line-clamp-2 max-[760px]:whitespace-normal"
                title={conditionSummary}
              >
                {conditionSummary}
              </p>
              <p
                class="m-0 truncate text-sm leading-snug text-muted-foreground max-[760px]:line-clamp-2 max-[760px]:whitespace-normal"
                title={actionSummary}
              >
                {actionSummary}
              </p>
            {/if}
          </div>

          <div class="flex shrink-0 items-center max-[760px]:justify-start">
            <span class="chevron" class:chevron-expanded={expanded} aria-hidden="true"></span>
          </div>
        </div>
      </button>

      {#if expanded}
        <div class="mt-3 grid gap-4 border-t border-card-edge pt-4">
          <div class="field">
            <label for={`rule-name-${ruleId}`}>Rule Name</label>
            <input
              id={`rule-name-${ruleId}`}
              bind:value={name}
              placeholder={namePlaceholder || 'Coffee Shop'}
              on:change={() => void onNameCommit()}
              on:keydown={(event) =>
                event.key === 'Enter' ? ((event.preventDefault(), (event.currentTarget as HTMLInputElement).blur())) : undefined}
            />
          </div>

          <RuleEditor
            bind:conditions
            bind:actions
            {accounts}
            accountLabel="Category"
            actionsTitle="Action"
            allowAccountCreate={true}
            onAccountCreate={(seed) => void onAccountCreate(seed)}
          />

          <div
            class="flex flex-wrap items-center justify-between gap-3 border-t border-card-edge pt-3 max-[760px]:items-start"
          >
            <div class="flex flex-wrap items-center gap-1.5">
              <button class="btn utility-btn" on:click={() => onMoveUp()} disabled={ruleIndex === 0}>Move Earlier</button>
              <button class="btn utility-btn" on:click={() => onMoveDown()} disabled={ruleIndex === ruleCount - 1}>
                Move Later
              </button>
              <button class="btn utility-btn" on:click={() => void onApplyHistory()} disabled={loading}>
                Apply to Past Transactions
              </button>
            </div>

            <div class="flex flex-wrap items-center gap-1.5 ml-auto max-[760px]:ml-0">
              <button class="btn utility-btn" on:click={() => void onRemove()} disabled={loading}>Delete</button>
              <button class="btn btn-primary" on:click={() => void onSave()} disabled={loading}>Save Changes</button>
            </div>
          </div>
        </div>
      {/if}
    </div>
  </div>
</article>

<style>
  .rule-card {
    border: 1px solid rgba(10, 61, 89, 0.1);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.88);
    transition:
      border-color 0.16s ease,
      box-shadow 0.16s ease,
      transform 0.16s ease;
  }

  .rule-card:hover {
    border-color: rgba(10, 61, 89, 0.16);
    box-shadow: 0 8px 18px rgba(10, 61, 89, 0.04);
  }

  .rule-card-expanded {
    border-color: rgba(15, 95, 136, 0.18);
    background: #ffffff;
    box-shadow: 0 12px 26px rgba(10, 61, 89, 0.06);
  }

  .rule-card-highlighted {
    border-color: rgba(12, 123, 89, 0.34);
    box-shadow:
      0 0 0 3px rgba(12, 123, 89, 0.08),
      0 12px 26px rgba(10, 61, 89, 0.06);
  }

  .rule-card-drop-target {
    border-color: rgba(12, 123, 89, 0.7);
    box-shadow: 0 0 0 3px rgba(12, 123, 89, 0.12);
    transform: translateY(-1px);
  }

  .drag-handle {
    width: 2rem;
    min-height: 2.7rem;
    padding: 0.3rem;
    border: 1px solid rgba(10, 61, 89, 0.08);
    border-radius: 12px;
    background: rgba(247, 251, 255, 0.9);
    display: grid;
    grid-template-columns: repeat(2, 0.32rem);
    justify-content: center;
    align-content: center;
    gap: 0.25rem;
    cursor: grab;
    flex-shrink: 0;
    transition:
      background 0.16s ease,
      border-color 0.16s ease,
      transform 0.16s ease;
  }

  .drag-handle:active {
    cursor: grabbing;
  }

  .drag-handle:hover {
    background: #eef6ff;
    border-color: rgba(15, 95, 136, 0.18);
    transform: translateY(-1px);
  }

  .drag-handle:focus-visible {
    outline: 2px solid rgba(15, 95, 136, 0.32);
    outline-offset: 3px;
  }

  .drag-dot {
    width: 0.32rem;
    height: 0.32rem;
    border-radius: 999px;
    background: rgba(15, 95, 136, 0.55);
  }

  .dirty-pill {
    border-radius: 999px;
    background: rgba(255, 244, 220, 0.92);
    border: 1px solid rgba(218, 169, 79, 0.28);
    color: #8b5b12;
    padding: 0.2rem 0.48rem;
    font-size: 0.73rem;
    font-weight: 700;
    line-height: 1.2;
  }

  .highlight-pill {
    border-radius: 999px;
    background: rgba(230, 247, 239, 0.96);
    border: 1px solid rgba(12, 123, 89, 0.2);
    color: #0a6a50;
    padding: 0.2rem 0.48rem;
    font-size: 0.73rem;
    font-weight: 700;
    line-height: 1.2;
  }

  .chevron {
    width: 0.78rem;
    height: 0.78rem;
    border-right: 2px solid rgba(15, 95, 136, 0.65);
    border-bottom: 2px solid rgba(15, 95, 136, 0.65);
    transform: rotate(45deg);
    transition: transform 0.16s ease;
  }

  .chevron-expanded {
    transform: rotate(225deg);
  }

  .utility-btn {
    background: transparent;
    border-color: rgba(10, 61, 89, 0.08);
    color: var(--muted-foreground);
    box-shadow: none;
    font-weight: 600;
    padding: 0.58rem 0.84rem;
  }

  .utility-btn:hover {
    background: rgba(10, 61, 89, 0.04);
    color: var(--brand-strong);
  }
</style>
