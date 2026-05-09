<script lang="ts">
  export let focusedPeriod: string | null;
  export let onReset: () => void = () => {};

  function formatMonth(period: string): string {
    const parsed = new Date(`${period}-01T00:00:00`);
    return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(parsed);
  }
</script>

{#if focusedPeriod}
  <nav class="flex items-center gap-1.5 text-sm">
    <button
      class="cursor-pointer border-none bg-transparent p-0 font-semibold text-[var(--brand-strong)] hover:underline"
      on:click={onReset}
    >
      All months
    </button>
    <span class="text-muted-foreground">&rarr;</span>
    <span class="font-semibold">{formatMonth(focusedPeriod)}</span>
  </nav>
{/if}
