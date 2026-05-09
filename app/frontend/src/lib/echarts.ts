import * as echarts from 'echarts/core';
import { BarChart, PieChart } from 'echarts/charts';
import { TooltipComponent, GridComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([BarChart, PieChart, TooltipComponent, GridComponent, LegendComponent, CanvasRenderer]);

export { echarts };
export type EChartsInstance = ReturnType<typeof echarts.init>;
