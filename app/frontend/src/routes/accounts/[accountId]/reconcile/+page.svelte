<script lang="ts">
  import { goto, invalidate } from '$app/navigation';
  import { onDestroy } from 'svelte';
  import { apiGet, apiPost } from '$lib/api';
  import { formatCurrency } from '$lib/format';
  import { showUndoToast } from '$lib/undo-toast';
  import {
    decimalAddAll,
    decimalEquals,
    decimalSub,
    isValidAmount,
    parseAmount
  } from '$lib/currency-parser';
  import {
    offByLabel,
    signedExpectedActualLine,
    type ReconcileErrorDetails
  } from './reconcile-error-copy';
  import {
    findSubsetSumCandidates,
    type SubsetSumCandidate,
    type SubsetSumRow
  } from './subset-sum';
  import type { PageData } from './$types';
  import type { ReconcileContextResponse, ReconcileContextRow } from './+page';

  export let data: PageData;

  type ReconcileError = ReconcileErrorDetails;
  type ReviewFilter = 'remaining' | 'checked' | 'all';
  type DuplicateReviewMatch = {
    row: ReconcileContextRow;
    reason: string;
    confidence: number;
    action: 'remove_manual_duplicate' | 'use_imported_transaction' | 'merge_imported_duplicates' | null;
    actionLabel: string | null;
    actionBlockedReason: string | null;
  };
  type DuplicateReviewGroup = {
    checked: ReconcileContextRow;
    matches: DuplicateReviewMatch[];
  };

  const { account, accountKind } = data;

  let periodStart = data.initialPeriodStart;
  let periodEnd = data.initialPeriodEnd;
  let closingBalance = '';

  let context: ReconcileContextResponse | null = data.initialContext;
  let contextLoading = false;
  let contextError = data.initialContextError ?? '';
  let lastFetchedRange = context ? `${periodStart}::${periodEnd}` : '';
  let hasSnappedPeriodStart = false;

  let setupCommitted = false;
  let checkedSelectionKeys = new Set<string>();
  let reviewFilter: ReviewFilter = 'remaining';
  let submitting = false;
  let bannerError = '';
  let bannerDetails: ReconcileError | null = null;
  let showRawError = false;

  let duplicateReviewEnabled = false;
  let duplicateReviewLoading = false;
  let duplicateReviewGroups: DuplicateReviewGroup[] = [];
  let duplicateReviewMessage = '';
  let duplicateReviewError = '';
  let duplicateActionsDisabled = false;
  let resolvingCandidateKey = '';

  let subsetSumCandidates: SubsetSumCandidate[] = [];
  let subsetSumSearched = false;
  let subsetSumSearching = false;
  let subsetSumSkippedTooMany = false;
  let subsetSumTimedOut = false;

  let contextDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let duplicateDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  function addDays(iso: string, days: number): string {
    const [y, m, d] = iso.split('-').map((s) => Number.parseInt(s, 10));
    const dt = new Date(Date.UTC(y, m - 1, d));
    dt.setUTCDate(dt.getUTCDate() + days);
    return dt.toISOString().slice(0, 10);
  }

  function refreshTickedRows(rows: ReconcileContextRow[]) {
    const validKeys = new Set(rows.map((row) => row.selectionKey));
    checkedSelectionKeys = new Set([...checkedSelectionKeys].filter((key) => validKeys.has(key)));
  }

  function clearSubsetSum() {
    subsetSumCandidates = [];
    subsetSumSearched = false;
    subsetSumSearching = false;
    subsetSumSkippedTooMany = false;
    subsetSumTimedOut = false;
  }

  function clearDuplicateReview() {
    duplicateReviewEnabled = false;
    duplicateReviewLoading = false;
    duplicateReviewGroups = [];
    duplicateReviewMessage = '';
    duplicateReviewError = '';
    duplicateActionsDisabled = false;
    resolvingCandidateKey = '';
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
    if (minPeriodStart && periodStart < minPeriodStart) {
      return `Period start must be on or after ${minPeriodStart} (the day after the last reconciliation).`;
    }
    if (!isValidAmount(closingBalance)) return 'Enter the closing balance from the statement.';
    return '';
  })();

  $: currency = context?.currency || 'USD';
  $: openingBalanceStr = context?.openingBalance ?? '0';

  $: tickedSumStr = (() => {
    if (!context) return '0';
    const amounts = context.transactions
      .filter((row) => checkedSelectionKeys.has(row.selectionKey))
      .map((row) => row.signedAmount);
    return amounts.length === 0 ? '0' : decimalAddAll(amounts);
  })();

  $: differenceStr = (() => {
    if (!context || !isValidAmount(closingBalance)) return null;
    const projected = decimalAddAll([openingBalanceStr, tickedSumStr]);
    try {
      return decimalSub(parseAmount(closingBalance), projected);
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

  $: filteredRows = (() => {
    const rows = context?.transactions ?? [];
    if (reviewFilter === 'checked') {
      return rows.filter((row) => checkedSelectionKeys.has(row.selectionKey));
    }
    if (reviewFilter === 'remaining') {
      return rows.filter((row) => !checkedSelectionKeys.has(row.selectionKey));
    }
    return rows;
  })();

  $: assertionFailed =
    bannerDetails?.outcome === 'assertion_failed' ||
    (bannerDetails?.expected != null && bannerDetails?.actual != null);

  $: duplicateReviewAvailable = duplicateReviewEnabled && duplicateReviewGroups.length > 0;

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
      if (!hasSnappedPeriodStart && res.lastReconciliationDate) {
        const floor = addDays(res.lastReconciliationDate, 1);
        if (periodStart < floor) periodStart = floor;
        hasSnappedPeriodStart = true;
      }
      refreshTickedRows(res.transactions);
    } catch (err) {
      contextError =
        err instanceof Error ? err.message : 'Could not load reconciliation context.';
      duplicateActionsDisabled = duplicateReviewEnabled;
    } finally {
      contextLoading = false;
    }
  }

  function scheduleContextFetch() {
    if (contextDebounceTimer !== null) clearTimeout(contextDebounceTimer);
    contextDebounceTimer = setTimeout(() => {
      void fetchContext();
    }, 250);
  }

  async function loadDuplicateReview() {
    if (!context || !setupCommitted) return;
    duplicateReviewLoading = true;
    duplicateReviewError = '';
    try {
      const res = await apiPost<{
        hasGroups: boolean;
        groups: DuplicateReviewGroup[];
      }>(`/api/accounts/${encodeURIComponent(account.id)}/reconciliation-duplicate-review`, {
        periodStart,
        periodEnd,
        checkedSelectionKeys: [...checkedSelectionKeys]
      });
      duplicateReviewGroups = res.groups;
      duplicateReviewEnabled = true;
      duplicateReviewMessage = res.hasGroups
        ? 'Your checked balance matches the statement, but we found transactions you left out that look like duplicates.'
        : '';
    } catch (err) {
      duplicateReviewError =
        err instanceof Error ? err.message : 'Could not review possible duplicates.';
    } finally {
      duplicateReviewLoading = false;
    }
  }

  function scheduleDuplicateReviewLoad() {
    if (!duplicateReviewEnabled || !context || contextLoading) return;
    if (duplicateDebounceTimer !== null) clearTimeout(duplicateDebounceTimer);
    duplicateDebounceTimer = setTimeout(() => {
      void loadDuplicateReview();
    }, 250);
  }

  $: if (setupCommitted) {
    void periodStart;
    void periodEnd;
    scheduleContextFetch();
  }

  $: if (duplicateReviewEnabled) {
    void checkedSelectionKeys;
    scheduleDuplicateReviewLoad();
  }

  async function handleContinue() {
    if (!setupValid) return;
    bannerError = '';
    bannerDetails = null;
    clearDuplicateReview();
    clearSubsetSum();
    setupCommitted = true;
    await fetchContext(true);
  }

  function handleEditSetup() {
    setupCommitted = false;
    bannerError = '';
    bannerDetails = null;
    clearDuplicateReview();
    clearSubsetSum();
  }

  function toggleRow(selectionKey: string) {
    const next = new Set(checkedSelectionKeys);
    if (next.has(selectionKey)) next.delete(selectionKey);
    else next.add(selectionKey);
    checkedSelectionKeys = next;
    clearSubsetSum();
  }

  function handleFindDifference() {
    if (!context || differenceStr === null || diffIsZero) return;
    clearSubsetSum();
    subsetSumSearching = true;

    const unticked: SubsetSumRow[] = context.transactions
      .filter((row) => !checkedSelectionKeys.has(row.selectionKey))
      .map((row) => ({
        selectionKey: row.selectionKey,
        signedAmount: row.signedAmount,
        date: row.date,
        payee: row.payee
      }));

    const result = findSubsetSumCandidates(unticked, differenceStr);
    subsetSumCandidates = result.candidates;
    subsetSumSkippedTooMany = result.skippedTooManyRows;
    subsetSumTimedOut = result.timedOut;
    subsetSumSearched = true;
    subsetSumSearching = false;
  }

  function handleTickCandidate(candidate: SubsetSumCandidate) {
    const next = new Set(checkedSelectionKeys);
    for (const row of candidate.rows) {
      next.add(row.selectionKey);
    }
    checkedSelectionKeys = next;
    clearSubsetSum();
  }

  function tickedAmountLabel(amount: string): string {
    return formatCurrency(Number.parseFloat(amount), currency, {
      signMode: 'good-change-plus',
      accountKind
    });
  }

  function diffStripValue(decimalStr: string): string {
    return formatCurrency(Number.parseFloat(decimalStr), currency, {
      signMode: 'good-change-plus',
      accountKind
    });
  }

  async function handleFinish() {
    if (!canFinish || !context) return;
    submitting = true;
    bannerError = '';
    bannerDetails = null;
    clearDuplicateReview();
    clearSubsetSum();

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
        // Navigation away is the primary success signal.
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

    const isAssertionFailure =
      !!bannerDetails &&
      (bannerDetails.outcome === 'assertion_failed' ||
        (bannerDetails.expected != null && bannerDetails.actual != null));

    if (diffIsZero && isAssertionFailure) {
      await loadDuplicateReview();
    }
  }

  async function handleDeleteRow(row: ReconcileContextRow) {
    if (!row.canDelete) return;
    if (!window.confirm(`Remove ${row.payee} on ${row.date}?`)) return;

    duplicateReviewError = '';
    try {
      const res = await apiPost<{ success: boolean; eventId: string | null }>('/api/transactions/delete', {
        journalPath: row.journalPath,
        headerLine: row.headerLine,
        lineNumber: row.lineNumber
      });
      if (res.eventId) {
        showUndoToast(res.eventId, `Removed ${row.payee} on ${row.date}`, async () => {
          await fetchContext(true);
          if (duplicateReviewEnabled) await loadDuplicateReview();
        });
      }
      checkedSelectionKeys.delete(row.selectionKey);
      checkedSelectionKeys = new Set(checkedSelectionKeys);
      await fetchContext(true);
      if (duplicateReviewEnabled) await loadDuplicateReview();
    } catch (err) {
      duplicateReviewError = err instanceof Error ? err.message : 'Could not remove that transaction.';
    }
  }

  async function handleResolveCandidate(group: DuplicateReviewGroup, match: DuplicateReviewMatch) {
    if (!match.action || duplicateActionsDisabled) return;

    const confirmCopy = {
      remove_manual_duplicate: `Remove ${match.row.payee} on ${match.row.date}?`,
      use_imported_transaction: `Keep the imported transaction for ${match.row.payee} and remove the checked manual duplicate?`,
      merge_imported_duplicates: `Merge these imported duplicates and keep the checked transaction?`
    } satisfies Record<NonNullable<DuplicateReviewMatch['action']>, string>;
    if (!window.confirm(confirmCopy[match.action])) return;

    duplicateReviewError = '';
    resolvingCandidateKey = `${group.checked.selectionKey}::${match.row.selectionKey}`;
    const nextChecked = new Set(checkedSelectionKeys);

    try {
      const result = await apiPost<{
        ok: boolean;
        removedSelectionKeys: string[];
        addedCheckedSelectionKeys: string[];
      }>(`/api/accounts/${encodeURIComponent(account.id)}/reconciliation-duplicate-resolution`, {
        periodStart,
        periodEnd,
        checkedSelectionKey: group.checked.selectionKey,
        uncheckedSelectionKey: match.row.selectionKey,
        action: match.action
      });

      for (const key of result.removedSelectionKeys) nextChecked.delete(key);
      for (const key of result.addedCheckedSelectionKeys) nextChecked.add(key);
      checkedSelectionKeys = nextChecked;
      await fetchContext(true);
      duplicateActionsDisabled = !!contextError;
      if (!contextError) {
        await loadDuplicateReview();
      } else {
        duplicateReviewError =
          'The duplicate resolution was applied, but this page could not refresh. Refresh before making more changes.';
      }
    } catch (err) {
      duplicateReviewError =
        err instanceof Error ? err.message : 'Could not resolve that possible duplicate.';
    } finally {
      resolvingCandidateKey = '';
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
    if (contextDebounceTimer !== null) clearTimeout(contextDebounceTimer);
    if (duplicateDebounceTimer !== null) clearTimeout(duplicateDebounceTimer);
  });
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
  <section role="alert" class="view-card rejection-card grid gap-3 border-bad/30 bg-bad/8">
    {#if assertionFailed && bannerDetails}
      <p class="eyebrow text-bad">Reconciliation rejected</p>
      <h3 class="m-0 font-display text-3xl text-bad">Off by {offByLabel(bannerDetails, currency)}</h3>
      {#if signedExpectedActualLine(bannerDetails, currency, accountKind)}
        <p class="m-0 text-muted-foreground">{signedExpectedActualLine(bannerDetails, currency, accountKind)}</p>
      {/if}
      <p class="m-0 text-sm text-muted-foreground">
        {duplicateReviewAvailable
          ? duplicateReviewMessage
          : 'Adjust the period or the checked rows below, then try again.'}
      </p>
      {#if differenceStr !== null && !diffIsZero && !subsetSumSearched && !subsetSumSearching}
        <button
          type="button"
          class="w-fit cursor-pointer text-sm font-semibold text-bad underline-offset-2 hover:underline"
          on:click={handleFindDifference}
        >
          Find the difference
        </button>
      {:else if subsetSumSearching}
        <p class="m-0 text-sm text-muted-foreground">Searching…</p>
      {/if}
      {#if bannerDetails.rawError}
        <button
          type="button"
          class="w-fit cursor-pointer text-sm font-semibold text-bad underline-offset-2 hover:underline"
          on:click={() => (showRawError = !showRawError)}
        >
          {showRawError ? 'Hide details' : 'View details'}
        </button>
        {#if showRawError}
          <pre class="m-0 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-line/60 bg-white/80 p-3 text-xs text-muted-foreground">{bannerDetails.rawError}</pre>
        {/if}
      {/if}
    {:else}
      <p class="eyebrow text-bad">Reconciliation rejected</p>
      <h3 class="m-0 font-display text-xl text-bad">{bannerError}</h3>
      {#if differenceStr !== null && !diffIsZero && !subsetSumSearched && !subsetSumSearching}
        <button
          type="button"
          class="w-fit cursor-pointer text-sm font-semibold text-bad underline-offset-2 hover:underline"
          on:click={handleFindDifference}
        >
          Find the difference
        </button>
      {:else if subsetSumSearching}
        <p class="m-0 text-sm text-muted-foreground">Searching…</p>
      {/if}
    {/if}
  </section>
{/if}

{#if subsetSumSearched}
  <section class="view-card grid gap-4 border-brand/20 bg-[linear-gradient(165deg,rgba(232,248,255,0.95),rgba(255,255,255,0.94))]">
    <div>
      <p class="eyebrow text-brand-strong">Subset-sum diagnostic</p>
      <h3 class="m-0 font-display text-xl">
        {#if subsetSumSkippedTooMany}
          Too many unticked transactions to search
        {:else if subsetSumCandidates.length > 0}
          These unticked transactions may close the gap
        {:else if subsetSumTimedOut}
          No combination found within the search limit
        {:else}
          No matching combination found
        {/if}
      </h3>
    </div>

    {#if subsetSumSkippedTooMany}
      <p class="m-0 text-sm text-muted-foreground">
        There are more than 200 unticked transactions in this period. Narrow the period or tick more rows manually before searching.
      </p>
    {:else if subsetSumCandidates.length > 0}
      <div class="grid gap-3">
        {#each subsetSumCandidates as candidate, i (i)}
          <article class="grid gap-3 rounded-3xl border border-card-edge bg-white/82 p-4 shadow-sm">
            <p class="m-0 text-sm font-semibold text-muted-foreground">
              Tick {candidate.rows.length} transaction{candidate.rows.length === 1 ? '' : 's'} to close the gap
            </p>
            <ul class="m-0 grid list-none gap-1 p-0">
              {#each candidate.rows as row (row.selectionKey)}
                <li class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line/30 bg-white/72 px-3 py-2">
                  <div class="min-w-0">
                    <p class="m-0 truncate text-sm font-semibold text-foreground">{row.payee}</p>
                    <p class="m-0 text-xs text-muted-foreground">{row.date}</p>
                  </div>
                  <span class="shrink-0 font-display text-sm">{tickedAmountLabel(row.signedAmount)}</span>
                </li>
              {/each}
            </ul>
            <button
              type="button"
              class="btn w-fit"
              on:click={() => handleTickCandidate(candidate)}
            >
              Tick these
            </button>
          </article>
        {/each}
      </div>
    {:else if subsetSumTimedOut}
      <p class="m-0 text-sm text-muted-foreground">
        No combination found within the search limit. Try adjusting the period or reviewing rows manually.
      </p>
    {:else}
      <p class="m-0 text-sm text-muted-foreground">
        No combination of up to 5 unticked transactions sums to the difference.
      </p>
    {/if}
  </section>
{/if}

{#if duplicateReviewEnabled}
  <section class="view-card grid gap-4 border-amber-400/30 bg-[linear-gradient(165deg,rgba(255,249,232,0.95),rgba(255,255,255,0.94))]">
    <div class="flex items-start justify-between gap-4">
      <div>
        <p class="eyebrow text-amber-800">Possible duplicates</p>
        <h3 class="m-0 font-display text-xl">Review likely duplicates before trying again</h3>
      </div>
      {#if duplicateReviewLoading}
        <span class="pill bg-white/80 text-amber-900">Refreshing…</span>
      {/if}
    </div>

    {#if duplicateReviewError}
      <p class="m-0 rounded-2xl border border-bad/30 bg-bad/8 px-4 py-3 text-sm text-bad">{duplicateReviewError}</p>
    {/if}

    {#if duplicateReviewAvailable}
      <div class="grid gap-4">
        {#each duplicateReviewGroups as group (group.checked.selectionKey)}
          <article class="grid gap-3 rounded-3xl border border-card-edge bg-white/82 p-4 shadow-sm">
            <div class="grid gap-2">
              <div class="flex flex-wrap items-center gap-2">
                <span class="pill bg-brand/10 text-brand-strong">Checked</span>
                <span class="pill bg-white text-foreground">{group.checked.sourceLabel}</span>
              </div>
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="m-0 truncate font-display text-lg text-foreground">{group.checked.payee}</p>
                  <p class="m-0 text-sm text-muted-foreground">
                    {group.checked.date}{group.checked.category ? ` · ${group.checked.category}` : ''}
                  </p>
                </div>
                <p class="m-0 font-display text-base text-foreground">
                  {tickedAmountLabel(group.checked.signedAmount)}
                </p>
              </div>
            </div>

            <ul class="m-0 grid list-none gap-3 p-0">
              {#each group.matches as match (match.row.selectionKey)}
                <li class="grid gap-3 rounded-2xl border border-line/50 bg-white/88 p-3">
                  <div class="flex flex-wrap items-center justify-between gap-3">
                    <div class="min-w-0">
                      <div class="flex flex-wrap items-center gap-2">
                        <p class="m-0 truncate font-semibold text-foreground">{match.row.payee}</p>
                        <span class="pill bg-surface text-foreground">{match.row.sourceLabel}</span>
                      </div>
                      <p class="m-0 mt-1 text-sm text-muted-foreground">
                        {match.row.date}{match.row.category ? ` · ${match.row.category}` : ''}
                      </p>
                    </div>
                    <p class="m-0 font-display text-base text-foreground">
                      {tickedAmountLabel(match.row.signedAmount)}
                    </p>
                  </div>
                  <p class="m-0 text-sm text-muted-foreground">{match.reason}</p>
                  <div class="flex flex-wrap items-center gap-2">
                    {#if match.action && match.actionLabel}
                      <button
                        type="button"
                        class="btn btn-primary w-fit"
                        disabled={duplicateActionsDisabled || resolvingCandidateKey === `${group.checked.selectionKey}::${match.row.selectionKey}`}
                        on:click={() => void handleResolveCandidate(group, match)}
                      >
                        {resolvingCandidateKey === `${group.checked.selectionKey}::${match.row.selectionKey}`
                          ? 'Applying…'
                          : match.actionLabel}
                      </button>
                    {/if}
                    {#if match.actionBlockedReason}
                      <p class="m-0 text-sm text-muted-foreground">{match.actionBlockedReason}</p>
                    {/if}
                  </div>
                </li>
              {/each}
            </ul>
          </article>
        {/each}
      </div>
    {:else if !duplicateReviewLoading}
      <p class="m-0 rounded-2xl border border-dashed border-card-edge bg-white/72 px-4 py-5 text-sm text-muted-foreground">
        We did not find strong enough duplicate candidates in this checked-versus-remaining split. Keep
        reviewing the list below and try again after adjusting your selection.
      </p>
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
      <input type="date" bind:value={periodStart} min={minPeriodStart || undefined} disabled={setupCommitted} required />
    </label>
    <label class="grid gap-1.5">
      <span class="text-sm font-semibold text-muted-foreground">Period end</span>
      <input type="date" bind:value={periodEnd} disabled={setupCommitted} required />
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
    <button type="button" class="btn btn-primary w-fit" on:click={() => void handleContinue()} disabled={!setupValid}>
      Continue
    </button>
  {/if}
</section>

<section class="view-card grid gap-4" class:review-disabled={!setupCommitted}>
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="eyebrow">Step 2 of 2 · Review</p>
      <h3 class="m-0 font-display text-xl">Tick transactions until the difference is zero</h3>
    </div>
    <div class="filter-strip flex flex-wrap items-center gap-2">
      {#each [
        { id: 'remaining', label: 'Remaining' },
        { id: 'checked', label: 'Checked' },
        { id: 'all', label: 'All' }
      ] as filter}
        <button
          type="button"
          class="btn w-fit"
          class:filter-active={reviewFilter === filter.id}
          on:click={() => (reviewFilter = filter.id as ReviewFilter)}
          disabled={!setupCommitted}
        >
          {filter.label}
        </button>
      {/each}
    </div>
  </div>

  {#if !setupCommitted}
    <p class="m-0 text-sm text-muted-foreground">Finish setup above to load the transactions for this period.</p>
  {:else}
    <div class="diff-strip grid grid-cols-4 gap-3 rounded-2xl border border-card-edge bg-white/64 p-3 max-shell:grid-cols-2">
      <div>
        <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">Opening</p>
        <p class="m-0 mt-1 font-display text-base">{context ? diffStripValue(openingBalanceStr) : '—'}</p>
      </div>
      <div>
        <p class="m-0 text-xs font-bold uppercase tracking-wider text-muted-foreground">Checked</p>
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
        <p class="m-0 mt-1 font-display text-base" class:diff-zero={diffIsZero} class:diff-nonzero={differenceStr !== null && !diffIsZero}>
          {differenceStr !== null ? diffStripValue(differenceStr) : '—'}
        </p>
        {#if differenceStr !== null && !diffIsZero && !subsetSumSearched && !subsetSumSearching}
          <button
            type="button"
            class="mt-1 w-fit cursor-pointer text-xs font-semibold text-brand-strong underline-offset-2 hover:underline"
            on:click={handleFindDifference}
          >
            Find the difference
          </button>
        {:else if subsetSumSearching}
          <p class="m-0 mt-1 text-xs text-muted-foreground">Searching…</p>
        {/if}
      </div>
    </div>

    {#if contextLoading}
      <p class="m-0 text-sm text-muted-foreground">Loading transactions…</p>
    {:else if contextError}
      <div class="grid gap-2 rounded-2xl border border-bad/30 bg-bad/8 p-3">
        <p class="m-0 text-sm text-bad">{contextError}</p>
        <button class="btn w-fit" type="button" on:click={() => void fetchContext(true)}>Try again</button>
      </div>
    {:else if context && filteredRows.length === 0}
      <p class="m-0 rounded-2xl border border-dashed border-card-edge bg-white/52 px-4 py-6 text-center text-sm text-muted-foreground">
        {reviewFilter === 'all'
          ? `No transactions on this account between ${periodStart} and ${periodEnd}.`
          : `No ${reviewFilter} transactions in this period.`}
      </p>
    {:else if context}
      <ul class="m-0 grid list-none gap-0 rounded-2xl border border-line/60 bg-white/64 p-0">
        {#each filteredRows as row (row.id)}
          <li class="grid grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-3 border-b border-line/30 px-3 py-2 last:border-b-0 max-shell:grid-cols-[auto_minmax(0,1fr)_auto]">
            <input
              type="checkbox"
              checked={checkedSelectionKeys.has(row.selectionKey)}
              on:change={() => toggleRow(row.selectionKey)}
              aria-label={`Tick ${row.payee} on ${row.date}`}
              disabled={submitting}
            />
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <p class="m-0 truncate text-sm font-semibold text-foreground" title={row.payee}>{row.payee}</p>
                <span class="pill bg-surface text-foreground">{row.sourceLabel}</span>
              </div>
              <p class="m-0 mt-0.5 text-xs text-muted-foreground">
                {row.date}{row.category ? ` · ${row.category}` : ''}
              </p>
            </div>
            <span class="shrink-0 font-display text-sm">{tickedAmountLabel(row.signedAmount)}</span>
            <details class="row-menu relative max-shell:col-span-3">
              <summary class="btn w-fit list-none cursor-pointer">Actions</summary>
              <div class="row-menu-panel absolute right-0 top-11 z-10 grid min-w-44 gap-1 rounded-2xl border border-card-edge bg-white p-2 shadow-lg">
                <button
                  type="button"
                  class="btn w-full justify-start"
                  disabled={!row.canDelete || duplicateActionsDisabled}
                  on:click={() => void handleDeleteRow(row)}
                >
                  Remove transaction
                </button>
              </div>
            </details>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<footer class="page-footer flex items-center justify-end gap-2 max-shell:fixed max-shell:bottom-0 max-shell:left-0 max-shell:right-0 max-shell:z-20 max-shell:flex-col-reverse max-shell:items-stretch max-shell:border-t max-shell:border-card-edge max-shell:bg-white/95 max-shell:p-4 max-shell:backdrop-blur">
  <button type="button" class="btn" on:click={handleCancel} disabled={submitting}>Cancel</button>
  <button type="button" class="btn btn-primary" on:click={() => void handleFinish()} disabled={!canFinish}>
    {submitting ? 'Reconciling…' : 'Reconcile'}
  </button>
</footer>

<div class="hidden h-20 max-shell:block" aria-hidden="true"></div>

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

  .filter-active {
    border-color: rgba(10, 92, 108, 0.22);
    background: rgba(10, 92, 108, 0.12);
    color: var(--brand-strong);
  }

  .row-menu[open] summary {
    border-color: rgba(10, 92, 108, 0.2);
  }

  .row-menu summary::-webkit-details-marker {
    display: none;
  }
</style>
