<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { echarts, type EChartsInstance } from '$lib/echarts';

  export let series: Array<{
    month: string;
    label: string;
    income: number;
    spending: number;
    net: number;
  }>;
  export let currentMonth: string;
  export let formatCurrency: (value: number) => string;
  export let onMonthClick: (month: string) => void = () => {};
  export let focusedIndex: number | null = null;

  let container: HTMLDivElement;
  let chart: EChartsInstance | null = null;
  let observer: ResizeObserver | null = null;

  function buildOption() {
    return {
      tooltip: {
        trigger: 'axis' as const,
        valueFormatter: (v: number | string) => formatCurrency(Number(v))
      },
      legend: { show: true, bottom: 0, textStyle: { fontSize: 11 } },
      grid: { top: 8, right: 0, bottom: 28, left: 0, containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: series.map(r =>
          r.month === currentMonth ? `${r.label}*` : r.label
        ),
        axisTick: { show: false },
        axisLine: { show: false }
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { show: false },
        splitLine: { lineStyle: { type: 'dashed' as const, color: 'rgba(10, 61, 89, 0.08)' } }
      },
      series: [
        {
          name: 'Income',
          type: 'bar' as const,
          cursor: 'pointer',
          data: series.map((r, i) => ({
            value: r.income,
            itemStyle: {
              color: '#1d9f6e',
              borderRadius: [4, 4, 0, 0],
              opacity: focusedIndex !== null && focusedIndex !== i ? 0.35 : 1
            }
          }))
        },
        {
          name: 'Spending',
          type: 'bar' as const,
          cursor: 'pointer',
          data: series.map((r, i) => ({
            value: r.spending,
            itemStyle: {
              color: '#0a3d59',
              borderRadius: [4, 4, 0, 0],
              opacity: focusedIndex !== null && focusedIndex !== i ? 0.35 : 1
            }
          }))
        }
      ]
    };
  }

  onMount(() => {
    chart = echarts.init(container);
    chart.setOption(buildOption());

    chart.on('click', (params: { componentType: string; dataIndex: number }) => {
      if (params.componentType === 'series' && series[params.dataIndex]) {
        onMonthClick(series[params.dataIndex].month);
      }
    });

    observer = new ResizeObserver(() => {
      chart?.resize();
    });
    observer.observe(container);
  });

  $: if (chart && series && focusedIndex !== undefined) {
    chart.setOption(buildOption());
  }

  onDestroy(() => {
    observer?.disconnect();
    chart?.dispose();
    chart = null;
  });
</script>

<div bind:this={container} class="h-56 w-full"></div>
