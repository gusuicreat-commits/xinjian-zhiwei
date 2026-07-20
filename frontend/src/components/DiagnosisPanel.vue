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
  StudentDiagnosis,
  StudentFeedback,
  StudentGuidance,
} from '@/types/student'

const props = defineProps<{
  diagnosis: StudentDiagnosis | null
  guidance: StudentGuidance[]
  feedback: StudentFeedback | null
  feedbackLoading: boolean
}>()

const emit = defineEmits<{ feedback: [action: FeedbackAction] }>()

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
