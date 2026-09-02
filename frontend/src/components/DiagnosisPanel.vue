<script setup lang="ts">
import {
  CircleCheck,
  DocumentChecked,
  Histogram,
  List,
  Promotion,
  QuestionFilled,
  Warning,
} from '@element-plus/icons-vue'
import { computed } from 'vue'

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
} from '@/types/student'

const props = defineProps<{
  diagnosis: StudentDiagnosis | null
  guidance: StudentGuidance[]
  feedback: StudentFeedback | null
  intervention: StudentIntervention | null
  feedbackLoading: boolean
  aiStatus: AIStatus
  aiExplanation: AIExplanationResponse | null
  aiLoading: boolean
  workflow: DiagnosisWorkflow | null
  workflowLoading: boolean
  deviceStateExplanation: DeviceStateExplanation
}>()

const emit = defineEmits<{
  feedback: [action: FeedbackAction]
  requestAi: []
  requestWorkflow: []
}>()

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
const rankedCauses = computed(() => props.guidance.flatMap((item) => item.ranked_causes))
const hints = computed(() => props.guidance.flatMap((item) => item.hints))
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
    waiting_feedback: '请按建议完成一次检查，然后反馈是否解决；你的反馈会作为下一轮证据。',
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
const workflowActionLabel = computed(() => {
  if (props.workflow?.status === 'waiting_teacher') return '等待教师确认'
  if (props.workflow?.status === 'waiting_feedback') return '等待排查反馈'
  if (props.workflow?.status === 'completed') return '更新辅助诊断'
  if (props.workflow?.status === 'rejected' || props.workflow?.status === 'failed') {
    return '重新进行辅助诊断'
  }
  return props.workflow ? '继续辅助诊断' : '启动辅助诊断'
})
const interventionStatus = computed(() => {
  if (!props.intervention) return null
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
      title: '教师已标记为解决',
      detail: props.intervention.resolution_summary || '教师已完成本次协助处理。',
      type: 'success',
    },
    unconfirmed: {
      title: '教师暂时无法确认',
      detail: '当前证据不足，教师可能需要更多日志或现场信息。',
      type: 'warning',
    },
    closed: {
      title: '教师协助已关闭',
      detail: props.intervention.resolution_summary || '本次教师协助流程已经结束。',
      type: 'info',
    },
  } as const
  return statusCopy[props.intervention.status]
})

function scorePercent(score: number): number {
  return Math.min(100, Math.round(score <= 1 ? score * 100 : score))
}

function reviewActionLabel(action: 'approve' | 'edit' | 'reject'): string {
  return { approve: '批准', edit: '修订并批准', reject: '驳回' }[action]
}

function formatReviewTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div id="diagnosis" class="diagnosis-suite">
    <article class="panel-card diagnosis-summary" :class="{ 'is-abnormal': primaryMatch }">
      <div class="panel-heading compact-heading">
        <h2><Warning /> 设备状态解释</h2>
        <div class="state-explanation-tags">
          <el-tag
            :type="deviceStateExplanation.source === 'ai' ? 'success' : 'info'"
            size="small"
            round
          >
            {{ deviceStateExplanation.source === 'ai' ? 'AI 综合解释' : '规则解释' }}
          </el-tag>
          <el-tag v-if="diagnosis?.is_test_data" type="warning" size="small" round>测试结果</el-tag>
        </div>
      </div>

      <div v-if="!primaryMatch" class="normal-result">
        <CircleCheck />
        <div>
          <strong>{{ deviceStateExplanation.status_title }}</strong>
          <p>{{ deviceStateExplanation.status_summary }}</p>
        </div>
      </div>
      <div v-else class="alert-result">
        <el-tag type="danger" effect="light" round>异常</el-tag>
        <h3>{{ deviceStateExplanation.status_title }}</h3>
        <p class="student-state-summary">{{ deviceStateExplanation.status_summary }}</p>
        <dl class="student-explanation-grid">
          <div>
            <dt>这意味着什么</dt>
            <dd>{{ deviceStateExplanation.meaning }}</dd>
          </div>
          <div>
            <dt>建议先做什么</dt>
            <dd>{{ deviceStateExplanation.next_step }}</dd>
          </div>
        </dl>
      </div>

      <details class="technical-details">
        <summary>查看技术详情</summary>
        <dl class="technical-facts">
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
              <code>{{ reading.sensor_type }} / {{ reading.metric_key }}</code>
              <span>{{ reading.value }} {{ reading.unit || '' }}</span>
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
              <code>{{ tree.tree_id }}</code>
              <span>{{ tree.tree_title }} · Level {{ tree.hint_level }}</span>
            </li>
          </ul>
        </section>
      </details>
    </article>

    <article v-if="diagnosis" class="panel-card ai-explanation-panel">
      <div class="panel-heading compact-heading">
        <h2><DocumentChecked /> 诊断解释</h2>
        <el-tag
          :type="aiExplanation?.status === 'succeeded' ? 'success' : 'info'"
          size="small"
          round
        >
          {{ aiExplanation?.status === 'succeeded' ? 'AI 已增强' : '确定性结果' }}
        </el-tag>
      </div>
      <div v-if="aiExplanation?.explanation" class="ai-explanation-content">
        <strong>{{ aiExplanation.explanation.summary }}</strong>
        <p>{{ aiExplanation.notice }}</p>
        <ul>
          <li v-for="step in aiExplanation.explanation.steps" :key="step">{{ step }}</li>
        </ul>
        <small v-if="aiExplanation.explanation.limitations.length">
          限制：{{ aiExplanation.explanation.limitations.join('；') }}
        </small>
      </div>
      <div v-else class="ai-disabled-state">
        <strong>{{ diagnosis.explanation?.summary || primaryMatch?.summary }}</strong>
        <p>当前建议由确定性规则、故障树和已审核知识生成；AI 不是诊断前置条件。</p>
        <p>{{ aiExplanation?.notice || aiStatus.notice }}</p>
        <ul v-if="diagnosis.explanation?.steps.length">
          <li v-for="step in diagnosis.explanation.steps" :key="step">{{ step }}</li>
        </ul>
        <small v-if="diagnosis.explanation?.limitations.length">
          当前限制：{{ diagnosis.explanation.limitations.join('；') }}
        </small>
        <small>
          Provider {{ aiStatus.provider_configured ? '已配置' : '待配置' }} · 知识匹配
          结构化案例 · Prompt
          {{ aiStatus.prompt_version }}
        </small>
      </div>
      <el-button
        type="primary"
        plain
        :loading="aiLoading"
        :disabled="!aiStatus.provider_configured"
        @click="emit('requestAi')"
      >
        {{ aiStatus.provider_configured ? '按需增强解释' : 'AI 增强未启用' }}
      </el-button>
      <p class="ai-safety-note">AI 只补充解释，不覆盖确定性规则、证据和故障树结论。</p>
    </article>

    <article v-if="diagnosis" class="panel-card ai-explanation-panel">
      <div class="panel-heading compact-heading">
        <h2><List /> 辅助诊断进度</h2>
        <el-tag :type="workflowStatus.type" size="small" round>
          {{ workflowStatus.label }}
        </el-tag>
      </div>
      <p class="workflow-user-status">{{ workflowStatusMessage }}</p>
      <section v-if="workflowExplanation?.summary" class="workflow-user-summary">
        <strong>当前判断</strong>
        <p>{{ workflowExplanation.summary }}</p>
      </section>
      <section v-if="workflowBasis.length" class="workflow-user-basis">
        <strong>本次参考</strong>
        <p>{{ workflowBasis.join('、') }}</p>
      </section>
      <section v-if="workflowLimitations.length" class="workflow-limitations">
        <strong>还需要确认</strong>
        <ul>
          <li v-for="item in workflowLimitations" :key="item">{{ item }}</li>
        </ul>
      </section>
      <section v-if="workflow?.reviews?.length" class="workflow-reviews">
        <strong>教师审核历史</strong>
        <ol>
          <li v-for="review in workflow.reviews ?? []" :key="review.id">
            <b>{{ reviewActionLabel(review.action) }}</b>
            <time>{{ formatReviewTime(review.created_at) }}</time>
            <p>审核详情仅教师可见</p>
          </li>
        </ol>
      </section>
      <el-button
        type="primary"
        :loading="workflowLoading"
        :disabled="workflow?.status === 'waiting_teacher'"
        @click="emit('requestWorkflow')"
      >
        {{ workflowActionLabel }}
      </el-button>
      <p class="ai-safety-note">诊断以设备记录和规则结果为准，AI 只负责整理说明。</p>
    </article>

    <article v-if="primaryMatch" class="panel-card evidence-panel">
      <div class="panel-heading compact-heading">
        <h2><DocumentChecked /> 证据展示</h2>
      </div>
      <ul class="evidence-list">
        <li v-for="item in evidenceItems" :key="item.fact">
          <span class="evidence-bullet" />
          <span>{{ item.fact }}</span>
          <strong>{{ item.observed_value }}</strong>
        </li>
      </ul>
      <p v-if="evidenceItems.length === 0" class="empty-copy">当前规则未返回可展示证据。</p>
    </article>

    <article v-if="primaryMatch" class="panel-card causes-panel">
      <div class="panel-heading compact-heading">
        <h2><Histogram /> 可能原因排序</h2>
      </div>
      <ol class="cause-ranking">
        <li v-for="(cause, index) in rankedCauses" :key="cause.cause_id">
          <span class="rank-index">{{ index + 1 }}</span>
          <div class="cause-copy">
            <div>
              <strong>{{ cause.title }}</strong>
              <small>置信度 {{ confidenceLabels[cause.confidence] }}</small>
            </div>
            <div class="score-track">
              <span :style="{ width: `${scorePercent(cause.score)}%` }" />
            </div>
          </div>
          <b>{{ scorePercent(cause.score) }}%</b>
        </li>
      </ol>
      <p v-if="rankedCauses.length === 0" class="empty-copy">尚无有证据支持的候选原因。</p>
    </article>

    <article v-if="primaryMatch" class="panel-card hints-panel">
      <div class="panel-heading compact-heading">
        <h2><List /> 分层排查步骤</h2>
      </div>
      <ol class="hint-steps">
        <li v-for="hint in hints" :key="`${hint.cause_id}-${hint.level}`">
          <span :class="`level-${hint.level}`">Level {{ hint.level }}</span>
          <p>{{ hint.text }}</p>
        </li>
      </ol>
      <p v-if="hints.length === 0" class="empty-copy">尚无可用排查提示。</p>
    </article>

    <div v-if="primaryMatch" class="feedback-area">
      <el-alert
        v-if="interventionStatus"
        class="intervention-status-alert"
        :title="interventionStatus.title"
        :description="interventionStatus.detail"
        :type="interventionStatus.type"
        :closable="false"
        show-icon
      />
      <div v-if="feedback" class="feedback-record">
        <CircleCheck /> 已记录：{{ actionLabels[feedback.action] }}
      </div>
      <div class="feedback-actions">
        <el-button type="success" :loading="feedbackLoading" @click="emit('feedback', 'resolved')">
          <CircleCheck /> 问题已解决
        </el-button>
        <el-button
          type="warning"
          :loading="feedbackLoading"
          @click="emit('feedback', 'unresolved')"
        >
          <QuestionFilled /> 仍未解决
        </el-button>
        <el-button
          type="primary"
          :loading="feedbackLoading"
          @click="emit('feedback', 'request_teacher_help')"
        >
          <Promotion /> 请求教师协助
        </el-button>
      </div>
    </div>
  </div>
</template>
