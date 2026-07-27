<script setup lang="ts">
import { Document, Right } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

import type { StudentLog } from '@/types/student'

const props = defineProps<{ logs: StudentLog[] }>()
const page = ref(1)
const pageSize = 20
const pageCount = computed(() => Math.max(1, Math.ceil(props.logs.length / pageSize)))
const visibleLogs = computed(() =>
  props.logs.slice((page.value - 1) * pageSize, page.value * pageSize),
)
watch(
  () => props.logs,
  () => {
    if (page.value > pageCount.value) page.value = pageCount.value
  },
)

function levelType(level: string): 'success' | 'warning' | 'danger' | 'info' {
  const normalized = level.toLowerCase()
  if (normalized === 'error' || normalized === 'critical') return 'danger'
  if (normalized === 'warning' || normalized === 'warn') return 'warning'
  if (normalized === 'info') return 'success'
  return 'info'
}
</script>

<template>
  <article id="logs" class="panel-card log-panel">
    <div class="panel-heading compact-heading">
      <h2><Document /> 实时日志列表</h2>
      <span class="text-action">共 {{ logs.length }} 条 <Right /></span>
    </div>
    <el-empty v-if="logs.length === 0" description="设备尚未上传日志" :image-size="72" />
    <div v-else class="log-list">
      <article v-for="log in visibleLogs" :key="log.id" class="log-row">
        <div class="log-meta">
          <time>{{ new Date(log.occurred_at).toLocaleTimeString('zh-CN') }}</time>
          <el-tag size="small" :type="levelType(log.level)" round>{{ log.level }}</el-tag>
          <p>{{ log.message }}</p>
        </div>
        <code v-if="log.event_code">{{ log.event_code }}</code>
        <span v-if="log.is_test_data" class="test-label">测试</span>
      </article>
    </div>
    <nav v-if="logs.length > pageSize" class="log-pagination" aria-label="日志分页">
      <button type="button" :disabled="page === 1" @click="page -= 1">上一页</button>
      <span aria-live="polite">第 {{ page }} / {{ pageCount }} 页</span>
      <button type="button" :disabled="page === pageCount" @click="page += 1">下一页</button>
    </nav>
  </article>
</template>
