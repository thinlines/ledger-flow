<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { echarts, type EChartsInstance } from '$lib/echarts';

  export let amounts: number[];

  let container: HTMLDivElement;
  let chart: EChartsInstance | null = null;
  let observer: ResizeObserver | null = null;

  function buildOption() {
    return {
      grid: { top: 0, bottom: 0, left: 0, right: 0 },
      xAxis: { type: 'category' as const, show: false, data: amounts.map((_, i) => i) },
      yAxis: { type: 'value' as const, show: false },
      series: [{
        type: 'bar' as const,
        data: amounts,
        itemStyle: { color: '#94a3b8', borderRadius: [2, 2, 0, 0] },
        barWidth: '60%'
      }]
    };
  }

  onMount(() => {
    chart = echarts.init(container);
    chart.setOption(buildOption());
    observer = new ResizeObserver(() => chart?.resize());
    observer.observe(container);
  });

  $: if (chart && amounts) {
    chart.setOption(buildOption());
  }

  onDestroy(() => {
    observer?.disconnect();
    chart?.dispose();
    chart = null;
  });
</script>

<div bind:this={container} class="h-6 w-full"></div>
