<script setup lang="ts">
import { issueLabel } from '@/presentation/userLanguage'
import type { CheckReceipt } from '@/api/diagnosisChecks'
defineProps<{ check?: CheckReceipt | null }>()
const displayTime = (value?: string | null) =>
  value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '未知'
const labels: Record<string, string> = {
  prior_evidence_still_matches: '原异常记录仍在检查窗口内，新增记录不足以确认变化',
  closed_previous_incident: '此前问题已结束，本次异常另记为新一轮问题',
  late_or_unverified: '新收到的记录早于处理结束或时间不明，无法确认当前状态',
  newly_detected: '本次检测到此异常',
  still_detected: '新记录中仍检测到异常',
  no_new_related_data: '没有新的相关记录，无法确认变化',
  not_detected_unverified: '本次未检测到该异常，恢复尚未确认',
  verified_recovery: '满足已配置的恢复判据，不代表整套硬件验收',
}
</script>
<template>
  <section class="check-summary" aria-label="本次检查依据">
    <strong>本次检查依据</strong>
    <template v-if="check">
      <p>检查时间：{{ displayTime(check.checked_at) }}</p>
      <p v-if="check.status === 'pending'">上次检查尚未确认，请确认原请求；刷新不会重新执行。</p>
      <p v-else-if="check.status === 'no_new_data'">暂无新的检查依据，保留上次诊断。</p>
      <p v-else-if="check.data_change === 'monitoring_only'">
        本次仅更新监测状态，没有新增相关采样。
      </p>
      <p v-else>与上次相比，新增相关记录 {{ check.new_records ?? 0 }} 条。</p>
      <p v-if="check.data_window?.latest">
        数据记录时间范围：{{ displayTime(check.data_window.earliest) }} —
        {{ displayTime(check.data_window.latest) }}
      </p>
      <p>{{ check.time_notice }}</p>
      <ul v-if="check.status !== 'no_new_data'">
        <li v-for="issue in check.issues ?? []" :key="issue.episode_id">
          {{ issue.label || issueLabel(issue.error_type) }}（{{
            issue.scope?.keys.join('、') || '设备范围'
          }}）：{{ labels[issue.observation] ?? '尚未确认' }}
          <span
            >；检查时处理状态：{{
              issue.handling_status === 'resolved'
                ? '已结束（不等于硬件恢复）'
                : issue.handling_status === 'escalated'
                  ? '等待教师处理'
                  : '处理中'
            }}</span
          >
        </li>
      </ul>
    </template>
    <p v-else>尚无本次检查对比记录。历史数据不会自动补算。</p>
    <p>重新检查只分析已上传数据，不会控制开发板采样；“仍未解决”继续使用原诊断数据。</p>
  </section>
</template>
<style scoped>
.check-summary {
  padding: 16px;
  margin: 12px 0;
  border: 1px solid #bac6d2;
  line-height: 1.65;
}
.check-summary p,
.check-summary li {
  font-size: 14px;
  overflow-wrap: anywhere;
}
</style>
