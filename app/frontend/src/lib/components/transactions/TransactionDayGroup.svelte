<script lang="ts">
  export let header: string;
  export let isFirst = false;
</script>

<div class="date-group" class:date-group-first={isFirst}>
  <h4 class="date-header">{header}</h4>
  <slot />
</div>

<style>
  .date-group + :global(.date-group) {
    margin-top: 0.65rem;
    padding-top: 0.65rem;
    border-top: 1px solid rgba(10, 61, 89, 0.08);
  }

  .date-header {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted-foreground);
    font-weight: 700;
  }
</style>
