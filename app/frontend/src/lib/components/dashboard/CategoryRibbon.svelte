<script lang="ts">
  import SparklineLine from './SparklineLine.svelte';

  export let categories: Array<{
    category: string;
    categoryLabel: string;
    amount: number;
  }>;
  export let sparklineData: Map<string, number[]>;
  export let formatCurrency: (value: number) => string;
</script>

{#if categories.length > 0}
  <div class="ribbon-scroll flex gap-3 overflow-x-auto pb-2" style="scroll-snap-type: x mandatory; -webkit-overflow-scrolling: touch;">
    {#each categories as row}
      <a
        href={`/transactions?category=${encodeURIComponent(row.category)}`}
        class="ribbon-chip flex-none rounded-xl border border-card-edge bg-white/80 px-4 py-3 no-underline text-inherit transition-all hover:-translate-y-px hover:border-[rgba(15,95,136,0.3)] hover:shadow-md"
        style="scroll-snap-align: start; min-width: 140px; max-width: 180px;"
      >
        <div class="flex items-baseline justify-between gap-2">
          <span class="truncate text-sm font-bold">{row.categoryLabel}</span>
        </div>
        <div class="my-1.5">
          {#if sparklineData.has(row.category)}
            <SparklineLine values={sparklineData.get(row.category) ?? []} />
          {/if}
        </div>
        <span class="font-display text-sm text-muted-foreground">{formatCurrency(row.amount)}</span>
      </a>
    {/each}
  </div>
{:else}
  <p class="m-0 text-sm text-muted-foreground">No spending data yet.</p>
{/if}

<style>
  .ribbon-scroll {
    scrollbar-width: thin;
    scrollbar-color: rgba(10, 61, 89, 0.12) transparent;
  }
  .ribbon-scroll::-webkit-scrollbar {
    height: 4px;
  }
  .ribbon-scroll::-webkit-scrollbar-thumb {
    background: rgba(10, 61, 89, 0.12);
    border-radius: 2px;
  }
</style>
