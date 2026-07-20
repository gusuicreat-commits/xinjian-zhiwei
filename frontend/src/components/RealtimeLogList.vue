<script setup lang="ts">
import { Document, Right } from '@element-plus/icons-vue'

import type { StudentLog } from '@/types/student'

defineProps<{ logs: StudentLog[] }>()

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
      <button type="button" class="text-action">查看全部 <Right /></button>
    </div>
    <el-empty v-if="logs.length === 0" description="设备尚未上传日志" :image-size="72" />
    <div v-else class="log-list">
      <article v-for="log in logs" :key="log.id" class="log-row">
        <div class="log-meta">
          <time>{{ new Date(log.occurred_at).toLocaleTimeString('zh-CN') }}</time>
          <el-tag size="small" :type="levelType(log.level)" round>{{ log.level }}</el-tag>
          <p>{{ log.message }}</p>
        </div>
        <code v-if="log.event_code">{{ log.event_code }}</code>
        <span v-if="log.is_test_data" class="test-label">测试</span>
      </article>
    </div>
  </article>
</template>
