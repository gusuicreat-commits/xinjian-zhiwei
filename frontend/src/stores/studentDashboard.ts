import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  createDiagnosisFeedback,
  getStudentDashboard,
  requestAIExplanation,
} from '@/api/student'
import {
  classifyRequestFailure,
  failureMessage,
  withCappedRetry,
  type RequestFailureKind,
} from '@/api/resilience'
import type { DeviceCredentials, FeedbackAction, StudentDashboard } from '@/types/student'

export type DashboardState = 'idle' | 'loading' | 'ready' | 'error'

export const useStudentDashboardStore = defineStore('student-dashboard', () => {
  const state = ref<DashboardState>('idle')
  const dashboard = ref<StudentDashboard | null>(null)
  const errorMessage = ref('')
  const failureKind = ref<RequestFailureKind | null>(null)
  const feedbackLoading = ref(false)
  const aiLoading = ref(false)

  async function load(credentials: DeviceCredentials): Promise<void> {
    state.value = dashboard.value ? 'ready' : 'loading'
    errorMessage.value = ''
    try {
      dashboard.value = await withCappedRetry(() => getStudentDashboard(credentials))
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
    feedbackLoading.value = true
    try {
      dashboard.value.feedback = await createDiagnosisFeedback(
        credentials,
        dashboard.value.diagnosis.id,
        action,
      )
    } finally {
      feedbackLoading.value = false
    }
  }

  async function generateAIExplanation(credentials: DeviceCredentials): Promise<void> {
    if (!dashboard.value?.diagnosis) return
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

  function clear(): void {
    state.value = 'idle'
    dashboard.value = null
    errorMessage.value = ''
    failureKind.value = null
  }

  return {
    state,
    dashboard,
    errorMessage,
    failureKind,
    feedbackLoading,
    aiLoading,
    load,
    submitFeedback,
    generateAIExplanation,
    clear,
  }
})
