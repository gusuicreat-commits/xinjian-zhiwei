import { isAxiosError } from 'axios'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  createStudentSession,
  getStudentExperimentSessions,
  getStudentAssignments,
  startStudentExperiment,
  endStudentExperiment,
} from '@/api/student'
import { createUserSession } from '@/api/auth'
import { newRequestId } from '@/api/feedbackRetry'
import { REVIEW_MODE, reviewStudentCredentials, reviewStudentSession } from '@/review/fixtures'
import type {
  DeviceCredentials,
  StudentSession,
  StudentExperimentSession,
  StudentAssignment,
} from '@/types/student'

const STORAGE_KEY = 'xinjian-student-device-session'

export function hasStoredStudentSession(): boolean {
  return restoreCredentials() !== null
}

function restoreCredentials(): DeviceCredentials | null {
  if (REVIEW_MODE) return { ...reviewStudentCredentials }
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<DeviceCredentials>
    return value.deviceId && (value.accessToken || value.deviceToken)
      ? {
          deviceId: value.deviceId,
          deviceToken: value.deviceToken ?? '',
          accessToken: value.accessToken,
          experimentSessionId: value.experimentSessionId,
        }
      : null
  } catch {
    sessionStorage.removeItem(STORAGE_KEY)
    return null
  }
}

export const useStudentSessionStore = defineStore('student-session', () => {
  const credentials = ref<DeviceCredentials | null>(restoreCredentials())
  const session = ref<StudentSession | null>(null)
  const loading = ref(false)
  const errorMessage = ref('')
  const availableSessions = ref<StudentExperimentSession[]>([])
  const accountToken = ref('')
  const accountUserId = ref('')
  const assignments = ref<StudentAssignment[]>([])
  let authRevision = 0
  const isAuthenticated = computed(() => credentials.value !== null)

  async function login(nextCredentials: DeviceCredentials): Promise<void> {
    const revision = ++authRevision
    credentials.value = null
    session.value = null
    sessionStorage.removeItem(STORAGE_KEY)
    loading.value = true
    errorMessage.value = ''
    try {
      if (REVIEW_MODE) {
        session.value = { ...reviewStudentSession }
        credentials.value = {
          ...nextCredentials,
          experimentSessionId: reviewStudentSession.experiment_session_id ?? undefined,
        }
        return
      }
      const nextSession = await createStudentSession(nextCredentials)
      if (revision !== authRevision) return
      session.value = nextSession
      const scopedCredentials = {
        ...nextCredentials,
        experimentSessionId: session.value.experiment_session_id ?? undefined,
      }
      credentials.value = scopedCredentials
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(scopedCredentials))
    } catch {
      if (revision !== authRevision) return
      errorMessage.value = '身份或实验资格无效，请重新登录并选择当前实验。'
      throw new Error(errorMessage.value)
    } finally {
      if (revision === authRevision) loading.value = false
    }
  }

  async function authenticateAccount(username: string, password: string): Promise<void> {
    logout()
    const revision = authRevision
    loading.value = true
    try {
      const account = await createUserSession(username, password)
      if (!account.roles.includes('student')) throw new Error('student role required')
      const [sessions, tasks] = await Promise.all([
        getStudentExperimentSessions(account.access_token),
        getStudentAssignments(account.access_token),
      ])
      if (revision !== authRevision) return
      availableSessions.value = sessions
      assignments.value = tasks
      accountToken.value = account.access_token
      accountUserId.value = account.user_id
      if (availableSessions.value.length === 0) {
        errorMessage.value = '账号已验证，尚无有效实验。请在任务开放后开始实验或联系教师。'
      }
    } catch {
      if (revision !== authRevision) return
      errorMessage.value = '账号、密码或学生资格无效，请检查后重试。'
      throw new Error(errorMessage.value)
    } finally {
      if (revision === authRevision) loading.value = false
    }
  }

  async function beginExperiment(assignmentId: string, deviceId: string): Promise<void> {
    if (!accountToken.value || !accountUserId.value) throw new Error('account required')
    const key = `xinjian-start-session:${accountUserId.value}`
    const previous = sessionStorage.getItem(key)
    const payload = previous
      ? (JSON.parse(previous) as {
          request_id: string
          device_id: string
          experiment_assignment_id: string
        })
      : { request_id: newRequestId(), device_id: deviceId, experiment_assignment_id: assignmentId }
    if (payload.device_id !== deviceId || payload.experiment_assignment_id !== assignmentId) {
      errorMessage.value = '上次开始实验的结果尚未确认，请先重试原任务和设备。'
      throw new Error(errorMessage.value)
    }
    sessionStorage.setItem(key, JSON.stringify(payload))
    const revision = authRevision
    loading.value = true
    let started: StudentExperimentSession
    try {
      started = await startStudentExperiment(accountToken.value, payload)
      if (revision !== authRevision) return
      sessionStorage.removeItem(key)
      availableSessions.value = [
        started,
        ...availableSessions.value.filter((s) => s.id !== started.id),
      ]
      errorMessage.value = ''
    } catch (error) {
      if (revision !== authRevision) return
      if (isAxiosError(error) && error.response?.status === 409) {
        sessionStorage.removeItem(key)
        errorMessage.value = '设备被占用或任务状态已变化，本次开始请求被拒绝。请重新选择后再开始。'
      } else {
        errorMessage.value = '未能确认实验已开始。重试会沿用原请求，请先确认原请求再切换设备。'
      }
      throw new Error(errorMessage.value)
    } finally {
      if (revision === authRevision) loading.value = false
    }
    if (revision === authRevision) await selectExperiment(started.id)
  }

  async function finishExperiment(): Promise<void> {
    const current = credentials.value
    if (!current?.accessToken || !current.experimentSessionId) return
    const key = `xinjian-end-session:${current.experimentSessionId}`
    const previous = sessionStorage.getItem(key)
    let pending: { requestId: string; version: number }
    if (previous) pending = JSON.parse(previous) as typeof pending
    else {
      const sessions = await getStudentExperimentSessions(current.accessToken)
      const selected = sessions.find((s) => s.id === current.experimentSessionId)
      if (!selected) throw new Error('会话已变化，请重新登录确认。')
      pending = { requestId: newRequestId(), version: selected.version_no }
      sessionStorage.setItem(key, JSON.stringify(pending))
    }
    try {
      await endStudentExperiment(current, pending.requestId, pending.version)
    } catch (error) {
      if (isAxiosError(error) && error.response?.status === 409) sessionStorage.removeItem(key)
      throw error
    }
    sessionStorage.removeItem(key)
    if (credentials.value === current) logout()
  }

  async function selectExperiment(id: string): Promise<void> {
    const selected = availableSessions.value.find((item) => item.id === id)
    if (!selected || !accountToken.value) throw new Error('experiment selection required')
    await login({
      deviceId: selected.device_id,
      deviceToken: '',
      accessToken: accountToken.value,
      experimentSessionId: selected.id,
    })
  }

  function logout(): void {
    authRevision += 1
    credentials.value = null
    session.value = null
    errorMessage.value = ''
    accountToken.value = ''
    availableSessions.value = []
    assignments.value = []
    accountUserId.value = ''
    loading.value = false
    sessionStorage.removeItem(STORAGE_KEY)
  }

  return {
    credentials,
    session,
    loading,
    errorMessage,
    isAuthenticated,
    login,
    logout,
    availableSessions,
    authenticateAccount,
    selectExperiment,
    assignments,
    beginExperiment,
    finishExperiment,
  }
})
