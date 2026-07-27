import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getTeacherDashboard } from '@/api/teacher'
import {
  classifyRequestFailure,
  failureMessage,
  withCappedRetry,
  type RequestFailureKind,
} from '@/api/resilience'
import type { TeacherCredentials, TeacherDashboard } from '@/types/teacher'

export const useTeacherDashboardStore = defineStore('teacher-dashboard', () => {
  const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const dashboard = ref<TeacherDashboard | null>(null)
  const errorMessage = ref('')
  const failureKind = ref<RequestFailureKind | null>(null)

  async function load(credentials: TeacherCredentials): Promise<void> {
    state.value = dashboard.value ? 'ready' : 'loading'
    errorMessage.value = ''
    try {
      dashboard.value = await withCappedRetry(() => getTeacherDashboard(credentials))
      state.value = 'ready'
      failureKind.value = null
    } catch (error) {
      state.value = 'error'
      failureKind.value = classifyRequestFailure(error)
      errorMessage.value = failureMessage(failureKind.value)
    }
  }

  function clear(): void {
    state.value = 'idle'
    dashboard.value = null
    errorMessage.value = ''
    failureKind.value = null
  }

  return { state, dashboard, errorMessage, failureKind, load, clear }
})
