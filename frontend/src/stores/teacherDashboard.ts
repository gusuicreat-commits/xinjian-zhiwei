import { defineStore } from 'pinia'
import { ref } from 'vue'

import { actOnTeacherIntervention, getTeacherDashboard } from '@/api/teacher'
import {
  classifyRequestFailure,
  failureMessage,
  withCappedRetry,
  type RequestFailureKind,
} from '@/api/resilience'
import type { TeacherDashboard } from '@/types/teacher'

export const useTeacherDashboardStore = defineStore('teacher-dashboard', () => {
  const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const dashboard = ref<TeacherDashboard | null>(null)
  const errorMessage = ref('')
  const failureKind = ref<RequestFailureKind | null>(null)
  const actionLoadingCaseId = ref<string | null>(null)

  async function load(accessToken: string): Promise<void> {
    state.value = dashboard.value ? 'ready' : 'loading'
    errorMessage.value = ''
    try {
      dashboard.value = await withCappedRetry(() => getTeacherDashboard(accessToken))
      state.value = 'ready'
      failureKind.value = null
    } catch (error) {
      state.value = 'error'
      failureKind.value = classifyRequestFailure(error)
      errorMessage.value = failureMessage(failureKind.value)
    }
  }

  async function act(
    accessToken: string,
    caseId: string,
    payload: {
      action: 'claim' | 'resolve' | 'close'
      expected_version: number
      note?: string
      is_private: boolean
    },
  ): Promise<void> {
    actionLoadingCaseId.value = caseId
    try {
      await actOnTeacherIntervention(accessToken, caseId, payload)
      await load(accessToken)
    } finally {
      actionLoadingCaseId.value = null
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
    actionLoadingCaseId,
    load,
    act,
    clear,
  }
})
