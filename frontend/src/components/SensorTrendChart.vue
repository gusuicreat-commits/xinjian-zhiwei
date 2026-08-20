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
      color: ['#006cd2', '#12a26b', '#d57b22', '#687078'],
      legend: { type: 'scroll', top: 0, textStyle: { color: '#5e6970', fontSize: 11 } },
      grid: { left: 44, right: 18, top: 48, bottom: 36 },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: '#cfd5d9' } },
        axisLabel: { color: '#7b858b' },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: '#e6eaed' } },
        axisLabel: { color: '#7b858b' },
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
    <details v-if="readings.length" class="chart-data-fallback">
      <summary>查看图表文本数据</summary>
      <table>
        <caption>
          传感器读数（最多显示最近 50 条）
        </caption>
        <thead>
          <tr>
            <th>时间</th>
            <th>指标</th>
            <th>数值</th>
            <th>单位</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="reading in readings.slice(-50)" :key="reading.id">
            <td>{{ new Date(reading.observed_at).toLocaleString('zh-CN') }}</td>
            <td>{{ reading.sensor_type }} · {{ reading.metric_key }}</td>
            <td>{{ reading.value }}</td>
            <td>{{ reading.unit || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </details>
  </article>
</template>
