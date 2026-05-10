import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { TooltipComponent, GridComponent, LegendComponent, MarkLineComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([BarChart, TooltipComponent, GridComponent, LegendComponent, MarkLineComponent, CanvasRenderer]);

export { echarts };
export type EChartsInstance = ReturnType<typeof echarts.init>;
