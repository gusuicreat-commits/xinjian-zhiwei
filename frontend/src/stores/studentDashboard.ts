import { defineStore } from 'pinia'
import { ref } from 'vue'

import { createDiagnosisFeedback, getStudentDashboard } from '@/api/student'
import type { DeviceCredentials, FeedbackAction, StudentDashboard } from '@/types/student'

export type DashboardState = 'idle' | 'loading' | 'ready' | 'error'

export const useStudentDashboardStore = defineStore('student-dashboard', () => {
  const state = ref<DashboardState>('idle')
  const dashboard = ref<StudentDashboard | null>(null)
  const errorMessage = ref('')
  const feedbackLoading = ref(false)

  async function load(credentials: DeviceCredentials): Promise<void> {
    state.value = dashboard.value ? 'ready' : 'loading'
    errorMessage.value = ''
    try {
      dashboard.value = await getStudentDashboard(credentials)
      state.value = 'ready'
    } catch {
      state.value = 'error'
      errorMessage.value = '学生数据加载失败，请检查会话或后端服务。'
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

  function clear(): void {
    state.value = 'idle'
    dashboard.value = null
    errorMessage.value = ''
  }

  return { state, dashboard, errorMessage, feedbackLoading, load, submitFeedback, clear }
})
