<script lang="ts">
  // Two-step (Setup → Review) reconciliation modal scoped to a single tracked
  // account. Owns the live diff math; defers the journal write to the
  // already-shipped 8a endpoint. On <980px renders as a bottom sheet using the
  // same bits-ui Dialog primitive RecentActivitySheet uses, with positioning
  // swapped via Tailwind responsive utilities.
  //
  // State machine:
  //   closed → setup → review (loading | loaded | empty | error) → submitting
  //                                                              ↘ success ⇒ close + refresh
  //                                                              ↘ error   ⇒ stay, banner
  //
  // The Reconcile button sits behind two gates: every diff field must parse,
  // and the parsed difference must equal zero (string-decimal compare so the
  // modal cannot enable Reconcile when the backend would 422).
  import { Dialog as DialogPrimitive } from 'bits-ui';
  import { onDestroy, tick } from 'svelte';
  import XIcon from '@lucide/svelte/icons/x';
  import { apiGet } from '$lib/api';
  import { formatCurrency, type AccountKind } from '$lib/format';
  import {
    decimalAddAll,
    decimalEquals,
    decimalSub,
    isValidAmount,
    parseAmount
  } from '$lib/currency-parser';

  type ContextRow = {
    id: string;
    date: string;
    payee: string;
    category: string;
    signedAmount: string;
  };

  type ContextResponse = {
    openingBalance: string;
    currency: string;
    lastReconciliationDate: string | null;
    transactions: ContextRow[];
  };

  type ReconcileError = {
    outcome?: string;
    message?: string;
    expected?: string | null;
    actual?: string | null;
    rawError?: string;
  };

  export let open = false;
  export let accountId: string;
  export let accountName: string;
  export let accountKind: AccountKind | null = null;
  export let onOpenChange: (next: boolean) => void = () => {};
  /** Called after a successful reconcile. The page refreshes the accounts list
   *  in this hook; throwing here surfaces a non-blocking refresh-error. */
  export let onReconciled: () => Promise<void> = async () => {};

  type Step = 'setup' | 'review';

  let step: Step = 'setup';
  let periodStart = '';
  let periodEnd = '';
  let closingBalance = '';

  let context: ContextResponse | null = null;
  let contextLoading = false;
  let contextError = '';
  let lastFetchedRange = '';

  let ticked = new Set<string>();
  let submitting = false;
  let bannerError = '';
  let bannerDetails: ReconcileError | null = null;
  let showRawError = false;

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function todayIso(): string {
    const now = new Date();
    const yyyy = now.getFullYear();
    const mm = String(now.getMonth() + 1).padStart(2, '0');
    const dd = String(now.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  }

  function addDays(iso: string, days: number): string {
    const [y, m, d] = iso.split('-').map((s) => Number.parseInt(s, 10));
    const dt = new Date(Date.UTC(y, m - 1, d));
    dt.setUTCDate(dt.getUTCDate() + days);
    return dt.toISOString().slice(0, 10);
  }

  function resetState() {
    step = 'setup';
    closingBalance = '';
    context = null;
    contextLoading = false;
    contextError = '';
    lastFetchedRange = '';
    ticked = new Set();
    submitting = false;
    bannerError = '';
    bannerDetails = null;
    showRawError = false;
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
  }

  // Re-seed defaults whenever the modal opens. `lastReconciliationDate` is
  // unknown until the first context fetch, so seed `periodStart` to today and
  // tighten it once the response arrives.
  $: if (open && step === 'setup' && periodStart === '' && periodEnd === '') {
    periodEnd = todayIso();
    periodStart = todayIso();
  }

  $: minPeriodStart =
    context?.lastReconciliationDate ? addDays(context.lastReconciliationDate, 1) : '';

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

  // Currency for diff math. Falls back to USD until the context arrives.
  $: currency = context?.currency || 'USD';

  // Live diff math — kept as decimal strings to match the backend assertion.
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
    step === 'review' &&
    !contextLoading &&
    !contextError &&
    !!context &&
    diffIsZero &&
    !submitting &&
    isValidAmount(closingBalance);

  function handleOpenChange(next: boolean) {
    if (!next) {
      resetState();
    }
    onOpenChange(next);
  }

  async function fetchContext(force = false) {
    if (!open || !accountId) return;
    if (!periodStart || !periodEnd || periodStart > periodEnd) return;
    const rangeKey = `${periodStart}::${periodEnd}`;
    if (!force && rangeKey === lastFetchedRange) return;
    lastFetchedRange = rangeKey;
    contextLoading = true;
    contextError = '';
    try {
      const res = await apiGet<ContextResponse>(
        `/api/accounts/${encodeURIComponent(accountId)}/reconciliation-context?period_start=${periodStart}&period_end=${periodEnd}`
      );
      context = res;
      // Snap periodStart up to the lock floor if the user hasn't already.
      if (res.lastReconciliationDate) {
        const floor = addDays(res.lastReconciliationDate, 1);
        if (periodStart < floor) periodStart = floor;
      }
      // Drop tick state for rows that no longer exist on the new payload.
      const ids = new Set(res.transactions.map((row) => row.id));
      ticked = new Set([...ticked].filter((id) => ids.has(id)));
    } catch (err) {
      contextError = err instanceof Error ? err.message : 'Could not load reconciliation context.';
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

  // Initial fetch on modal open so `lastReconciliationDate` is known before
  // the user touches anything — the snap inside fetchContext then defaults
  // periodStart to `lastReconciliationDate + 1 day`.
  $: if (open && step === 'setup' && periodStart && periodEnd && !context && !contextLoading) {
    void fetchContext();
  }

  $: if (step === 'review') {
    // Refetch on date changes while in Review. The debounce keeps typing
    // responsive on slow journals.
    void periodStart;
    void periodEnd;
    scheduleContextFetch();
  }

  async function handleContinue() {
    if (!setupValid) return;
    bannerError = '';
    bannerDetails = null;
    step = 'review';
    await tick();
    await fetchContext(true);
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
      signMode: accountKind ? 'good-change-plus' : 'negative-only',
      accountKind: accountKind ?? undefined
    });
  }

  function diffStripValue(decimalStr: string): string {
    const numeric = Number.parseFloat(decimalStr);
    return formatCurrency(numeric, currency, {
      signMode: accountKind ? 'good-change-plus' : 'negative-only',
      accountKind: accountKind ?? undefined
    });
  }

  async function handleFinish() {
    if (!canFinish || !context) return;
    submitting = true;
    bannerError = '';
    bannerDetails = null;

    let res: Response;
    try {
      res = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/reconcile`, {
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
      submitting = false;
      // The modal closes regardless of refresh outcome — the user got their
      // confirmation by virtue of the close. The parent's `onReconciled`
      // hook is where the accounts list refetch lives; if it throws, the
      // parent surfaces the trust-issue toast/banner itself.
      onOpenChange(false);
      resetState();
      try {
        await onReconciled();
      } catch {
        // swallowed — parent owns user-facing surfacing.
      }
      return;
    }

    submitting = false;
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === 'object') {
      bannerDetails = detail as ReconcileError;
      bannerError = bannerDetails.message || `Reconciliation failed (${res.status}).`;
    } else if (typeof detail === 'string') {
      bannerError = detail;
    } else {
      bannerError = `Reconciliation failed (${res.status}).`;
    }
  }

  function handleCancel() {
    onOpenChange(false);
  }

  onDestroy(() => {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
  });
</script>

<DialogPrimitive.Root {open} onOpenChange={handleOpenChange}>
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay class="fixed inset-0 z-30 bg-black/35" />

    <DialogPrimitive.Content
      class="fixed z-40 flex flex-col bg-white shadow-card animate-[sheet-slide-in_0.2s_ease-out]
             shell:top-1/2 shell:left-1/2 shell:h-auto shell:max-h-[min(36rem,calc(100vh-3rem))] shell:w-[min(40rem,calc(100vw-3rem))] shell:-translate-x-1/2 shell:-translate-y-1/2 shell:rounded-2xl shell:border shell:border-line
             max-shell:bottom-0 max-shell:left-0 max-shell:right-0 max-shell:max-h-[90vh] max-shell:rounded-t-2xl max-shell:border-t max-shell:border-line"
      aria-labelledby="reconcile-modal-title"
    >
      <header class="flex items-start justify-between gap-3 border-b border-line/60 px-5 pt-5 pb-4">
        <div class="min-w-0">
          <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Step {step === 'setup' ? '1 of 2' : '2 of 2'}
          </p>
          <h3 id="reconcile-modal-title" class="m-0 mt-1 font-display text-lg">
            Reconcile statement · {accountName}
          </h3>
        </div>
        <DialogPrimitive.Close
          class="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="Close"
        >
          <XIcon class="size-4" />
        </DialogPrimitive.Close>
      </header>

      <div class="grow overflow-y-auto px-5 py-4">
        {#if bannerError}
          <div role="alert" class="mb-4 rounded-2xl border border-bad/30 bg-bad/8 px-4 py-3">
            <p class="m-0 text-sm font-semibold text-bad">{bannerError}</p>
            {#if bannerDetails?.expected && bannerDetails?.actual}
              <p class="m-0 mt-1 text-xs text-muted-foreground">
                Expected {bannerDetails.expected} · Found {bannerDetails.actual}
              </p>
            {/if}
            {#if bannerDetails?.rawError}
              <button
                type="button"
                class="mt-2 cursor-pointer text-xs font-semibold text-bad underline-offset-2 hover:underline"
                on:click={() => (showRawError = !showRawError)}
              >
                {showRawError ? 'Hide details' : 'View details'}
              </button>
              {#if showRawError}
                <pre class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-line/60 bg-white/80 p-2 text-xs text-muted-foreground">{bannerDetails.rawError}</pre>
              {/if}
            {/if}
          </div>
        {/if}

        {#if step === 'setup'}
          <div class="grid gap-4">
            <p class="m-0 text-sm text-muted-foreground">
              Enter the statement period and the closing balance you'll attest to. We'll show every
              transaction in the range so you can tick them off and confirm the balance lines up.
            </p>
            <div class="grid gap-3 max-shell:grid-cols-1 grid-cols-2">
              <label class="grid gap-1.5">
                <span class="text-sm font-semibold text-muted-foreground">Period start</span>
                <input
                  type="date"
                  bind:value={periodStart}
                  min={minPeriodStart || undefined}
                  required
                />
              </label>
              <label class="grid gap-1.5">
                <span class="text-sm font-semibold text-muted-foreground">Period end</span>
                <input type="date" bind:value={periodEnd} required />
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
              />
            </label>
            {#if minPeriodStart}
              <p class="m-0 text-xs text-muted-foreground">
                Locked to {minPeriodStart} or later — the day after the last reconciliation
                ({context?.lastReconciliationDate}). Delete the prior reconciliation if you need to
                redo an earlier period.
              </p>
            {/if}
            {#if !setupValid && (periodStart || periodEnd || closingBalance)}
              <p class="m-0 text-xs text-muted-foreground">{setupBlockedReason}</p>
            {/if}
          </div>
        {:else}
          <div class="grid gap-4">
            <div
              class="grid grid-cols-4 gap-3 rounded-2xl border border-card-edge bg-white/64 p-3
                     max-shell:grid-cols-2"
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
                <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">Difference</p>
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
              <p class="m-0 rounded-2xl border border-dashed border-card-edge bg-white/52 px-4 py-6 text-center text-sm text-muted-foreground">
                No transactions on this account between {periodStart} and {periodEnd}.
              </p>
            {:else if context}
              <ul class="m-0 grid list-none gap-0 rounded-2xl border border-line/60 bg-white/64 p-0">
                {#each context.transactions as row (row.id)}
                  <li class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b border-line/30 px-3 py-2 last:border-b-0">
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
          </div>
        {/if}
      </div>

      <footer
        class="flex items-center justify-end gap-2 border-t border-line/60 px-5 pb-5 pt-4
               max-shell:flex-col-reverse max-shell:items-stretch"
      >
        <button type="button" class="btn" on:click={handleCancel} disabled={submitting}>
          Cancel
        </button>
        {#if step === 'setup'}
          <button
            type="button"
            class="btn btn-primary"
            on:click={handleContinue}
            disabled={!setupValid}
          >
            Continue
          </button>
        {:else}
          <button
            type="button"
            class="btn btn-primary"
            on:click={() => void handleFinish()}
            disabled={!canFinish}
          >
            {submitting ? 'Reconciling…' : 'Reconcile'}
          </button>
        {/if}
      </footer>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
</DialogPrimitive.Root>

<style>
  .diff-zero {
    color: var(--ok);
  }
  .diff-nonzero {
    color: var(--bad);
  }
</style>
