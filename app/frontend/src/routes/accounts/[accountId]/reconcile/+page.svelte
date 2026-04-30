<script lang="ts">
  // Two-step (Setup → Review) reconciliation surface scoped to a single tracked
  // balance-sheet account. The route owns the live diff math and defers the
  // journal write to the 8a endpoint. Setup sits at the top, Review below;
  // Review activates once Setup is valid. Successful reconcile navigates to
  // /transactions?account=<id> and invalidates the accounts list so the
  // future Last-reconciled line refreshes when 8f lands.
  //
  // The Reconcile button sits behind two gates: every diff field must parse,
  // and the parsed difference must equal zero (string-decimal compare so the
  // page cannot enable Reconcile when the backend would 422).
  import { goto, invalidate } from '$app/navigation';
  import { onDestroy } from 'svelte';
  import { apiGet } from '$lib/api';
  import { formatCurrency } from '$lib/format';
  import {
    decimalAddAll,
    decimalEquals,
    decimalSub,
    isValidAmount,
    parseAmount
  } from '$lib/currency-parser';
  import type { PageData } from './$types';
  import type { ReconcileContextResponse } from './+page';

  export let data: PageData;

  type ReconcileError = {
    outcome?: string;
    message?: string;
    expected?: string | null;
    actual?: string | null;
    rawError?: string;
  };

  const { account, accountKind } = data;

  let periodStart = data.initialPeriodStart;
  let periodEnd = data.initialPeriodEnd;
  let closingBalance = '';

  let context: ReconcileContextResponse | null = data.initialContext;
  let contextLoading = false;
  let contextError = data.initialContextError ?? '';
  let lastFetchedRange = context ? `${periodStart}::${periodEnd}` : '';

  let setupCommitted = false;
  let ticked = new Set<string>();
  let submitting = false;
  let bannerError = '';
  let bannerDetails: ReconcileError | null = null;
  let showRawError = false;

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function addDays(iso: string, days: number): string {
    const [y, m, d] = iso.split('-').map((s) => Number.parseInt(s, 10));
    const dt = new Date(Date.UTC(y, m - 1, d));
    dt.setUTCDate(dt.getUTCDate() + days);
    return dt.toISOString().slice(0, 10);
  }

  $: minPeriodStart = context?.lastReconciliationDate
    ? addDays(context.lastReconciliationDate, 1)
    : '';

  $: setupValid =
    /^\d{4}-\d{2}-\d{2}$/.test(periodStart) &&
    /^\d{4}-\d{2}-\d{2}$/.test(periodEnd) &&
    periodStart <= periodEnd &&
    isValidAmount(closingBalance) &&
    (!minPeriodStart || periodStart >= minPeriodStart);

  $: setupBlockedReason = (() => {
    if (!periodStart || !periodEnd) return 'Pick the statement period before continuing.';
    if (periodStart > periodEnd) return 'Period start has to be on or before period end.';
    if (minPeriodStart && periodStart < minPeriodStart)
      return `Period start must be on or after ${minPeriodStart} (the day after the last reconciliation).`;
    if (!isValidAmount(closingBalance)) return 'Enter the closing balance from the statement.';
    return '';
  })();

  $: currency = context?.currency || 'USD';

  $: openingBalanceStr = context?.openingBalance ?? '0';

  $: tickedSumStr = (() => {
    if (!context) return '0';
    const amounts = context.transactions
      .filter((row) => ticked.has(row.id))
      .map((row) => row.signedAmount);
    return amounts.length === 0 ? '0' : decimalAddAll(amounts);
  })();

  $: differenceStr = (() => {
    if (!context || !isValidAmount(closingBalance)) return null;
    const projected = decimalAddAll([openingBalanceStr, tickedSumStr]);
    try {
      const closing = parseAmount(closingBalance);
      return decimalSub(closing, projected);
    } catch {
      return null;
    }
  })();

  $: diffIsZero = differenceStr !== null && decimalEquals(differenceStr, '0');

  $: canFinish =
    setupCommitted &&
    setupValid &&
    !contextLoading &&
    !contextError &&
    !!context &&
    diffIsZero &&
    !submitting &&
    isValidAmount(closingBalance);

  async function fetchContext(force = false) {
    if (!periodStart || !periodEnd || periodStart > periodEnd) return;
    const rangeKey = `${periodStart}::${periodEnd}`;
    if (!force && rangeKey === lastFetchedRange) return;
    lastFetchedRange = rangeKey;
    contextLoading = true;
    contextError = '';
    try {
      const res = await apiGet<ReconcileContextResponse>(
        `/api/accounts/${encodeURIComponent(account.id)}/reconciliation-context?period_start=${periodStart}&period_end=${periodEnd}`
      );
      context = res;
      if (res.lastReconciliationDate) {
        const floor = addDays(res.lastReconciliationDate, 1);
        if (periodStart < floor) periodStart = floor;
      }
      const ids = new Set(res.transactions.map((row) => row.id));
      ticked = new Set([...ticked].filter((id) => ids.has(id)));
    } catch (err) {
      contextError =
        err instanceof Error ? err.message : 'Could not load reconciliation context.';
    } finally {
      contextLoading = false;
    }
  }

  function scheduleContextFetch() {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      void fetchContext();
    }, 250);
  }

  $: if (setupCommitted) {
    void periodStart;
    void periodEnd;
    scheduleContextFetch();
  }

  async function handleContinue() {
    if (!setupValid) return;
    bannerError = '';
    bannerDetails = null;
    setupCommitted = true;
    await fetchContext(true);
  }

  function handleEditSetup() {
    setupCommitted = false;
    bannerError = '';
    bannerDetails = null;
  }

  function toggleRow(id: string) {
    const next = new Set(ticked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    ticked = next;
  }

  function tickedAmountLabel(amount: string): string {
    const numeric = Number.parseFloat(amount);
    return formatCurrency(numeric, currency, {
      signMode: 'good-change-plus',
      accountKind
    });
  }

  function diffStripValue(decimalStr: string): string {
    const numeric = Number.parseFloat(decimalStr);
    return formatCurrency(numeric, currency, {
      signMode: 'good-change-plus',
      accountKind
    });
  }

  function diffMagnitudeLabel(decimalStr: string): string {
    const numeric = Math.abs(Number.parseFloat(decimalStr));
    return formatCurrency(numeric, currency, { signMode: 'negative-only' });
  }

  function offByLabel(details: ReconcileError): string {
    if (details.expected != null && details.actual != null) {
      try {
        const expectedDecimal = parseAmount(details.expected);
        const actualDecimal = parseAmount(details.actual);
        const diff = decimalSub(expectedDecimal, actualDecimal);
        return diffMagnitudeLabel(diff);
      } catch {
        // fall through to message-based fallback
      }
    }
    return details.message || 'Reconciliation rejected.';
  }

  function signedExpectedActualLine(details: ReconcileError): string | null {
    if (details.expected == null || details.actual == null) return null;
    let expectedNum: number;
    let actualNum: number;
    try {
      expectedNum = Number.parseFloat(parseAmount(details.expected));
      actualNum = Number.parseFloat(parseAmount(details.actual));
    } catch {
      return null;
    }
    const expected = formatCurrency(expectedNum, currency, {
      signMode: 'good-change-plus',
      accountKind
    });
    const actual = formatCurrency(actualNum, currency, {
      signMode: 'good-change-plus',
      accountKind
    });
    return `Your statement: ${expected} · Journal: ${actual}`;
  }

  async function handleFinish() {
    if (!canFinish || !context) return;
    submitting = true;
    bannerError = '';
    bannerDetails = null;

    let res: Response;
    try {
      res = await fetch(`/api/accounts/${encodeURIComponent(account.id)}/reconcile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          periodStart,
          periodEnd,
          closingBalance,
          currency: context.currency
        })
      });
    } catch (err) {
      submitting = false;
      bannerError = err instanceof Error ? err.message : 'Network error — try again.';
      return;
    }

    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* leave body null */
    }

    if (res.ok) {
      try {
        await invalidate('/api/tracked-accounts');
        await invalidate('/api/dashboard/overview');
      } catch {
        // best-effort; navigation away is the primary success signal.
      }
      submitting = false;
      void goto(`/transactions?accounts=${encodeURIComponent(account.id)}`);
      return;
    }

    submitting = false;
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === 'object') {
      bannerDetails = detail as ReconcileError;
      bannerError = bannerDetails.message || `Reconciliation failed (${res.status}).`;
    } else if (typeof detail === 'string') {
      bannerError = detail;
      bannerDetails = null;
    } else {
      bannerError = `Reconciliation failed (${res.status}).`;
      bannerDetails = null;
    }
  }

  function handleCancel() {
    if (typeof window !== 'undefined' && window.history.length > 1) {
      window.history.back();
    } else {
      void goto('/accounts');
    }
  }

  onDestroy(() => {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
  });

  $: assertionFailed = bannerDetails?.outcome === 'assertion_failed' || (bannerDetails?.expected != null && bannerDetails?.actual != null);
</script>

<svelte:head>
  <title>Reconcile statement · {account.displayName}</title>
</svelte:head>

<section class="hero view-card">
  <p class="eyebrow">Reconcile</p>
  <h2 class="page-title">Reconcile statement · {account.displayName}</h2>
  <p class="subtitle">
    Enter the statement period and the closing balance you'll attest to. We'll show every transaction
    in the range so you can tick them off and confirm the balance lines up.
  </p>
</section>

{#if bannerError}
  <section
    role="alert"
    class="view-card rejection-card grid gap-2 border-bad/30 bg-bad/8"
  >
    {#if assertionFailed && bannerDetails}
      <p class="eyebrow text-bad">Reconciliation rejected</p>
      <h3 class="m-0 font-display text-3xl text-bad">Off by {offByLabel(bannerDetails)}</h3>
      {#if signedExpectedActualLine(bannerDetails)}
        <p class="m-0 text-muted-foreground">{signedExpectedActualLine(bannerDetails)}</p>
      {/if}
      <p class="m-0 text-sm text-muted-foreground">
        Adjust the period or ticked rows below to scan for the missing $X, then try again.
      </p>
      {#if bannerDetails.rawError}
        <button
          type="button"
          class="cursor-pointer text-sm font-semibold text-bad underline-offset-2 hover:underline w-fit"
          on:click={() => (showRawError = !showRawError)}
        >
          {showRawError ? 'Hide details' : 'View details'}
        </button>
        {#if showRawError}
          <pre class="m-0 mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-line/60 bg-white/80 p-3 text-xs text-muted-foreground">{bannerDetails.rawError}</pre>
        {/if}
      {/if}
    {:else}
      <p class="eyebrow text-bad">Reconciliation rejected</p>
      <h3 class="m-0 font-display text-xl text-bad">{bannerError}</h3>
      {#if bannerDetails?.rawError}
        <button
          type="button"
          class="cursor-pointer text-sm font-semibold text-bad underline-offset-2 hover:underline w-fit"
          on:click={() => (showRawError = !showRawError)}
        >
          {showRawError ? 'Hide details' : 'View details'}
        </button>
        {#if showRawError}
          <pre class="m-0 mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-line/60 bg-white/80 p-3 text-xs text-muted-foreground">{bannerDetails.rawError}</pre>
        {/if}
      {/if}
    {/if}
  </section>
{/if}

<section class="view-card grid gap-4">
  <div class="flex items-start justify-between gap-4">
    <div>
      <p class="eyebrow">Step 1 of 2 · Setup</p>
      <h3 class="m-0 font-display text-xl">Statement period and closing balance</h3>
    </div>
    {#if setupCommitted}
      <button type="button" class="btn w-fit" on:click={handleEditSetup} disabled={submitting}>
        Edit
      </button>
    {/if}
  </div>

  <div class="grid gap-3 grid-cols-2 max-shell:grid-cols-1">
    <label class="grid gap-1.5">
      <span class="text-sm font-semibold text-muted-foreground">Period start</span>
      <input
        type="date"
        bind:value={periodStart}
        min={minPeriodStart || undefined}
        disabled={setupCommitted}
        required
      />
    </label>
    <label class="grid gap-1.5">
      <span class="text-sm font-semibold text-muted-foreground">Period end</span>
      <input
        type="date"
        bind:value={periodEnd}
        disabled={setupCommitted}
        required
      />
    </label>
  </div>

  <label class="grid gap-1.5">
    <span class="text-sm font-semibold text-muted-foreground">Closing balance</span>
    <input
      type="text"
      inputmode="decimal"
      bind:value={closingBalance}
      placeholder="$0.00"
      class="font-display text-lg"
      disabled={setupCommitted}
    />
  </label>

  {#if minPeriodStart}
    <p class="m-0 text-xs text-muted-foreground">
      Locked to {minPeriodStart} or later — the day after the last reconciliation
      ({context?.lastReconciliationDate}). Delete the prior reconciliation if you need to redo an
      earlier period.
    </p>
  {/if}

  {#if !setupValid && (periodStart || periodEnd || closingBalance)}
    <p class="m-0 text-xs text-muted-foreground">{setupBlockedReason}</p>
  {/if}

  {#if !setupCommitted}
    <button
      type="button"
      class="btn btn-primary w-fit"
      on:click={() => void handleContinue()}
      disabled={!setupValid}
    >
      Continue
    </button>
  {/if}
</section>

<section class="view-card grid gap-4" class:review-disabled={!setupCommitted}>
  <div>
    <p class="eyebrow">Step 2 of 2 · Review</p>
    <h3 class="m-0 font-display text-xl">Tick transactions until the difference is zero</h3>
  </div>

  {#if !setupCommitted}
    <p class="m-0 text-sm text-muted-foreground">
      Finish setup above to load the transactions for this period.
    </p>
  {:else}
    <div
      class="diff-strip grid grid-cols-4 gap-3 rounded-2xl border border-card-edge bg-white/64 p-3 max-shell:grid-cols-2"
    >
      <div>
        <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">Opening</p>
        <p class="m-0 mt-1 font-display text-base">
          {context ? diffStripValue(openingBalanceStr) : '—'}
        </p>
      </div>
      <div>
        <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">Ticked</p>
        <p class="m-0 mt-1 font-display text-base">{diffStripValue(tickedSumStr)}</p>
      </div>
      <div>
        <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">Closing</p>
        <p class="m-0 mt-1 font-display text-base">
          {isValidAmount(closingBalance) ? diffStripValue(parseAmount(closingBalance)) : '—'}
        </p>
      </div>
      <div>
        <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Difference
        </p>
        <p
          class="m-0 mt-1 font-display text-base"
          class:diff-zero={diffIsZero}
          class:diff-nonzero={differenceStr !== null && !diffIsZero}
        >
          {differenceStr !== null ? diffStripValue(differenceStr) : '—'}
        </p>
      </div>
    </div>

    {#if contextLoading}
      <p class="m-0 text-sm text-muted-foreground">Loading transactions…</p>
    {:else if contextError}
      <div class="grid gap-2 rounded-2xl border border-bad/30 bg-bad/8 p-3">
        <p class="m-0 text-sm text-bad">{contextError}</p>
        <button class="btn w-fit" type="button" on:click={() => void fetchContext(true)}>
          Try again
        </button>
      </div>
    {:else if context && context.transactions.length === 0}
      <p
        class="m-0 rounded-2xl border border-dashed border-card-edge bg-white/52 px-4 py-6 text-center text-sm text-muted-foreground"
      >
        No transactions on this account between {periodStart} and {periodEnd}.
      </p>
    {:else if context}
      <ul class="m-0 grid list-none gap-0 rounded-2xl border border-line/60 bg-white/64 p-0">
        {#each context.transactions as row (row.id)}
          <li
            class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b border-line/30 px-3 py-2 last:border-b-0"
          >
            <input
              type="checkbox"
              checked={ticked.has(row.id)}
              on:change={() => toggleRow(row.id)}
              aria-label={`Tick ${row.payee} on ${row.date}`}
              disabled={submitting}
            />
            <div class="min-w-0">
              <p class="m-0 truncate text-sm font-semibold text-foreground" title={row.payee}>
                {row.payee}
              </p>
              <p class="m-0 mt-0.5 text-xs text-muted-foreground">
                {row.date}{row.category ? ` · ${row.category}` : ''}
              </p>
            </div>
            <span class="shrink-0 font-display text-sm">
              {tickedAmountLabel(row.signedAmount)}
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<footer
  class="page-footer flex items-center justify-end gap-2 max-shell:fixed max-shell:bottom-0 max-shell:left-0 max-shell:right-0 max-shell:z-20 max-shell:flex-col-reverse max-shell:items-stretch max-shell:border-t max-shell:border-card-edge max-shell:bg-white/95 max-shell:p-4 max-shell:backdrop-blur"
>
  <button type="button" class="btn" on:click={handleCancel} disabled={submitting}>Cancel</button>
  <button
    type="button"
    class="btn btn-primary"
    on:click={() => void handleFinish()}
    disabled={!canFinish}
  >
    {submitting ? 'Reconciling…' : 'Reconcile'}
  </button>
</footer>

<!-- Spacer so the sticky mobile footer doesn't cover content. -->
<div class="hidden max-shell:block h-20" aria-hidden="true"></div>

<style>
  .diff-zero {
    color: var(--ok);
  }
  .diff-nonzero {
    color: var(--bad);
  }
  .review-disabled {
    opacity: 0.65;
  }
  .rejection-card {
    background: linear-gradient(155deg, rgba(255, 240, 240, 0.95), rgba(255, 248, 246, 0.92));
  }
</style>
