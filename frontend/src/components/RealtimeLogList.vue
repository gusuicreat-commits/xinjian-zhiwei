<script setup lang="ts">
import { logLevel, logSummary } from '@/presentation/userLanguage'
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
        <div class="log-entry-meta">
          <time :datetime="log.occurred_at">{{
            new Date(log.occurred_at).toLocaleTimeString('zh-CN', { hour12: false })
          }}</time>
          <span class="log-severity" :class="`severity-${log.level.toLowerCase()}`">{{
            logLevel(log.level)
          }}</span>
          <span v-if="log.is_test_data" class="log-source">测试记录</span>
        </div>
        <p class="log-description">
          {{ logSummary({ event_code: log.event_code, message: log.message }) }}
        </p>
        <details class="log-original">
          <summary>查看原始日志</summary>
          <div class="log-original-body">
            <code
              >{{ log.level
              }}<template v-if="log.event_code"> · {{ log.event_code }}</template></code
            >
            <p>{{ log.message }}</p>
          </div>
        </details>
      </article>
    </div>
    <nav v-if="logs.length > pageSize" class="log-pagination" aria-label="日志分页">
      <button type="button" :disabled="page === 1" @click="page -= 1">上一页</button>
      <span aria-live="polite">第 {{ page }} / {{ pageCount }} 页</span>
      <button type="button" :disabled="page === pageCount" @click="page += 1">下一页</button>
    </nav>
  </article>
</template>

<style scoped>
.log-panel .log-list {
  padding: 0 4px 0 0;
  scrollbar-gutter: stable;
}
.log-panel .log-row {
  min-height: 0;
  padding: 16px 4px;
}
.log-entry-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  font-size: 12px;
  line-height: 1.5;
}
.log-entry-meta time {
  color: #6a7075;
  font-variant-numeric: tabular-nums;
}
.log-severity {
  padding: 1px 7px;
  color: #525b64;
  background: #eaecea;
  border-radius: 4px;
  font-weight: 600;
}
.severity-error,
.severity-critical {
  color: #963d49;
  background: #f4e7e9;
}
.severity-warn,
.severity-warning {
  color: #805e21;
  background: #f3ecdc;
}
.log-source {
  color: #6a7075;
}
.log-description {
  margin: 8px 0 6px;
  color: #30383e;
  font-size: 14px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}
.log-original {
  color: #64717b;
  font-size: 12px;
  line-height: 1.6;
}
.log-original > summary {
  cursor: pointer;
  width: fit-content;
  padding: 3px 0;
}
.log-original > summary:hover {
  color: #243bff;
}
.log-original > summary:focus-visible {
  outline: 2px solid #243bff;
  outline-offset: 3px;
}
.log-original-body {
  margin-top: 8px;
  padding: 10px 12px;
  border-left: 2px solid #d8dcd9;
  background: #efefeb;
  overflow-wrap: anywhere;
}
.log-row .log-original-body code {
  display: block;
  margin: 0;
  color: #525d66;
  font-size: 11px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.log-original-body p {
  margin: 6px 0 0;
  white-space: pre-wrap;
}
</style>
