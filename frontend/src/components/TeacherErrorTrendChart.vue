<script setup lang="ts">
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { TeacherDashboard } from '@/types/teacher'
const props = defineProps<{ data: TeacherDashboard['error_trend'] }>()
const element = ref<HTMLElement | null>(null)
let chart: ECharts | null = null
use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])
function render(): void {
  if (!element.value) return
  chart ??= init(element.value)
  chart.setOption(
    {
      tooltip: { trigger: 'axis' },
      grid: { left: 38, right: 16, top: 22, bottom: 30 },
      xAxis: {
        type: 'category',
        data: props.data.map((x) => x.day.slice(5)),
        axisLabel: { color: '#8297bc' },
        axisLine: { lineStyle: { color: '#24476e' } },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        axisLabel: { color: '#8297bc' },
        splitLine: { lineStyle: { color: '#173760' } },
      },
      series: [
        {
          type: 'line',
          smooth: true,
          symbolSize: 8,
          data: props.data.map((x) => x.count),
          lineStyle: { color: '#ff5b62', width: 2 },
          itemStyle: { color: '#ff5b62', borderColor: '#fff', borderWidth: 2 },
          areaStyle: { color: 'rgba(255,91,98,.08)' },
        },
      ],
    },
    true,
  )
}
function resize(): void {
  chart?.resize()
}
watch(
  () => props.data,
  async () => {
    await nextTick()
    render()
  },
  { deep: true },
)
onMounted(() => {
  render()
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>
<template>
  <div ref="element" class="teacher-chart" role="img" aria-label="七日错误趋势图" />
  <ol class="sr-only" aria-label="错误趋势文本数据">
    <li v-for="item in data" :key="item.day">{{ item.day }}：{{ item.count }}</li>
  </ol>
</template>
