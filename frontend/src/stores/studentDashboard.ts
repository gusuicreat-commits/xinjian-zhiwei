import axios from 'axios'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  completeFeedbackRequest,
  FeedbackRequestError,
  feedbackSessionScope,
  getOrCreateFeedbackRequest,
  listLocalFeedbackRequests,
  sameFeedbackPayload,
} from '@/api/feedbackRetry'
import {
  createDiagnosisFeedback,
  getFeedbackRecovery,
  getLatestDiagnosisWorkflow,
  getStudentDashboard,
  requestAIExplanation,
  startDiagnosisWorkflow,
} from '@/api/student'
import {
  classifyRequestFailure,
  failureMessage,
  withCappedRetry,
  type RequestFailureKind,
} from '@/api/resilience'
import {
  REVIEW_MODE,
  reviewAIExplanation,
  reviewStudentDashboard,
  reviewStudentWorkflow,
} from '@/review/fixtures'
import type {
  DeviceCredentials,
  DiagnosisWorkflow,
  FeedbackAction,
  FeedbackRecovery,
  FeedbackRecoveryTarget,
  StudentFeedbackCreate,
  StudentDashboard,
} from '@/types/student'

export type DashboardState = 'idle' | 'loading' | 'ready' | 'error'

export const useStudentDashboardStore = defineStore('student-dashboard', () => {
  const state = ref<DashboardState>('idle')
  const dashboard = ref<StudentDashboard | null>(null)
  const errorMessage = ref('')
  const failureKind = ref<RequestFailureKind | null>(null)
  const feedbackLoading = ref(false)
  const aiLoading = ref(false)
  const workflowLoading = ref(false)
  const workflow = ref<DiagnosisWorkflow | null>(null)
  let activeSessionScope: string | null = null
  let loadSequence = 0
  let recoverySequence = 0
  let aiSequence = 0
  let workflowSequence = 0
  const feedbackRecoveryState = ref<DashboardState>('idle')
  const feedbackRecovery = ref<FeedbackRecovery | null>(null)
  const feedbackRecoveryError = ref('')
  const localFeedbackError = ref('')
  const localFeedback = ref<FeedbackRecoveryTarget[]>([])
  const pendingFeedback = computed<FeedbackRecoveryTarget[]>(() => {
    const server: FeedbackRecoveryTarget[] = (feedbackRecovery.value?.pending ?? []).map(
      (item) => ({
        diagnosis_result_id: item.diagnosis_result_id,
        payload: { request_id: item.request_id, action: item.action, note: item.note },
        source: 'server',
        created_at: item.created_at,
      }),
    )
    return [
      ...server,
      ...localFeedback.value.filter(
        (local) =>
          !server.some(
            (item) =>
              item.diagnosis_result_id === local.diagnosis_result_id &&
              sameFeedbackPayload(item.payload, local.payload),
          ),
      ),
    ]
  })
  const feedbackBlocked = computed(
    () =>
      feedbackRecoveryState.value !== 'ready' ||
      pendingFeedback.value.length > 0 ||
      Boolean(localFeedbackError.value) ||
      Boolean(feedbackRecovery.value?.has_more_pending),
  )

  function readLocalFeedback(credentials: DeviceCredentials): void {
    try {
      localFeedback.value = listLocalFeedbackRequests(credentials)
      localFeedbackError.value = ''
    } catch (error) {
      localFeedbackError.value = error instanceof Error ? error.message : '本页反馈记录无法读取。'
    }
  }

  function clearMatchingLocal(
    credentials: DeviceCredentials,
    diagnosisId: string,
    payload: StudentFeedbackCreate,
  ): void {
    try {
      completeFeedbackRequest(credentials, diagnosisId, payload)
    } catch {
      // A server-confirmed result stays confirmed even when browser storage is unavailable.
      if (activeSessionScope === feedbackSessionScope(credentials)) {
        localFeedbackError.value =
          '服务器已确认反馈，但本页记录暂时无法清理；请恢复浏览器存储后刷新。'
      }
    }
  }

  async function refreshFeedbackRecovery(credentials: DeviceCredentials): Promise<boolean> {
    const scope = feedbackSessionScope(credentials)
    if (activeSessionScope !== scope) return false
    const sequence = ++recoverySequence
    feedbackRecoveryState.value = 'loading'
    feedbackRecoveryError.value = ''
    readLocalFeedback(credentials)
    try {
      if (!credentials.experimentSessionId)
        throw new FeedbackRequestError('反馈需要实验会话，请重新登录。')
      const recovery = REVIEW_MODE
        ? { pending: [], latest_applied: null, has_more_pending: false }
        : await withCappedRetry(() => getFeedbackRecovery({ ...credentials }))
      if (activeSessionScope !== scope || sequence !== recoverySequence) return false
      feedbackRecovery.value = recovery
      if (recovery.latest_applied) {
        const applied = recovery.latest_applied
        clearMatchingLocal(credentials, applied.diagnosis_result_id, applied)
      }
      readLocalFeedback(credentials)
      feedbackRecoveryState.value = 'ready'
      return true
    } catch (error) {
      if (activeSessionScope !== scope || sequence !== recoverySequence) return false
      feedbackRecoveryState.value = 'error'
      feedbackRecoveryError.value =
        error instanceof FeedbackRequestError
          ? error.message
          : '暂时无法查询上一条反馈的状态，请重新查询后再提交，避免重复操作。'
      return false
    }
  }

  async function load(credentials: DeviceCredentials): Promise<void> {
    const scope = feedbackSessionScope(credentials)
    if (activeSessionScope !== scope) {
      dashboard.value = null
      workflow.value = null
      activeSessionScope = scope
      recoverySequence += 1
      aiSequence += 1
      workflowSequence += 1
      aiLoading.value = false
      workflowLoading.value = false
      feedbackRecovery.value = null
      feedbackRecoveryState.value = 'idle'
      feedbackRecoveryError.value = ''
      localFeedback.value = []
      localFeedbackError.value = ''
    }
    const sequence = ++loadSequence
    state.value = dashboard.value ? 'ready' : 'loading'
    errorMessage.value = ''
    const recoveryLoaded = refreshFeedbackRecovery(credentials)
    if (REVIEW_MODE) {
      dashboard.value = structuredClone(reviewStudentDashboard)
      workflow.value = structuredClone(reviewStudentWorkflow)
      state.value = 'ready'
      failureKind.value = null
      await recoveryLoaded
      return
    }
    try {
      const loadedDashboard = await withCappedRetry(() => getStudentDashboard(credentials))
      if (sequence !== loadSequence) return
      dashboard.value = loadedDashboard
      try {
        const loadedWorkflow = await getLatestDiagnosisWorkflow(credentials)
        if (sequence !== loadSequence) return
        workflow.value = loadedWorkflow
      } catch {
        if (sequence !== loadSequence) return
        // The additive graph surface must not take down the legacy student dashboard.
        workflow.value = null
      }
      state.value = 'ready'
      failureKind.value = null
    } catch (error) {
      if (sequence !== loadSequence) return
      state.value = 'error'
      failureKind.value = classifyRequestFailure(error)
      errorMessage.value = failureMessage(failureKind.value)
    } finally {
      await recoveryLoaded
    }
  }

  async function sendFeedback(
    credentials: DeviceCredentials,
    diagnosisId: string,
    payload: StudentFeedbackCreate,
  ): Promise<boolean> {
    const scope = feedbackSessionScope(credentials)
    try {
      const feedback = await withCappedRetry(() =>
        createDiagnosisFeedback(credentials, diagnosisId, payload),
      )
      clearMatchingLocal(credentials, diagnosisId, payload)
      if (activeSessionScope === scope) {
        if (dashboard.value?.diagnosis?.id === diagnosisId) dashboard.value.feedback = feedback
        await load(credentials)
      }
      return true
    } catch (error) {
      if (error instanceof FeedbackRequestError) throw error
      if (
        axios.isAxiosError(error) &&
        error.response &&
        [400, 401, 403, 404, 422].includes(error.response.status)
      ) {
        clearMatchingLocal(credentials, diagnosisId, payload)
        if (activeSessionScope === scope) await refreshFeedbackRecovery(credentials)
        throw new FeedbackRequestError('反馈已被拒绝，未被接受；请检查实验会话并刷新诊断后再提交。')
      }
      if (activeSessionScope === scope) await refreshFeedbackRecovery(credentials)
      throw new FeedbackRequestError(
        '反馈结果尚未确认，请在“上一条反馈待确认”中继续确认原反馈；系统会沿用原提交记录。',
      )
    }
  }

  async function submitFeedback(
    credentials: DeviceCredentials,
    action: FeedbackAction,
  ): Promise<boolean> {
    if (feedbackLoading.value) return false
    if (!dashboard.value?.diagnosis || activeSessionScope !== feedbackSessionScope(credentials)) {
      throw new FeedbackRequestError('当前诊断已变化，请刷新后再提交反馈。')
    }
    if (REVIEW_MODE) {
      dashboard.value.feedback = {
        id: 'review-feedback-interactive',
        action,
        note: null,
        is_test_data: true,
        created_at: new Date().toISOString(),
      }
      return true
    }
    const scopedCredentials = { ...credentials }
    const scope = feedbackSessionScope(scopedCredentials)
    const diagnosisId = dashboard.value.diagnosis.id
    feedbackLoading.value = true
    try {
      if (!(await refreshFeedbackRecovery(scopedCredentials))) {
        throw new FeedbackRequestError(
          feedbackRecoveryError.value || '反馈状态尚未确认，请重新查询。',
        )
      }
      if (activeSessionScope !== scope || dashboard.value?.diagnosis?.id !== diagnosisId) {
        throw new FeedbackRequestError('当前诊断已变化，请刷新后再提交反馈。')
      }
      if (feedbackBlocked.value)
        throw new FeedbackRequestError(
          localFeedbackError.value || '请先在“上一条反馈待确认”中继续确认原反馈，再提交新的反馈。',
        )
      const payload = getOrCreateFeedbackRequest(scopedCredentials, diagnosisId, action)
      readLocalFeedback(scopedCredentials)
      return await sendFeedback(scopedCredentials, diagnosisId, payload)
    } finally {
      feedbackLoading.value = false
    }
  }

  async function recoverFeedback(
    credentials: DeviceCredentials,
    target: FeedbackRecoveryTarget,
  ): Promise<boolean> {
    if (feedbackLoading.value) return false
    const scopedCredentials = { ...credentials }
    const scope = feedbackSessionScope(scopedCredentials)
    if (activeSessionScope !== scope)
      throw new FeedbackRequestError('实验会话已变化，请刷新后再确认。')
    // Snapshot all original fields; recovery never generates a new request ID or rewrites a note.
    const diagnosisId = target.diagnosis_result_id
    const payload = { ...target.payload }
    feedbackLoading.value = true
    try {
      if (!(await refreshFeedbackRecovery(scopedCredentials)) || activeSessionScope !== scope) {
        throw new FeedbackRequestError('反馈状态尚未确认，请重新查询后继续。')
      }
      const applied = feedbackRecovery.value?.latest_applied
      if (applied?.diagnosis_result_id === diagnosisId && sameFeedbackPayload(applied, payload)) {
        clearMatchingLocal(scopedCredentials, diagnosisId, payload)
        await load(scopedCredentials)
        return true
      }
      const original = feedbackRecovery.value?.pending.find(
        (item) =>
          item.diagnosis_result_id === diagnosisId && item.request_id === payload.request_id,
      )
      if (original && !sameFeedbackPayload(original, payload)) {
        throw new FeedbackRequestError(
          '本页反馈与服务器记录不一致，请继续确认服务器中的原反馈；本页记录已保留。',
        )
      }
      return await sendFeedback(scopedCredentials, diagnosisId, payload)
    } finally {
      feedbackLoading.value = false
    }
  }

  async function generateAIExplanation(credentials: DeviceCredentials): Promise<void> {
    const scopedCredentials = { ...credentials }
    const scope = feedbackSessionScope(scopedCredentials)
    if (!dashboard.value?.diagnosis || activeSessionScope !== scope) return
    const diagnosisId = dashboard.value.diagnosis.id
    const sequence = ++aiSequence
    if (REVIEW_MODE) {
      dashboard.value.ai_explanation = structuredClone(reviewAIExplanation)
      return
    }
    aiLoading.value = true
    try {
      const explanation = await requestAIExplanation(scopedCredentials, diagnosisId)
      if (
        activeSessionScope === scope &&
        sequence === aiSequence &&
        dashboard.value?.diagnosis?.id === diagnosisId
      ) {
        dashboard.value.ai_explanation = explanation
      }
    } finally {
      if (sequence === aiSequence) aiLoading.value = false
    }
  }

  async function runDiagnosisWorkflow(credentials: DeviceCredentials): Promise<void> {
    const scopedCredentials = { ...credentials }
    const scope = feedbackSessionScope(scopedCredentials)
    if (activeSessionScope !== scope || !scopedCredentials.experimentSessionId) return
    const sequence = ++workflowSequence
    if (REVIEW_MODE) {
      workflow.value = structuredClone(reviewStudentWorkflow)
      return
    }
    workflowLoading.value = true
    try {
      const result = await startDiagnosisWorkflow(scopedCredentials)
      if (activeSessionScope !== scope || sequence !== workflowSequence) return
      workflow.value = result
      await load(scopedCredentials)
    } finally {
      if (sequence === workflowSequence) workflowLoading.value = false
    }
  }

  function clear(): void {
    activeSessionScope = null
    loadSequence += 1
    recoverySequence += 1
    aiSequence += 1
    workflowSequence += 1
    aiLoading.value = false
    workflowLoading.value = false
    feedbackRecoveryState.value = 'idle'
    feedbackRecovery.value = null
    feedbackRecoveryError.value = ''
    localFeedbackError.value = ''
    localFeedback.value = []
    state.value = 'idle'
    dashboard.value = null
    errorMessage.value = ''
    failureKind.value = null
    workflow.value = null
  }

  return {
    state,
    dashboard,
    errorMessage,
    failureKind,
    feedbackLoading,
    feedbackRecoveryState,
    feedbackRecovery,
    feedbackRecoveryError,
    localFeedbackError,
    pendingFeedback,
    feedbackBlocked,
    refreshFeedbackRecovery,
    recoverFeedback,
    aiLoading,
    workflowLoading,
    workflow,
    load,
    submitFeedback,
    generateAIExplanation,
    runDiagnosisWorkflow,
    clear,
  }
})
