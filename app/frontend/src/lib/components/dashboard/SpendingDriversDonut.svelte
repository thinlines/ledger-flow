<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { echarts, type EChartsInstance } from '$lib/echarts';

  export let breakdown: Array<{ categoryLabel: string; amount: number }>;
  export let formatCurrency: (value: number) => string;
  export let onCategoryClick: (category: string) => void = () => {};

  let container: HTMLDivElement;
  let chart: EChartsInstance | null = null;
  let observer: ResizeObserver | null = null;

  function buildOption() {
    return {
      tooltip: {
        trigger: 'item' as const,
        valueFormatter: (v: number | string) => formatCurrency(Number(v))
      },
      series: [{
        type: 'pie' as const,
        radius: ['40%', '70%'],
        label: { show: false },
        emphasis: { label: { show: true, fontWeight: 'bold' as const } },
        data: breakdown.map(r => ({ name: r.categoryLabel, value: r.amount }))
      }]
    };
  }

  onMount(() => {
    chart = echarts.init(container);
    chart.setOption(buildOption());
    chart.on('click', (params: { componentType: string; name: string }) => {
      if (params.componentType === 'series') {
        onCategoryClick(params.name);
      }
    });
    observer = new ResizeObserver(() => chart?.resize());
    observer.observe(container);
  });

  $: if (chart && breakdown) {
    chart.setOption(buildOption());
  }

  onDestroy(() => {
    observer?.disconnect();
    chart?.dispose();
    chart = null;
  });
</script>

<div bind:this={container} class="mx-auto h-[200px] w-full max-w-[300px]"></div>
