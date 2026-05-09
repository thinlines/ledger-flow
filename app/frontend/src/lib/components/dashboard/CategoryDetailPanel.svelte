<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { apiGet } from '$lib/api';
  import { echarts, type EChartsInstance } from '$lib/echarts';

  export let category: string;
  export let categoryLabel: string;
  export let categoryHistory: Array<{ month: string; category: string; categoryLabel: string; amount: number }>;
  export let focusedPeriod: string | null;
  export let currentMonth: string;
  export let formatCurrency: (value: number) => string;
  export let onClose: () => void = () => {};

  type TransactionRow = {
    date: string;
    payee: string;
    amount: number;
    category: string;
    categoryLabel: string;
    accountLabel: string;
  };

  let chartContainer: HTMLDivElement;
  let chart: EChartsInstance | null = null;
  let chartObserver: ResizeObserver | null = null;

  let transactions: TransactionRow[] = [];
  let txLoading = false;
  let txError = '';
  let abortController: AbortController | null = null;

  $: period = focusedPeriod ?? currentMonth;
  $: categoryRows = categoryHistory
    .filter(r => r.category === category)
    .sort((a, b) => a.month.localeCompare(b.month));

  function buildChartOption() {
    return {
      tooltip: {
        trigger: 'axis' as const,
        valueFormatter: (v: number | string) => formatCurrency(Number(v))
      },
      grid: { top: 8, right: 0, bottom: 4, left: 0, containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: categoryRows.map(r => {
          const d = new Date(`${r.month}-01T00:00:00`);
          return new Intl.DateTimeFormat(undefined, { month: 'short' }).format(d);
        }),
        axisTick: { show: false },
        axisLine: { show: false }
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { show: false },
        splitLine: { lineStyle: { type: 'dashed' as const, color: 'rgba(10, 61, 89, 0.08)' } }
      },
      series: [{
        type: 'bar' as const,
        data: categoryRows.map(r => r.amount),
        itemStyle: { color: '#0a3d59', borderRadius: [3, 3, 0, 0] }
      }]
    };
  }

  async function fetchTransactions(p: string, cat: string) {
    abortController?.abort();
    abortController = new AbortController();
    txLoading = true;
    txError = '';
    transactions = [];
    try {
      const result = await apiGet<{ transactions: TransactionRow[]; total: number }>(
        `/api/dashboard/transactions?period=${encodeURIComponent(p)}&category=${encodeURIComponent(cat)}`,
        { signal: abortController.signal }
      );
      transactions = result.transactions;
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      txError = 'Could not load transactions.';
    } finally {
      txLoading = false;
    }
  }

  $: if (category && period) {
    fetchTransactions(period, category);
  }

  onMount(() => {
    chart = echarts.init(chartContainer);
    chart.setOption(buildChartOption());
    chartObserver = new ResizeObserver(() => chart?.resize());
    chartObserver.observe(chartContainer);
  });

  $: if (chart && categoryRows) {
    chart.setOption(buildChartOption());
  }

  onDestroy(() => {
    abortController?.abort();
    chartObserver?.disconnect();
    chart?.dispose();
    chart = null;
  });

  function formatDate(value: string): string {
    const parsed = new Date(`${value}T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(parsed);
  }
</script>

<section class="view-card mt-4 p-5">
  <div class="mb-4 flex items-start justify-between gap-4">
    <div>
      <p class="eyebrow">Category detail</p>
      <h3 class="m-0 font-display text-xl">{categoryLabel}</h3>
    </div>
    <button
      class="cursor-pointer rounded-lg border-none bg-transparent px-3 py-1.5 text-sm font-semibold text-muted-foreground transition-colors hover:bg-[rgba(10,61,89,0.04)] hover:text-[var(--foreground)]"
      on:click={onClose}
    >
      Close
    </button>
  </div>

  <div bind:this={chartContainer} class="mb-4 h-36 w-full"></div>

  <div>
    <p class="eyebrow mb-2">Transactions</p>
    {#if txLoading}
      <p class="m-0 text-sm text-muted-foreground">Loading...</p>
    {:else if txError}
      <p class="m-0 text-sm text-muted-foreground">{txError}</p>
    {:else if transactions.length === 0}
      <p class="m-0 text-sm text-muted-foreground">No transactions found for this period.</p>
    {:else}
      <div class="grid gap-0">
        {#each transactions as tx}
          <div class="detail-tx-row flex items-center justify-between gap-3 py-2">
            <div class="min-w-0">
              <p class="m-0 truncate font-medium">{tx.payee}</p>
              <p class="m-0 text-xs text-muted-foreground">{formatDate(tx.date)}</p>
            </div>
            <p class="m-0 shrink-0 font-display text-sm">{formatCurrency(tx.amount)}</p>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</section>

<style>
  .detail-tx-row + .detail-tx-row {
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }
</style>
