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
const unverifiedWorkflowKnowledge = computed(() =>
  workflowKnowledge.value.filter((item) => item.metadata?.review_status !== 'approved'),
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

function formatRrfScore(score: number): string {
  return Number.isFinite(score) ? score.toFixed(4) : '—'
}

function reviewActionLabel(action: 'approve' | 'edit' | 'reject'): string {
  return { approve: '批准', edit: '修订并批准', reject: '驳回' }[action]
}

function formatReviewTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function evidenceDetailRefs(evidence: {
  evidence_refs?: string[]
  details?: Record<string, unknown>[]
}): string[] {
  const detailRefs = (evidence.details ?? []).flatMap((detail) =>
    ['log_id', 'reading_id']
      .filter((key) => typeof detail[key] === 'string')
      .map((key) => `${key === 'log_id' ? 'log' : 'reading'}:${String(detail[key])}`),
  )
  return [...new Set([...(evidence.evidence_refs ?? []), ...detailRefs])]
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
          Provider {{ aiStatus.provider_configured ? '已配置' : '待配置' }} · Embedding
          {{ aiStatus.embedding_client_configured ? '已配置' : '待配置' }} · Prompt
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
        <h2><List /> LangGraph 辅助诊断</h2>
        <el-tag :type="workflowStatus.type" size="small" round>
          {{ workflowStatus.label }}
        </el-tag>
      </div>
      <p v-if="workflow">
        证据分 {{ workflow.evidence_score ?? '—' }} · Level {{ workflow.guidance_level ?? '—' }} ·
        规则 {{ workflow.rule_engine_version || '—' }} · 故障树
        {{ workflow.fault_tree_version || '—' }}
      </p>
      <p v-if="workflowExplanation?.summary" class="workflow-explanation-summary">
        <strong>辅助解释：</strong>{{ workflowExplanation.summary }}
      </p>
      <div v-if="workflow?.node_trace.length" class="workflow-trace" aria-label="工作流节点轨迹">
        <span v-for="(node, index) in workflow.node_trace" :key="`${node}-${index}`">
          {{ node }}
        </span>
      </div>
      <p v-else>规则、故障树、知识检索与 AI 解释由可恢复状态图统一编排。</p>
      <div
        v-if="workflow && (workflowRuleHits.length || workflowCandidates.length)"
        class="workflow-evidence-grid"
      >
        <section>
          <strong>确定性规则引用</strong>
          <ul v-if="workflowRuleHits.length">
            <li v-for="hit in workflowRuleHits" :key="hit.rule_id">
              <code>{{ hit.rule_id }}</code>
              <span>{{ hit.summary }}</span>
              <small v-if="hit.evidence.length">
                {{
                  hit.evidence
                    .map((item) => {
                      const refs = evidenceDetailRefs(item)
                      return `${item.fact}=${item.observed_value ?? '已命中'}${refs.length ? ` [${refs.join('、')}]` : ''}`
                    })
                    .join('；')
                }}
              </small>
            </li>
          </ul>
          <p v-else class="empty-inline">未记录规则命中。</p>
        </section>
        <section>
          <strong>故障树候选与证据引用</strong>
          <ul v-if="workflowCandidates.length">
            <li v-for="candidate in workflowCandidates" :key="candidate.cause_id">
              <span>{{ candidate.name }}</span>
              <b>{{ scorePercent(candidate.score) }}%</b>
              <small>{{ candidate.evidence_refs.join('、') || '无稳定证据引用' }}</small>
            </li>
          </ul>
          <p v-else class="empty-inline">未记录故障树候选。</p>
        </section>
      </div>
      <section v-if="workflow?.needs_rag || workflowKnowledge.length" class="workflow-knowledge">
        <strong>已审核知识来源</strong>
        <ul v-if="approvedWorkflowKnowledge.length">
          <li v-for="reference in approvedWorkflowKnowledge" :key="reference.chunk_id">
            <div>
              <b>{{ reference.title }}</b>
              <code>{{ reference.source_id }} / {{ reference.chunk_id }}</code>
            </div>
            <span>RRF {{ formatRrfScore(reference.score) }}</span>
            <small> 版本 {{ reference.metadata?.source_version || '—' }} · 已审核 </small>
          </li>
        </ul>
        <p v-else-if="workflow?.needs_rag" class="workflow-warning">
          本次需要知识检索，但没有可采用的已审核来源。
        </p>
        <p v-else class="empty-inline">本次证据分支未采用知识检索。</p>
      </section>
      <section v-if="unverifiedWorkflowKnowledge.length" class="workflow-unverified-knowledge">
        <strong>未验证来源（不可作为诊断依据）</strong>
        <ul>
          <li v-for="reference in unverifiedWorkflowKnowledge" :key="reference.chunk_id">
            <div>
              <b>{{ reference.title }}</b>
              <code>{{ reference.source_id }} / {{ reference.chunk_id }}</code>
            </div>
            <span>RRF {{ formatRrfScore(reference.score) }}</span>
            <small>审核状态未批准，已与诊断证据隔离。</small>
          </li>
        </ul>
      </section>
      <section v-if="workflowLimitations.length" class="workflow-limitations">
        <strong>当前限制 / 缺失证据</strong>
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
        {{ workflow?.status === 'waiting_teacher' ? '等待教师审核' : '启动辅助诊断工作流' }}
      </el-button>
      <p class="ai-safety-note">工作流不会让模型修改规则证据、证据分值或提示等级。</p>
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
