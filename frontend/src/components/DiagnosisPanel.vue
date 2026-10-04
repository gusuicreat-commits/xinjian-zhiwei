<script setup lang="ts">
import MemorySummary from './MemorySummary.vue'
import { REVIEW_MODE } from '@/review/fixtures'
import { issueLabel, readableText, evidenceText } from '@/presentation/userLanguage'
import TeachingReferencePanel from './TeachingReferencePanel.vue'
import DiagnosisCheckPanel from './DiagnosisCheckPanel.vue'
import { CircleCheck, Promotion, QuestionFilled } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

import type {
  FeedbackAction,
  AIExplanationResponse,
  AIStatus,
  DiagnosisWorkflow,
  DeviceStateExplanation,
  StudentDiagnosis,
  StudentFeedback,
  StudentGuidance,
  StudentIntervention,
  StudentDashboard,
} from '@/types/student'

const props = defineProps<{
  view?: 'work' | 'reference'
  issues?: StudentDashboard['issues']
  diagnosis: StudentDiagnosis | null
  guidance: StudentGuidance[]
  feedback: StudentFeedback | null
  intervention: StudentIntervention | null
  interventions?: StudentIntervention[]
  feedbackLoading: boolean
  feedbackBlocked?: boolean
  aiStatus: AIStatus
  aiExplanation: AIExplanationResponse | null
  aiLoading: boolean
  workflow: DiagnosisWorkflow | null
  workflowLoading: boolean
  summaryAtTop?: boolean
  readOnly?: boolean
  checkPending?: boolean
  hasExperimentSession: boolean
  deviceStateExplanation: DeviceStateExplanation
}>()

const emit = defineEmits<{
  feedback: [action: FeedbackAction, episodeId: string | null]
  requestAi: []
  requestWorkflow: []
}>()

const selectedIssue = ref<string | null>(null)
watch(
  [() => props.diagnosis?.id, () => props.issues?.map((issue) => issue.id).join('|')],
  ([diagnosisId], previous) => {
    if (
      diagnosisId !== previous?.[0] ||
      !props.issues?.some((issue) => issue.id === selectedIssue.value)
    ) {
      selectedIssue.value = props.issues?.length === 1 ? props.issues[0]!.id : null
    }
  },
  { immediate: true },
)
const isMultiIssue = computed(() => (props.issues?.length ?? 0) > 1)
const currentAiExplanation = computed(() =>
  props.aiExplanation?.diagnosis_result_id === props.diagnosis?.id ? props.aiExplanation : null,
)
const focusedFeedback = computed(() =>
  isMultiIssue.value
    ? props.feedback?.episode_id === selectedIssue.value
      ? props.feedback
      : null
    : props.feedback,
)
const issueSelectionRequired = computed(
  () => (props.issues?.length ?? 0) > 1 && !selectedIssue.value,
)

const actionLabels: Record<FeedbackAction, string> = {
  resolved: '问题已解决',
  unresolved: '仍未解决',
  request_teacher_help: '请求教师协助',
}
const confidenceLabels = { low: '低', medium: '中', high: '高' }
const workflowStatusLabels: Record<
  DiagnosisWorkflow['status'],
  {
    label: string
    type: 'primary' | 'success' | 'warning' | 'info' | 'danger'
  }
> = {
  created: { label: '流程已创建', type: 'info' },
  collecting: { label: '正在采集诊断上下文', type: 'primary' },
  deterministic_analysis: { label: '正在执行确定性诊断', type: 'primary' },
  retrieving: { label: '正在检索已审核知识', type: 'primary' },
  ai_analysis: { label: '正在生成辅助解释', type: 'primary' },
  waiting_feedback: { label: '等待你的反馈', type: 'warning' },
  waiting_teacher: { label: '等待教师审核', type: 'warning' },
  completed: { label: '流程完成', type: 'success' },
  rejected: { label: '教师已驳回', type: 'danger' },
  failed: { label: '流程失败，确定性规则结果仍可用', type: 'danger' },
}
const primaryMatch = computed(() => props.diagnosis?.matches[0] ?? null)
const technicalDetails = computed(() => props.deviceStateExplanation.technical_details)
const evidenceItems = computed(
  () => props.diagnosis?.matches.flatMap((match) => match.evidence) ?? [],
)
const focusedGuidance = computed(() =>
  (props.issues?.length ?? 0) > 1
    ? props.guidance.filter((item) => item.episode_id === selectedIssue.value)
    : props.guidance,
)
const rankedCauses = computed(() => focusedGuidance.value.flatMap((item) => item.ranked_causes))
const hints = computed(() => focusedGuidance.value.flatMap((item) => item.hints))
const focusedIntervention = computed(() =>
  (props.issues?.length ?? 0) > 1
    ? (props.interventions?.find((item) => item.episode_id === selectedIssue.value) ?? null)
    : props.intervention,
)
const workflowRuleHits = computed(() => {
  const pending = props.workflow?.review_request?.rule_hits ?? []
  return pending.length ? pending : (props.workflow?.final_result?.rule_hits ?? [])
})
const workflowCandidates = computed(() => {
  const pending = props.workflow?.review_request?.candidates ?? []
  return pending.length ? pending : (props.workflow?.final_result?.candidate_causes ?? [])
})
const workflowKnowledge = computed(() => {
  const pending = props.workflow?.review_request?.retrieved_chunks ?? []
  return pending.length ? pending : (props.workflow?.final_result?.knowledge_references ?? [])
})
const approvedWorkflowKnowledge = computed(() =>
  workflowKnowledge.value.filter((item) => item.metadata?.review_status === 'approved'),
)
const workflowExplanation = computed(() => {
  const finalResult = props.workflow?.final_result
  const aiResult = props.workflow?.review_request?.ai_result
  const deterministicResult = props.workflow?.review_request?.deterministic_result
  if (finalResult?.summary) return finalResult
  if (aiResult?.summary) return aiResult
  if (deterministicResult?.summary) return deterministicResult
  return finalResult ?? aiResult ?? deterministicResult ?? null
})
const workflowLimitations = computed(() => {
  if (props.workflow?.final_result) return props.workflow.final_result.limitations ?? []
  const aiLimitations = props.workflow?.review_request?.ai_result?.limitations ?? []
  if (aiLimitations.length) return aiLimitations
  return props.workflow?.review_request?.deterministic_result?.limitations ?? []
})
const workflowStatus = computed(() =>
  props.workflow
    ? workflowStatusLabels[props.workflow.status]
    : ({ label: '可按需运行', type: 'info' } as const),
)
const workflowStatusMessage = computed(() => {
  if (!props.workflow) return '需要时可启动辅助诊断，系统会整理设备记录并给出下一步建议。'
  const messages: Record<DiagnosisWorkflow['status'], string> = {
    created: '辅助诊断已创建，正在准备设备记录。',
    collecting: '正在整理本次实验的设备记录。',
    deterministic_analysis: '正在根据设备记录分析异常原因。',
    retrieving: '正在对照已审核的操作资料。',
    ai_analysis: '正在把诊断结果整理成易懂的说明。',
    waiting_feedback: '请按当前提示排查并反馈；“仍未解决”继续原指导，不会重新采样。',
    waiting_teacher: '结果已提交教师确认，确认前不会作为最终建议发布。',
    completed: '辅助诊断已完成，可按建议继续排查或实验。',
    rejected: '教师认为当前信息不足，请补充设备记录后再试。',
    failed: '辅助诊断暂时未完成，上方的规则诊断结果仍然可用。',
  }
  return messages[props.workflow.status]
})
const workflowBasis = computed(() => {
  const items: string[] = []
  if (workflowRuleHits.value.length) items.push('设备运行记录')
  if (workflowCandidates.value.length) items.push('可能原因分析')
  if (approvedWorkflowKnowledge.value.length) {
    items.push(`${approvedWorkflowKnowledge.value.length} 份已审核操作资料`)
  }
  return items
})
const workflowActionLabel = computed(() =>
  props.checkPending ? '确认上次检查结果' : props.diagnosis ? '用最新数据重新检查' : '检查当前数据',
)
const interventionStatus = computed(() => {
  if (!focusedIntervention.value) return null
  const statusCopy = {
    open: {
      title: '求助已提交，等待教师认领',
      detail: '该请求已经进入教师端异常处置队列。',
      type: 'warning',
    },
    claimed: {
      title: '教师正在处理',
      detail: '工单已被教师认领，请留意后续处理结果。',
      type: 'primary',
    },
    resolved: {
      title: '教师已完成工单处理（不代表硬件复测通过）',
      detail: focusedIntervention.value.resolution_summary || '教师已完成本次协助处理。',
      type: 'success',
    },
    unconfirmed: {
      title: '教师暂时无法确认',
      detail: '当前证据不足，教师可能需要更多日志或现场信息。',
      type: 'warning',
    },
    closed: {
      title: '教师协助已关闭',
      detail: focusedIntervention.value.resolution_summary || '本次教师协助流程已经结束。',
      type: 'info',
    },
  } as const
  return statusCopy[focusedIntervention.value.status]
})

const focusedIssue = computed(() => props.issues?.find((issue) => issue.id === selectedIssue.value))
const focusTitle = computed(() => {
  if (issueSelectionRequired.value) return '当前有多个问题，请先选择本次排查对象'
  if (focusedIssue.value && isMultiIssue.value)
    return `${focusedIssue.value.scope?.keys.join('、') || '范围待确认'} · ${issueLabel(focusedIssue.value.error_type)}`
  return props.deviceStateExplanation.status_title
})
const nextStep = computed(() => {
  if (props.readOnly) return '先恢复连接并刷新状态；下方保留的是上次读取内容，暂不能提交操作。'
  if (props.checkPending) return '先确认上次检查结果，系统会沿用原请求，不重复开始。'
  if (!props.diagnosis) return '先检查已上传的数据，生成本次实验的判断依据。'
  if (issueSelectionRequired.value)
    return '选择一个问题后，查看它对应的排查步骤，再针对这个问题反馈。'
  if (props.feedbackBlocked) return '请先查看上方的反馈恢复提示，确认原反馈或重新查询状态。'
  if (focusedIssue.value?.status === 'resolved')
    return '这轮问题已结束；如有后续上传记录，可以重新检查，不能据此认定硬件已恢复。'
  if (hints.value.length) return '按下方当前开放的步骤排查，再反馈这个问题的结果。'
  if (isMultiIssue.value)
    return '这个问题暂无适用排查步骤，可请求教师协助；不要套用其他问题的建议。'
  return props.deviceStateExplanation.next_step
})
const focusLimitation = computed(() =>
  issueSelectionRequired.value
    ? '不同问题的原因和步骤可能不同，不能将一次反馈当成全部解决。'
    : focusedIssue.value
      ? '当前异常及候选原因需要结合这个问题的证据核验；处理结束不等于硬件恢复。'
      : '已有记录不等于现场验证；缺少证据时不会自动认定硬件正常。',
)
const requiredLimitations = computed(() => {
  const byText = new Map<string, { text: string; sources: string[] }>()
  const groups: Array<[string, string[]]> = [
    [
      '规则诊断',
      props.diagnosis?.explanation?.limitations ??
        props.diagnosis?.deterministic_result?.limitations ??
        [],
    ],
    ['已保存 AI 解释', currentAiExplanation.value?.explanation?.limitations ?? []],
    ['本工作流', workflowLimitations.value],
  ]
  for (const [source, values] of groups) {
    for (const text of values) {
      const entry = byText.get(text)
      if (entry) {
        if (!entry.sources.includes(source)) entry.sources.push(source)
      } else byText.set(text, { text, sources: [source] })
    }
  }
  return [...byText.values()]
})
const workflowReasoning = computed(() => props.workflow?.final_result?.ai_reasoning)
const verificationRequests = computed(() =>
  workflowReasoning.value?.projection_version === 'reasoning-facts-v2'
    ? (workflowReasoning.value.verification_requests ?? []).filter(
        (item) => item.source === 'rules',
      )
    : [],
)
const reportedEvidence = computed(
  () =>
    props.workflow?.reported_evidence ??
    (workflowReasoning.value?.projection_version === 'reasoning-facts-v2'
      ? (workflowReasoning.value.reported_evidence ?? [])
      : []),
)
const sourceLabel = (source: string) =>
  ({
    rule_engine: '规则记录',
    sensor_reading: '传感器上报',
    device_report: '设备上报',
    device_log: '设备日志',
    log: '日志记录',
    student_report: '学生报告',
  })[source] ?? '来源上报'
const reportStatusLabel = (status: string) =>
  ({
    observed: '已记录',
    valid: '有效记录',
    invalid: '无效记录',
    unknown: '尚未核实',
    conflicting: '存在冲突',
  })[status] ?? '记录状态待核验'
const workflowNeedsAttention = computed(
  () =>
    props.workflow?.status === 'waiting_teacher' ||
    props.workflow?.status === 'rejected' ||
    props.workflow?.status === 'failed',
)
const check = computed(() => props.workflow?.check)
const canEnhance = computed(() => props.aiStatus.ai_enabled && props.aiStatus.provider_configured)
const feedbackDisabled = computed(
  () =>
    props.readOnly ||
    props.feedbackBlocked ||
    issueSelectionRequired.value ||
    !props.hasExperimentSession ||
    props.checkPending ||
    focusedIssue.value?.status === 'resolved',
)
function sendFeedback(action: FeedbackAction) {
  if (!feedbackDisabled.value) emit('feedback', action, selectedIssue.value)
}

function scorePercent(score: number): number {
  return Math.min(100, Math.round(score <= 1 ? score * 100 : score))
}

function reviewActionLabel(action: 'approve' | 'edit' | 'reject'): string {
  return { approve: '批准', edit: '修订并批准', reject: '驳回' }[action]
}

function formatReviewTime(value?: string | null): string {
  if (!value) return '未知'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div id="diagnosis" class="diagnosis-suite task-diagnosis">
    <div v-if="issues && issues.length > 1" class="issue-picker">
      <label for="diagnosis-issue">选择本次排查和反馈的问题</label>
      <el-select id="diagnosis-issue" v-model="selectedIssue" placeholder="请选择一个问题">
        <el-option
          v-for="issue in issues"
          :key="issue.id"
          :value="issue.id"
          :label="`${issueLabel(issue.error_type)} · ${issue.scope?.keys.join('、') || '设备范围'} · ${issue.status === 'resolved' ? '已结束（不代表硬件已验证）' : '处理中'}`"
        />
      </el-select>
      <p v-if="focusedIssue" class="focus-target">
        当前对象：{{ focusedIssue.scope?.keys.join('、') || '范围待确认' }} ·
        {{ focusedIssue.status === 'resolved' ? '处理已结束' : '处理中' }}
      </p>
    </div>

    <div v-show="view !== 'reference'" class="work-view">
      <section class="next-step-card" aria-label="现在该做什么">
        <div class="next-step-heading">
          <span
            >当前判断<span v-if="!isMultiIssue" class="summary-source">
              ·
              {{
                deviceStateExplanation.source === 'ai' ? '已保存的 AI 综合解释' : '规则解释'
              }}</span
            ></span
          >
          <el-tag v-if="diagnosis?.is_test_data" type="warning">测试结果</el-tag>
        </div>
        <h2>{{ focusTitle }}</h2>
        <p
          v-if="!isMultiIssue && deviceStateExplanation.status_summary !== focusTitle"
          class="primary-summary"
        >
          {{ readableText(deviceStateExplanation.status_summary) }}
        </p>
        <p class="primary-limitation"><strong>还不能确定什么：</strong>{{ focusLimitation }}</p>
        <ul v-if="requiredLimitations.length" class="required-limitations" aria-label="诊断限制">
          <li v-for="limitation in requiredLimitations" :key="limitation.text">
            {{ isMultiIssue ? '整次诊断限制' : '限制' }}（{{ limitation.sources.join('、') }}）：{{
              limitation.text
            }}
          </li>
        </ul>
        <p v-if="workflowReasoning?.status === 'unknown'" class="required-notice">
          本次分析仍为未知，现有证据不足以确认原因。
        </p>
        <p v-if="workflowReasoning?.conflict" class="required-notice">
          本次证据存在冲突，暂不能确认原因。
        </p>
        <ul v-if="verificationRequests.length" class="required-limitations" aria-label="待核验事项">
          <li v-for="item in verificationRequests" :key="item.text">
            建议核验（尚未确认）：{{ item.text }}
          </li>
        </ul>
        <ul v-if="reportedEvidence.length" class="required-limitations" aria-label="来源记录">
          <li v-for="item in reportedEvidence" :key="item.id">
            来源记录（{{ sourceLabel(item.source) }}；{{
              reportStatusLabel(item.status)
            }}，不等于根因确认）：{{ item.fact }}
          </li>
        </ul>
        <p v-if="workflowNeedsAttention" class="required-notice">
          {{ workflowStatus.label }}：{{ workflowStatusMessage }}
        </p>
        <p class="next-action"><strong>接下来：</strong>{{ nextStep }}</p>
        <div class="next-step-actions">
          <el-button
            :type="checkPending || !diagnosis ? 'primary' : 'default'"
            :loading="workflowLoading"
            :disabled="REVIEW_MODE || !hasExperimentSession || workflowLoading || readOnly"
            :title="REVIEW_MODE ? '离线演示仅展示固定记录，不支持重新检查' : undefined"
            @click="!readOnly && hasExperimentSession && emit('requestWorkflow')"
            >{{ workflowActionLabel }}</el-button
          >
        </div>
        <p class="next-step-note">
          重新检查分析已上传记录；“仍未解决”继续原指导。刷新页面不会启动诊断。
        </p>
        <p v-if="!hasExperimentSession" class="next-step-note">
          请先连接有效的实验会话，再检查当前数据。
        </p>
        <div v-if="check" class="check-context" aria-label="检查时效与范围">
          <p>检查时间：{{ check.checked_at ? formatReviewTime(check.checked_at) : '尚未确认' }}</p>
          <p v-if="check.status === 'pending'">
            上次检查尚未确认，请确认原请求；刷新不会重新执行。
          </p>
          <p v-else-if="check.status === 'no_new_data'">暂无新的检查依据，保留上次诊断。</p>
          <p v-else-if="check.data_change === 'monitoring_only'">
            本次仅更新监测状态，没有新增相关采样。
          </p>
          <p v-else>与上次相比，新增相关记录 {{ check.new_records ?? 0 }} 条。</p>
          <p v-if="check.data_window?.latest">
            数据记录时间范围：{{ formatReviewTime(check.data_window.earliest) }} —
            {{ formatReviewTime(check.data_window.latest) }}
          </p>
          <p v-if="check.time_notice">{{ check.time_notice }}</p>
        </div>
        <p v-else-if="diagnosis" class="next-step-note">
          诊断记录时间：{{
            formatReviewTime(diagnosis.evaluated_at)
          }}。尚无本次检查对比记录，不能据此判断设备当前已恢复。
        </p>
      </section>

      <section v-if="primaryMatch" class="guidance-work" aria-label="当前问题的排查与反馈">
        <h3>分层排查步骤</h3>
        <p v-if="issueSelectionRequired" class="empty-copy">
          请先选择一个问题，再查看对应步骤和提交反馈。
        </p>
        <template v-else>
          <ol class="hint-steps">
            <li
              v-for="(hint, index) in hints"
              :key="`${hint.cause_id}-${hint.level}-${index}`"
              class="guidance-hint"
            >
              <span :class="`level-${hint.level}`">提示 {{ hint.level }}</span>
              <div class="hint-content">
                <p class="hint-action">{{ hint.text }}</p>
                <TeachingReferencePanel :material="hint.teaching" />
              </div>
            </li>
          </ol>
          <p v-if="hints.length === 0" class="empty-copy">
            尚无可用排查提示；请保留现有记录并请求教师协助。
          </p>
        </template>
        <div class="feedback-area">
          <el-alert
            v-if="interventionStatus"
            class="intervention-status-alert"
            :title="interventionStatus.title"
            :description="interventionStatus.detail"
            :type="interventionStatus.type"
            :closable="false"
            show-icon
          />
          <p v-if="focusedFeedback" class="feedback-record">
            <CircleCheck /> 已记录：{{ actionLabels[focusedFeedback.action] }}
          </p>
          <p class="feedback-context">
            反馈只针对当前问题。“问题已解决”记录你的反馈，不代表硬件已通过复测。
          </p>
          <div class="feedback-actions">
            <el-button
              type="success"
              :loading="feedbackLoading"
              :disabled="feedbackDisabled"
              @click="sendFeedback('resolved')"
              ><CircleCheck /> 问题已解决</el-button
            >
            <el-button
              type="warning"
              :loading="feedbackLoading"
              :disabled="feedbackDisabled"
              @click="sendFeedback('unresolved')"
              ><QuestionFilled /> 仍未解决</el-button
            >
            <el-button
              type="primary"
              :loading="feedbackLoading"
              :disabled="feedbackDisabled"
              @click="sendFeedback('request_teacher_help')"
              ><Promotion /> 请求教师协助</el-button
            >
          </div>
        </div>
      </section>

      <details class="diagnosis-records">
        <summary>本次诊断依据与记录</summary>
        <p v-if="isMultiIssue" class="record-scope">
          下面的设备状态和规则记录属于整次诊断；所选问题的步骤与反馈以上方为准。
        </p>
        <section class="record-section diagnosis-summary">
          <h3>
            设备状态记录 ·
            {{ deviceStateExplanation.source === 'ai' ? '已保存的 AI 综合解释' : '规则解释' }}
          </h3>
          <p v-if="isMultiIssue">{{ readableText(deviceStateExplanation.status_summary) }}</p>
          <p><strong>这意味着什么：</strong>{{ readableText(deviceStateExplanation.meaning) }}</p>
          <details class="technical-details">
            <summary>查看技术详情</summary>
            <dl class="technical-facts">
              <dt>问题类型原始编号</dt>
              <dd>{{ issues?.map((issue) => issue.error_type).join('、') }}</dd>
              <dt>设备状态说明原文</dt>
              <dd>{{ deviceStateExplanation.status_summary }}</dd>
              <dt>解释原文</dt>
              <dd>
                {{ currentAiExplanation?.explanation?.summary || diagnosis?.explanation?.summary }}
              </dd>
              <dt>工作流解释原文</dt>
              <dd>{{ workflowExplanation?.summary }}</dd>
              <div>
                <dt>设备状态</dt>
                <dd>{{ technicalDetails.device.status }}</dd>
              </div>
              <div>
                <dt>原始错误码</dt>
                <dd>
                  <code>{{ technicalDetails.error_code || '—' }}</code>
                </dd>
              </div>
              <div v-if="technicalDetails.retry_count !== undefined">
                <dt>连续重试</dt>
                <dd>{{ technicalDetails.retry_count }} 次</dd>
              </div>
              <div>
                <dt>固件版本</dt>
                <dd>{{ technicalDetails.device.firmware_version || '—' }}</dd>
              </div>
            </dl>
            <section v-if="technicalDetails.logs.length" class="technical-section">
              <strong>原始日志</strong>
              <ul>
                <li v-for="log in technicalDetails.logs" :key="log.id">
                  <code>{{ log.event_code || log.level }}</code
                  ><span>{{ log.message }}</span>
                </li>
              </ul>
            </section>
            <section v-if="technicalDetails.sensor_readings.length" class="technical-section">
              <strong>传感器数值</strong>
              <ul>
                <li v-for="reading in technicalDetails.sensor_readings" :key="reading.id">
                  <code>{{ reading.sensor_type }} / {{ reading.metric_key }}</code
                  ><span>{{ reading.value }} {{ reading.unit || '' }}</span>
                </li>
              </ul>
            </section>
            <section v-if="technicalDetails.rule_hits.length" class="technical-section">
              <strong>规则命中</strong>
              <ul>
                <li v-for="hit in technicalDetails.rule_hits" :key="hit.rule_id">
                  <code>{{ hit.rule_id }}</code
                  ><span>{{ hit.summary }}</span>
                </li>
              </ul>
            </section>
            <section v-if="technicalDetails.fault_tree_evidence.length" class="technical-section">
              <strong>故障树证据</strong>
              <ul>
                <li v-for="tree in technicalDetails.fault_tree_evidence" :key="tree.tree_id">
                  <code>{{ tree.tree_id }}</code
                  ><span>{{ tree.tree_title }} · 提示层级 {{ tree.hint_level }}</span>
                </li>
              </ul>
            </section>
          </details>
        </section>

        <section v-if="primaryMatch" class="record-section evidence-panel">
          <h3>{{ isMultiIssue ? '整次诊断的规则证据' : '证据展示' }}</h3>
          <ul class="evidence-list">
            <li v-for="(item, index) in evidenceItems" :key="`${item.fact}-${index}`">
              <span class="evidence-bullet" /><span
                >{{ evidenceText(item) }}
                <details>
                  <summary>查看原始证据</summary>
                  <pre>{{ JSON.stringify(item, null, 2) }}</pre>
                </details></span
              >
            </li>
          </ul>
          <p v-if="!evidenceItems.length" class="empty-copy">当前规则未返回可展示证据。</p>
        </section>
        <section v-if="primaryMatch && !issueSelectionRequired" class="record-section causes-panel">
          <h3>当前问题的可能原因排序</h3>
          <p>支持分只表示检查排序，不是发生概率，也不代表已确认根因。</p>
          <ol class="cause-ranking">
            <li v-for="(cause, index) in rankedCauses" :key="cause.cause_id">
              <span class="rank-index">{{ index + 1 }}</span>
              <div class="cause-copy">
                <strong>{{ cause.title }}</strong
                ><small>证据等级 {{ confidenceLabels[cause.confidence] }}</small>
              </div>
              <b>支持分 {{ scorePercent(cause.score) }}/100</b>
            </li>
          </ol>
          <p v-if="!rankedCauses.length" class="empty-copy">尚无有证据支持的候选原因。</p>
        </section>

        <section v-if="diagnosis" class="record-section ai-explanation-panel">
          <h3>已保存的诊断解释</h3>
          <el-tag
            :type="currentAiExplanation?.status === 'succeeded' ? 'success' : 'info'"
            size="small"
            >{{
              currentAiExplanation?.status === 'succeeded' ? '已保存 AI 解释' : '确定性结果'
            }}</el-tag
          >
          <template v-if="currentAiExplanation?.explanation">
            <p>{{ readableText(currentAiExplanation.explanation.summary) }}</p>
            <p>{{ currentAiExplanation.notice }}</p>
            <ul v-if="!isMultiIssue">
              <li v-for="step in currentAiExplanation.explanation.steps" :key="step">{{ step }}</li>
            </ul>
            <p v-if="currentAiExplanation.explanation.limitations.length">
              此解释的限制：{{
                readableText(currentAiExplanation.explanation.limitations.join('；'))
              }}
            </p>
          </template>
          <template v-else>
            <p>{{ readableText(diagnosis.explanation?.summary || primaryMatch?.summary) }}</p>
            <p>当前建议由确定性规则、故障树和已审核知识生成；AI 不是诊断前置条件。</p>
            <p v-if="currentAiExplanation?.notice">{{ currentAiExplanation.notice }}</p>
          </template>
          <p class="ai-availability">
            当前 AI 增强{{
              canEnhance ? '可用' : '未启用'
            }}。这只描述当前配置，不改变已保存解释的来源。
          </p>
          <el-button
            plain
            :loading="aiLoading"
            :disabled="!canEnhance || readOnly || !hasExperimentSession || checkPending"
            @click="canEnhance && !readOnly && emit('requestAi')"
            >{{ canEnhance ? '按需增强解释' : 'AI 增强未启用' }}</el-button
          >
          <details>
            <summary>查看当前配置与版本</summary>
            <p>{{ aiStatus.notice }}</p>
            <small
              >模型服务 {{ aiStatus.provider_configured ? '已配置' : '待配置' }} · 提示模板版本
              {{ aiStatus.prompt_version }}</small
            >
          </details>
        </section>
        <section class="record-section ai-explanation-panel">
          <h3>辅助诊断进度</h3>
          <MemorySummary v-if="workflow?.memory_context" :memory="workflow.memory_context" />
          <el-tag :type="workflowStatus.type" size="small">{{ workflowStatus.label }}</el-tag>
          <p>{{ workflowStatusMessage }}</p>
          <DiagnosisCheckPanel :check="workflow?.check" />
          <div v-if="workflowExplanation?.summary">
            <strong>本工作流记录的判断</strong>
            <p>{{ readableText(workflowExplanation.summary) }}</p>
          </div>
          <p v-if="workflowBasis.length">本次参考：{{ workflowBasis.join('、') }}</p>
          <div v-if="workflowLimitations.length">
            <strong>本工作流的限制</strong>
            <ul>
              <li v-for="item in workflowLimitations" :key="item">{{ item }}</li>
            </ul>
          </div>
          <div v-if="workflow?.reviews?.length">
            <strong>教师审核历史</strong>
            <ol>
              <li v-for="review in workflow.reviews" :key="review.id">
                <b>{{ reviewActionLabel(review.action) }}</b>
                <time>{{ formatReviewTime(review.created_at) }}</time>
                <p>审核详情仅教师可见</p>
              </li>
            </ol>
          </div>
        </section>
      </details>
    </div>

    <section v-show="view === 'reference'" class="reference-work" aria-label="当前问题的教学参考">
      <div class="next-step-heading">
        <h2>教学参考</h2>
        <el-tag v-if="diagnosis?.is_test_data" type="warning">测试资料</el-tag>
      </div>
      <p>资料来自本次诊断锁定的实验包；预期观察不代表已经执行或实测成功。</p>
      <p v-if="issueSelectionRequired" class="empty-copy">
        请先选择一个问题，再查看它关联的教学资料。
      </p>
      <template v-else>
        <article
          v-for="(hint, index) in hints"
          :key="`${hint.cause_id}-${hint.level}-${index}`"
          class="reference-item"
        >
          <h3>对应排查提示 · 提示等级 {{ hint.level }}</h3>
          <p>{{ hint.text }}</p>
          <TeachingReferencePanel :material="hint.teaching" />
        </article>
        <p v-if="!hints.length" class="empty-copy">
          当前没有明确关联的教学资料。可先查看实验数据，或返回当前排查联系教师。
        </p>
      </template>
    </section>
  </div>
</template>

<style scoped>
.task-diagnosis {
  display: block;
  min-width: 0;
  grid-column: 1 / -1;
}
.task-diagnosis h2,
.task-diagnosis h3,
.task-diagnosis p {
  overflow-wrap: anywhere;
}
.task-diagnosis h2 {
  margin: 12px 0;
  font-size: clamp(20px, 2.5vw, 26px);
  line-height: 1.4;
}
.task-diagnosis h3 {
  margin: 0 0 12px;
  font-size: 17px;
  line-height: 1.5;
}
.task-diagnosis p,
.task-diagnosis li {
  font-size: 14px;
  line-height: 1.65;
}
.issue-picker {
  margin-bottom: 18px;
  max-width: 680px;
}
.issue-picker label {
  display: block;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 600;
}
.issue-picker .el-select {
  width: 100%;
}
.next-step-card,
.reference-work {
  padding: 22px;
  border: 1px solid var(--studio-line, #c7c6bc);
  background: #f3f4ee;
}
.next-step-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: #55604a;
  font-size: 13px;
}
.primary-summary {
  margin: 8px 0 12px;
}
.primary-limitation {
  margin: 12px 0;
}
.next-action {
  margin: 16px 0;
}
.required-limitations {
  padding-left: 20px;
  margin: 10px 0;
}
.required-notice {
  margin: 10px 0;
  padding-left: 12px;
  border-left: 3px solid #b07825;
}
.next-step-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.task-diagnosis :deep(.el-button) {
  margin-left: 0;
  white-space: normal;
  min-height: 42px;
  height: auto;
}
.next-step-note,
.focus-target,
.feedback-context,
.record-scope {
  color: #555b50;
  font-size: 13px !important;
}
.next-step-note {
  margin: 12px 0 0;
}
.check-context {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--studio-line, #c7c6bc);
}
.check-context p {
  margin: 5px 0;
  font-size: 13px;
}
.guidance-work {
  margin-top: 24px;
}
.task-diagnosis .hint-steps {
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
  list-style: none;
}
.task-diagnosis .guidance-hint {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 14px;
  padding: 14px;
  align-items: start;
  border: 1px solid var(--studio-line, #c7c6bc);
}
.task-diagnosis .hint-content {
  min-width: 0;
}
.task-diagnosis .hint-action {
  margin: 0;
}
.task-diagnosis .feedback-area {
  margin: 16px 0 0;
  padding: 0;
}
.task-diagnosis .feedback-context {
  margin: 12px 0;
}
.task-diagnosis .feedback-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  background: none;
}
.task-diagnosis .feedback-actions .el-button {
  width: auto;
  height: auto;
  min-height: 42px;
  padding: 10px 16px;
  border: 1px solid var(--studio-line, #c7c6bc);
}
.task-diagnosis .feedback-record {
  margin: 10px 0;
  padding: 10px;
  display: flex;
  gap: 6px;
}
.feedback-record svg {
  width: 18px;
}
.diagnosis-records {
  margin-top: 24px;
  border-top: 1px solid var(--studio-line, #c7c6bc);
  padding-top: 16px;
}
.diagnosis-records > summary {
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
  padding: 6px 0;
}
.task-diagnosis .record-section {
  margin: 20px 0 0;
  padding: 18px 0 0;
  border: 0;
  border-top: 1px solid var(--studio-line, #c7c6bc);
  display: block;
  background: none;
}
.task-diagnosis .technical-details {
  margin: 14px 0 0;
  padding: 14px;
}
.task-diagnosis .technical-facts {
  margin: 14px 0;
}
.task-diagnosis .technical-facts dd {
  overflow-wrap: anywhere;
}
.task-diagnosis .cause-copy {
  display: grid;
  gap: 4px;
}
.task-diagnosis .cause-ranking {
  margin: 12px 0;
}
.task-diagnosis .cause-ranking li {
  padding: 12px;
}
.task-diagnosis .cause-ranking b {
  font-size: 13px;
  white-space: nowrap;
}
.reference-item {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--studio-line, #c7c6bc);
}
@media (max-width: 680px) {
  .next-step-card,
  .reference-work {
    padding: 16px;
  }
  .task-diagnosis .feedback-actions {
    display: grid;
    grid-template-columns: 1fr;
  }
  .task-diagnosis .feedback-actions .el-button {
    width: 100%;
  }
  .task-diagnosis .guidance-hint {
    grid-template-columns: 1fr;
    gap: 8px;
  }
  .task-diagnosis .cause-ranking li {
    grid-template-columns: 28px minmax(0, 1fr);
    gap: 10px;
  }
  .task-diagnosis .cause-ranking b {
    grid-column: 2;
  }
}
</style>

<style scoped>
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-width: 100%;
  font-size: 0.85em;
}
</style>
