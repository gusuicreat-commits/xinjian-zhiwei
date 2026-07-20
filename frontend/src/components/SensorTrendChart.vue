<script setup lang="ts">
import { TrendCharts } from '@element-plus/icons-vue'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { StudentReading } from '@/types/student'

const props = defineProps<{ readings: StudentReading[] }>()
const chartElement = ref<HTMLElement | null>(null)
let chart: ECharts | null = null

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const series = computed(() => {
  const groups = new Map<string, StudentReading[]>()
  for (const reading of props.readings) {
    const key = `${reading.sensor_type} · ${reading.metric_key}${reading.unit ? ` (${reading.unit})` : ''}`
    groups.set(key, [...(groups.get(key) ?? []), reading])
  }
  return [...groups.entries()].map(([name, values]) => ({
    name,
    type: 'line' as const,
    showSymbol: values.length < 20,
    smooth: true,
    data: values.map((item) => [item.observed_at, item.value]),
  }))
})

function renderChart(): void {
  if (!chartElement.value || props.readings.length === 0) return
  chart ??= init(chartElement.value)
  chart.setOption(
    {
      tooltip: { trigger: 'axis' },
      color: ['#2f86e9', '#1caf70', '#c47b42', '#8b5cf6'],
      legend: { type: 'scroll', top: 0, textStyle: { color: '#6c5a4d', fontSize: 11 } },
      grid: { left: 44, right: 18, top: 48, bottom: 36 },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: '#dfd4ca' } },
        axisLabel: { color: '#8a7769' },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: '#eee7e0' } },
        axisLabel: { color: '#8a7769' },
      },
      series: series.value,
    },
    true,
  )
}

function resize(): void {
  chart?.resize()
}

watch(
  () => props.readings,
  async () => {
    await nextTick()
    renderChart()
  },
  { deep: true },
)
onMounted(() => {
  renderChart()
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<template>
  <article id="readings" class="panel-card chart-panel">
    <div class="panel-heading compact-heading">
      <h2><TrendCharts /> 传感器折线图</h2>
      <span class="range-pill">最近 {{ readings.length }} 条</span>
    </div>
    <el-empty v-if="readings.length === 0" description="设备尚未上传传感器读数" :image-size="72" />
    <div v-else ref="chartElement" class="sensor-chart" role="img" aria-label="传感器读数折线图" />
  </article>
</template>
