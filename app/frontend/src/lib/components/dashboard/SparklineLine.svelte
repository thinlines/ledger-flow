<script lang="ts">
  export let values: number[];

  const w = 100;
  const h = 16;

  $: max = Math.max(...values, 1);
  $: min = Math.min(...values, 0);
  $: range = max - min || 1;
  $: points = values
    .map((v, i) => `${(i / Math.max(values.length - 1, 1)) * w},${h - ((v - min) / range) * h}`)
    .join(' ');
</script>

<svg viewBox="0 0 {w} {h}" class="h-4 w-full" preserveAspectRatio="none">
  <polyline
    {points}
    fill="none"
    stroke="var(--brand)"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
  />
</svg>
