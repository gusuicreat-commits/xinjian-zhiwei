<script setup lang="ts">
import { Calendar, Clock, Cpu, DataLine, Timer } from '@element-plus/icons-vue'
import { computed } from 'vue'

import type { CurrentTask, StudentDevice } from '@/types/student'

const props = defineProps<{ task: CurrentTask; device: StudentDevice }>()

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN') : '尚未上报'
}

const statusLabels = { online: '在线', offline: '离线', never_seen: '未连接' }
const statusTypes = { online: 'success', offline: 'danger', never_seen: 'info' } as const
const taskTitle = computed(() => props.task.title || '当前实验任务待配置')
</script>

<template>
  <section class="overview-grid">
    <article class="panel-card task-card">
      <div class="task-icon"><DataLine /></div>
      <div class="task-main">
        <p class="panel-eyebrow"><Calendar /> 当前实验任务</p>
        <h2>{{ taskTitle }}</h2>
        <p class="task-description">{{ task.notice }}</p>
        <div class="task-meta-row">
          <span><Timer /> 任务状态</span>
          <strong>{{ task.configured ? '已配置' : '待配置' }}</strong>
          <span><Clock /> 模板标识</span>
          <strong>{{ task.template_id || '尚未提供' }}</strong>
        </div>
      </div>
    </article>

    <article class="panel-card device-card">
      <div class="panel-heading">
        <h2><Cpu /> 设备状态</h2>
        <el-tag :type="statusTypes[device.status]" effect="light" round>
          <span class="status-dot" />{{ statusLabels[device.status] }}
        </el-tag>
      </div>
      <dl class="device-facts">
        <div>
          <dt>最近心跳</dt>
          <dd>{{ formatTime(device.last_seen_at) }}</dd>
        </div>
        <div>
          <dt>固件版本</dt>
          <dd>{{ device.firmware_version || '未提供' }}</dd>
        </div>
        <div>
          <dt>设备标识</dt>
          <dd>{{ device.device_id }}</dd>
        </div>
        <div>
          <dt>数据状态</dt>
          <dd>{{ device.is_test_fixture ? '测试设备' : '未标记为测试设备' }}</dd>
        </div>
      </dl>
    </article>
  </section>
</template>
