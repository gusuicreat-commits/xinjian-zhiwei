import { defineStore } from 'pinia'
import { ref } from 'vue'

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

  async function load(credentials: DeviceCredentials): Promise<void> {
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
      dashboard.value = await withCappedRetry(() => getStudentDashboard(credentials))
      try {
        workflow.value = await getLatestDiagnosisWorkflow(credentials)
      } catch {
        // The additive graph surface must not take down the legacy student dashboard.
        workflow.value = null
      }
      state.value = 'ready'
      failureKind.value = null
    } catch (error) {
      state.value = 'error'
      failureKind.value = classifyRequestFailure(error)
      errorMessage.value = failureMessage(failureKind.value)
    }
  }

  async function submitFeedback(
    credentials: DeviceCredentials,
    action: FeedbackAction,
  ): Promise<void> {
    if (!dashboard.value?.diagnosis) return
    if (REVIEW_MODE) {
      dashboard.value.feedback = {
        id: 'review-feedback-interactive',
        action,
        note: null,
        is_test_data: true,
        created_at: new Date().toISOString(),
      }
      return
    }
    feedbackLoading.value = true
    try {
      dashboard.value.feedback = await createDiagnosisFeedback(
        credentials,
        dashboard.value.diagnosis.id,
        action,
      )
      await load(credentials)
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
