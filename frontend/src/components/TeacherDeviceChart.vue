<script setup lang="ts">
import { PieChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { TeacherDashboard } from '@/types/teacher'

const props = defineProps<{ data: TeacherDashboard['device_status'] }>()
const element = ref<HTMLElement | null>(null)
let chart: ECharts | null = null
use([PieChart, LegendComponent, TooltipComponent, CanvasRenderer])
const labels = { online: '在线', offline: '离线', never_seen: '未上报', abnormal: '异常' }
const colors = { online: '#32d6a2', offline: '#348cf4', never_seen: '#7189ad', abnormal: '#ff5b62' }

function render(): void {
  if (!element.value) return
  chart ??= init(element.value)
  chart.setOption(
    {
      tooltip: { trigger: 'item' },
      legend: { orient: 'vertical', right: 8, top: 'center', textStyle: { color: '#b9c9e8' } },
      series: [
        {
          type: 'pie',
          radius: ['50%', '72%'],
          center: ['34%', '52%'],
          avoidLabelOverlap: true,
          label: {
            show: true,
            position: 'center',
            formatter: `${props.data.reduce((sum, item) => sum + item.count, 0)}\n设备状态`,
            color: '#eef5ff',
            fontSize: 16,
            lineHeight: 24,
          },
          data: props.data.map((item) => ({
            name: labels[item.status],
            value: item.count,
            itemStyle: { color: colors[item.status] },
          })),
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
  <div ref="element" class="teacher-chart" role="img" aria-label="设备状态图" />
  <ul class="sr-only" aria-label="设备状态文本数据">
    <li v-for="item in data" :key="item.status">{{ labels[item.status] }}：{{ item.count }}</li>
  </ul>
</template>
