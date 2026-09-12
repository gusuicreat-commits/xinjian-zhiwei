<script setup lang="ts">
import { FEEDBACK_ACTION_LABELS } from '@/api/feedbackRetry'
import type { DashboardState } from '@/stores/studentDashboard'
import type { FeedbackRecovery, FeedbackRecoveryTarget } from '@/types/student'

defineProps<{
  state: DashboardState
  recovery: FeedbackRecovery | null
  pending: FeedbackRecoveryTarget[]
  error: string
  localError: string
  loading: boolean
  currentDiagnosisId?: string
}>()
const emit = defineEmits<{
  retry: []
  recover: [target: FeedbackRecoveryTarget]
}>()
</script>

<template>
  <section class="feedback-recovery" aria-label="反馈确认记录">
    <template v-if="error || localError">
      <el-alert :title="error || localError" type="warning" :closable="false" show-icon />
      <el-button :loading="state === 'loading'" :disabled="loading" @click="emit('retry')">
        重新查询反馈状态
      </el-button>
    </template>
    <p v-if="state === 'loading'" role="status">正在查询反馈确认状态…</p>
    <template v-if="pending.length">
      <h3>上一条反馈待确认</h3>
      <p>请先确认原反馈，系统会继续处理同一次操作。打开页面不会自动提交。</p>
      <div
        v-for="item in pending"
        :key="`${item.source}:${item.diagnosis_result_id}:${item.payload.request_id}`"
        class="feedback-recovery-item"
      >
        <p>
          <strong>{{ FEEDBACK_ACTION_LABELS[item.payload.action] }}</strong>
          <span v-if="item.diagnosis_result_id !== currentDiagnosisId">（之前的诊断）</span>
        </p>
        <p v-if="item.payload.note">原备注：{{ item.payload.note }}</p>
        <p v-if="item.source === 'browser'" class="feedback-recovery-meta">
          本页保留的提交记录，服务器是否收到仍待确认。
        </p>
        <p v-else-if="item.created_at" class="feedback-recovery-meta">
          提交时间：{{ new Date(item.created_at).toLocaleString() }}
        </p>
        <el-button
          type="primary"
          :loading="loading"
          :disabled="state !== 'ready'"
          @click="emit('recover', item)"
          >继续确认原反馈</el-button
        >
      </div>
    </template>
    <p v-if="recovery?.has_more_pending">
      还有其他反馈待确认。处理本页记录后，请刷新查看剩余记录。
    </p>
    <p v-if="recovery?.latest_applied" role="status">
      最近一次反馈已确认：{{ FEEDBACK_ACTION_LABELS[recovery.latest_applied.action] }}
      <span v-if="recovery.latest_applied.diagnosis_result_id !== currentDiagnosisId"
        >（之前的诊断）</span
      >
      · {{ new Date(recovery.latest_applied.created_at).toLocaleString() }}
    </p>
  </section>
</template>

<style scoped>
.feedback-recovery {
  display: grid;
  gap: 0.75rem;
}
.feedback-recovery:empty {
  display: none;
}
.feedback-recovery p,
.feedback-recovery h3 {
  margin: 0;
}
.feedback-recovery-item {
  display: grid;
  justify-items: start;
  gap: 0.5rem;
  padding: 1rem;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-light);
}
.feedback-recovery-meta {
  color: var(--el-text-color-secondary);
  font-size: 0.875rem;
}
</style>
