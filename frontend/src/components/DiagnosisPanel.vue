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
}>()

const emit = defineEmits<{
  feedback: [action: FeedbackAction]
  requestAi: []
}>()

const actionLabels: Record<FeedbackAction, string> = {
  resolved: '问题已解决',
  unresolved: '仍未解决',
  request_teacher_help: '请求教师协助',
}
const confidenceLabels = { low: '低', medium: '中', high: '高' }
const primaryMatch = computed(() => props.diagnosis?.matches[0] ?? null)
const evidenceItems = computed(
  () => props.diagnosis?.matches.flatMap((match) => match.evidence) ?? [],
)
const rankedCauses = computed(() => props.guidance.flatMap((item) => item.ranked_causes))
const hints = computed(() => props.guidance.flatMap((item) => item.hints))
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
</script>

<template>
  <div id="diagnosis" class="diagnosis-suite">
    <article class="panel-card diagnosis-summary" :class="{ 'is-abnormal': primaryMatch }">
      <div class="panel-heading compact-heading">
        <h2><Warning /> 异常诊断卡片</h2>
        <el-tag v-if="diagnosis?.is_test_data" type="warning" size="small" round>测试结果</el-tag>
      </div>

      <el-empty v-if="!diagnosis" description="尚无诊断记录" :image-size="66" />
      <div v-else-if="!primaryMatch" class="normal-result">
        <CircleCheck />
        <div>
          <strong>当前未匹配故障规则</strong>
          <p>这是确定性示例规则结果，不代表已完成真实硬件健康认证。</p>
        </div>
      </div>
      <div v-else class="alert-result">
        <p class="alert-code">{{ primaryMatch.error_type }}</p>
        <el-tag type="danger" effect="light" round>异常</el-tag>
        <h3>{{ primaryMatch.summary }}</h3>
        <p>检测到确定性示例规则匹配项，请结合下方证据与分层步骤继续排查。</p>
        <small>规则 {{ primaryMatch.rule_id }} · 优先级 {{ primaryMatch.priority }}</small>
      </div>
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
