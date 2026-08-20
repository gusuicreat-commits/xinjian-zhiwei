<script setup lang="ts">
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { TeacherDashboard } from '@/types/teacher'
const props = defineProps<{ data: TeacherDashboard['error_ranking'] }>()
const element = ref<HTMLElement | null>(null)
let chart: ECharts | null = null
use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])
function render(): void {
  if (!element.value) return
  chart ??= init(element.value)
  chart.setOption(
    {
      tooltip: { trigger: 'axis' },
      grid: { left: 126, right: 26, top: 16, bottom: 26 },
      xAxis: {
        type: 'value',
        minInterval: 1,
        axisLabel: { color: '#7b858b' },
        splitLine: { lineStyle: { color: '#e3e7ea' } },
      },
      yAxis: {
        type: 'category',
        inverse: true,
        data: props.data.map((x) => x.error_code),
        axisLabel: { color: '#343a3e', width: 116, overflow: 'truncate' },
      },
      series: [
        {
          type: 'bar',
          data: props.data.map((x) => x.count),
          barWidth: 18,
          itemStyle: { color: '#006cd2', borderRadius: 0 },
          label: { show: true, position: 'right', color: '#0a0a0a' },
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
  <el-empty v-if="data.length === 0" description="暂无诊断错误记录" :image-size="54" />
  <div v-else ref="element" class="teacher-chart" role="img" aria-label="高频错误横向柱状图" />
  <ol class="sr-only" aria-label="高频错误文本数据">
    <li v-for="item in data" :key="item.error_code">{{ item.error_code }}：{{ item.count }}</li>
  </ol>
</template>
