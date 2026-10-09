<script setup lang="ts">
import axios from 'axios'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { newRequestId } from '@/api/feedbackRetry'
import {
  answerStudentQuery,
  findStudentQuery,
  readStudentQuery,
  startStudentQuery,
  type QueryAnswerPayload,
  type QueryAnswerValue,
  type QueryTask,
} from '@/api/student'
import { queryCodeLabel, queryOptionLabels, queryQuestionText } from '@/presentation/userLanguage'
import type { DeviceCredentials } from '@/types/student'

const props = defineProps<{
  diagnosisId: string
  credentials: DeviceCredentials | null
  readOnly?: boolean
  refreshKey?: string
}>()
const emit = defineEmits<{ login: [] }>()
const task = ref<QueryTask | null>(null)
const loading = ref(false)
const message = ref('')
const denied = ref(false)
const needsLogin = ref(false)
const loaded = ref(false)
const readFailed = ref(false)
const startPending = ref(false)
const pending = ref<QueryAnswerPayload | null>(null)
const selected = ref<QueryAnswerValue | null>(null)
let revision = 0
let sequence = 0
const storageKey = () =>
  `xinjian-query-answer:${JSON.stringify([props.credentials?.deviceId, props.credentials?.experimentSessionId, props.diagnosisId])}`
const questionText = computed(() =>
  task.value?.question ? queryQuestionText(task.value.question.question_id) : null,
)
const canAnswer = computed(
  () =>
    task.value?.status === 'waiting_answer' &&
    task.value.question?.synthetic &&
    questionText.value &&
    !readFailed.value,
)
const blocked = computed(() => loading.value || props.readOnly || denied.value || needsLogin.value)
function savePending(value: QueryAnswerPayload | null) {
  pending.value = value
  if (value) sessionStorage.setItem(storageKey(), JSON.stringify(value))
  else sessionStorage.removeItem(storageKey())
}
function restorePending() {
  try {
    const raw = sessionStorage.getItem(storageKey())
    if (!raw) return
    const value = JSON.parse(raw) as QueryAnswerPayload
    if (
      !/^[0-9a-f-]{36}$/i.test(value.request_id) ||
      typeof value.question_id !== 'string' ||
      typeof value.question_version !== 'string' ||
      !['matches_table', 'differs', 'unclear'].includes(value.value)
    )
      throw new Error('invalid')
    pending.value = value
    selected.value = value.value
  } catch {
    readFailed.value = true
    message.value = '原答复记录无法读取，请联系教师核对提交状态。'
  }
}
async function operate(kind: 'read' | 'start' | 'answer') {
  const credentials = props.credentials
  if (!credentials || loading.value || (kind !== 'read' && blocked.value)) return
  const currentRevision = revision
  const currentSequence = ++sequence
  const current = () =>
    currentRevision === revision &&
    currentSequence === sequence &&
    credentials === props.credentials
  loading.value = true
  message.value = ''
  try {
    if (kind === 'answer') {
      if (!task.value || !pending.value) return
      await answerStudentQuery(credentials, task.value.id, { ...pending.value })
      if (!current()) return
      savePending(null)
      // A successful receipt and a failed follow-up GET are separate outcomes.
      message.value = '答复已保存。'
      readFailed.value = true
      const result = await readStudentQuery(credentials, task.value.id)
      if (!current()) return
      task.value = result
    } else {
      const result =
        kind === 'start'
          ? await startStudentQuery(credentials, props.diagnosisId)
          : await findStudentQuery(credentials, props.diagnosisId)
      if (!current()) return
      task.value = result
    }
    if (!current()) return
    loaded.value = true
    readFailed.value = false
    startPending.value = false
    denied.value = false
    if (pending.value) message.value = '上次答复结果尚未确认；重试将沿用原答复。'
  } catch (error) {
    if (!current()) return
    const status = axios.isAxiosError(error) ? error.response?.status : undefined
    if (status === 401 || status === 403) {
      task.value = null
      savePending(null)
      selected.value = null
      startPending.value = false
      denied.value = status === 403
      needsLogin.value = status === 401
      message.value = status === 403 ? '当前无权查看本次资料核对。' : '登录已失效，请重新登录。'
      if (status === 401) emit('login')
    } else if (status === 409) {
      savePending(null)
      startPending.value = false
      readFailed.value = true
      message.value = '请求发生冲突，已重新读取状态；请核对后再决定。'
      try {
        const result = task.value
          ? await readStudentQuery(credentials, task.value.id)
          : await findStudentQuery(credentials, props.diagnosisId)
        if (!current()) return
        task.value = result
        loaded.value = true
        readFailed.value = false
      } catch (readError) {
        if (!current()) return
        const readStatus = axios.isAxiosError(readError) ? readError.response?.status : undefined
        if (readStatus === 401 || readStatus === 403) {
          task.value = null
          denied.value = readStatus === 403
          needsLogin.value = readStatus === 401
          message.value =
            readStatus === 403 ? '当前无权查看本次资料核对。' : '登录已失效，请重新登录。'
          if (readStatus === 401) emit('login')
        } else message.value = '请求发生冲突，状态读取失败；请重新读取状态。'
      }
    } else if (status === 422) {
      savePending(null)
      startPending.value = false
      message.value = '本次请求不受支持，请核对当前诊断或联系教师。'
      readFailed.value = true
    } else {
      if (kind === 'start') startPending.value = true
      if (kind === 'read' || !pending.value) readFailed.value = true
      message.value = pending.value
        ? '答复结果尚未确认，请点击重试原答复。'
        : kind === 'start'
          ? '核对暂时不可用，请点击重试核对。'
          : '资料核对读取失败，请重新读取状态。'
    }
  } finally {
    if (current()) loading.value = false
  }
}
function submit() {
  if (
    blocked.value ||
    !canAnswer.value ||
    !selected.value ||
    pending.value ||
    !task.value?.question
  )
    return
  savePending({
    request_id: newRequestId(),
    question_id: task.value.question.question_id,
    question_version: task.value.question.version,
    value: selected.value,
  })
  void operate('answer')
}
watch(
  () => [props.credentials, props.diagnosisId] as const,
  (_, previous) => {
    if (previous?.[0] && previous[0] !== props.credentials) {
      sessionStorage.removeItem(
        `xinjian-query-answer:${JSON.stringify([previous[0].deviceId, previous[0].experimentSessionId, previous[1]])}`,
      )
    }
    revision++
    task.value = null
    pending.value = null
    selected.value = null
    loading.value = false
    message.value = ''
    denied.value = needsLogin.value = readFailed.value = loaded.value = startPending.value = false
    restorePending()
    void operate('read')
  },
  { immediate: true, flush: 'sync' },
)
watch(
  () => props.refreshKey,
  () => {
    if (!loading.value && !denied.value && !needsLogin.value) void operate('read')
  },
)
onBeforeUnmount(() => {
  revision++
})
</script>

<template>
  <section class="query-check-panel" aria-label="资料核对" :aria-busy="loading">
    <h2>资料核对</h2>
    <p>核对本次诊断的程序设置、实验要求与接线观察。</p>
    <p v-if="message" role="alert">{{ message }}</p>
    <p v-if="loading" role="status">正在读取或提交，请稍候。</p>
    <template v-if="!denied && !needsLogin">
      <p v-if="readFailed" role="alert">当前核对状态暂未更新；之前的内容仅供查看，不能继续作答。</p>
      <el-button v-if="readFailed || task || pending" :disabled="loading" @click="operate('read')"
        >重新读取状态</el-button
      >
      <p v-if="loaded && !task && !readFailed && !startPending && !pending">尚未发起资料核对。</p>
      <el-button
        v-if="loaded && !task && !readFailed && !startPending && !pending"
        :disabled="blocked"
        @click="operate('start')"
        >核对资料</el-button
      >
      <el-button v-if="startPending" :disabled="blocked" @click="operate('start')"
        >重试核对</el-button
      >
      <template v-if="task">
        <el-alert
          v-if="task.is_test_data"
          title="测试数据：本次核对不代表真实设备验证结果。"
          type="warning"
          :closable="false"
        />
        <el-alert
          v-if="task.status === 'stale'"
          :title="queryCodeLabel('stale')"
          type="error"
          :closable="false"
        />
        <p>
          <strong>{{ queryCodeLabel(task.status) }}</strong>
        </p>
        <p>这是程序里设置的引脚，不代表实际接线已核对</p>
        <p>
          {{ queryCodeLabel(task.root_cause_status) }}；{{
            queryCodeLabel(task.physical_verification)
          }}。
        </p>
        <dl>
          <template v-for="(item, code) in task.requirements" :key="code">
            <dt>{{ queryCodeLabel(code) }}</dt>
            <dd>
              {{ queryCodeLabel(item.status) }}；{{ queryCodeLabel(item.judgement)
              }}<span v-if="item.gap">；{{ queryCodeLabel(item.gap) }}</span>
            </dd>
          </template>
        </dl>
        <p v-if="task.terminal_reason">结束说明：{{ queryCodeLabel(task.terminal_reason) }}</p>
        <template v-if="task.question">
          <el-alert
            v-if="task.question.synthetic"
            title="测试用题目，正式题目待教师确认"
            type="warning"
            :closable="false"
          />
          <p v-if="!questionText">题目暂缺解释，暂不提供作答；可展开查看原文。</p>
          <p v-else>{{ questionText }}</p>
          <fieldset v-if="canAnswer" :disabled="blocked || Boolean(pending)">
            <legend>选择你的观察结果</legend>
            <label v-for="option in task.question.options" :key="option">
              <input
                v-model="selected"
                type="radio"
                :value="option"
                :name="`query-answer-${diagnosisId}`"
              />{{ queryOptionLabels[option] || '暂缺解释' }}
            </label>
            <el-button :disabled="blocked || !selected || Boolean(pending)" @click="submit"
              >提交答复</el-button
            >
          </fieldset>
        </template>
      </template>
      <div v-if="pending" role="status" class="pending-answer">
        <p>待确认的原答复：{{ queryOptionLabels[pending.value] }}。请先确认原答复再继续。</p>
        <el-button :disabled="blocked || !task || readFailed" @click="operate('answer')"
          >重试原答复</el-button
        >
      </div>
      <details v-if="task">
        <summary>核对原始代码与题目编号</summary>
        <pre>{{ JSON.stringify(task, null, 2) }}</pre>
      </details>
    </template>
    <el-button v-if="needsLogin" @click="emit('login')">重新登录</el-button>
  </section>
</template>

<style scoped>
.query-check-panel {
  margin: 24px 0;
  padding: 24px;
  border: 1px solid var(--studio-line);
  background: var(--studio-paper, #fff);
  overflow-wrap: anywhere;
}
.query-check-panel h2 {
  margin: 0 0 16px;
  font-size: 22px;
}
.query-check-panel p {
  line-height: 1.7;
  margin: 12px 0;
}
.query-check-panel :deep(.el-alert) {
  margin: 16px 0;
}
.query-check-panel dt {
  margin-top: 16px;
  font-weight: 600;
}
.query-check-panel dd {
  margin: 8px 0 0;
  line-height: 1.7;
}
.query-check-panel fieldset {
  padding: 16px;
  margin: 16px 0;
  border: 1px solid var(--studio-line);
  min-width: 0;
}
.query-check-panel label {
  display: flex;
  gap: 8px;
  align-items: baseline;
  margin-bottom: 16px;
}
.query-check-panel pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
}
.query-check-panel summary {
  cursor: pointer;
  margin-top: 16px;
}
.query-check-panel :deep(.el-button) {
  margin: 8px 8px 8px 0;
}
@media (max-width: 680px) {
  .query-check-panel {
    padding: 16px;
  }
}
</style>
