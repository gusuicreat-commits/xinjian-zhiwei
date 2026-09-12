import axios from 'axios'
import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  completeFeedbackRequest,
  FeedbackRequestError,
  feedbackSessionScope,
  getOrCreateFeedbackRequest,
} from '@/api/feedbackRetry'
import {
  createDiagnosisFeedback,
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

  async function load(credentials: DeviceCredentials): Promise<void> {
    const scope = feedbackSessionScope(credentials)
    if (activeSessionScope !== scope) {
      dashboard.value = null
      workflow.value = null
      activeSessionScope = scope
    }
    const sequence = ++loadSequence
    state.value = dashboard.value ? 'ready' : 'loading'
    errorMessage.value = ''
    if (REVIEW_MODE) {
      dashboard.value = structuredClone(reviewStudentDashboard)
      workflow.value = structuredClone(reviewStudentWorkflow)
      state.value = 'ready'
      failureKind.value = null
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
    const payload = getOrCreateFeedbackRequest(scopedCredentials, diagnosisId, action)
    feedbackLoading.value = true
    try {
      const feedback = await withCappedRetry(() =>
        createDiagnosisFeedback(scopedCredentials, diagnosisId, payload),
      )
      completeFeedbackRequest(scopedCredentials, diagnosisId)
      if (activeSessionScope === scope && dashboard.value?.diagnosis?.id === diagnosisId) {
        dashboard.value.feedback = feedback
        await load(scopedCredentials)
      }
      return true
    } catch (error) {
      if (error instanceof FeedbackRequestError) throw error
      if (
        axios.isAxiosError(error) &&
        error.response &&
        [400, 401, 403, 404, 422].includes(error.response.status)
      ) {
        completeFeedbackRequest(scopedCredentials, diagnosisId)
        throw new FeedbackRequestError('反馈已被拒绝，未被接受；请检查实验会话并刷新诊断后再提交。')
      }
      throw new FeedbackRequestError(
        '反馈结果尚未确认，请重试同一反馈；系统会沿用原提交记录，避免重复处理。',
      )
    } finally {
      feedbackLoading.value = false
    }
  }

  async function generateAIExplanation(credentials: DeviceCredentials): Promise<void> {
    if (!dashboard.value?.diagnosis) return
    if (REVIEW_MODE) {
      dashboard.value.ai_explanation = structuredClone(reviewAIExplanation)
      return
    }
    aiLoading.value = true
    try {
      dashboard.value.ai_explanation = await requestAIExplanation(
        credentials,
        dashboard.value.diagnosis.id,
      )
    } finally {
      aiLoading.value = false
    }
  }

  async function runDiagnosisWorkflow(credentials: DeviceCredentials): Promise<void> {
    if (REVIEW_MODE) {
      workflow.value = structuredClone(reviewStudentWorkflow)
      return
    }
    workflowLoading.value = true
    try {
      workflow.value = await startDiagnosisWorkflow(credentials)
      await load(credentials)
    } finally {
      workflowLoading.value = false
    }
  }

  function clear(): void {
    activeSessionScope = null
    loadSequence += 1
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
