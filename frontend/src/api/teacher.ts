import { isAxiosError } from 'axios'
import { apiClient } from '@/api/client'
import { newRequestId } from '@/api/feedbackRetry'
import { createUserSession } from '@/api/auth'
import type { UserSession } from '@/types/auth'
import type {
  DiagnosisWorkflowMetrics,
  TeacherDashboard,
  TeacherDiagnosisWorkflow,
} from '@/types/teacher'

export async function createTeacherSession(
  username: string,
  password: string,
): Promise<UserSession> {
  const session = await createUserSession(username, password)
  if (!session.roles.some((role) => role === 'teacher' || role === 'admin')) {
    throw new Error('TEACHER_ROLE_REQUIRED')
  }
  return session
}

export async function getPendingDiagnosisWorkflows(
  accessToken: string,
): Promise<TeacherDiagnosisWorkflow[]> {
  const response = await apiClient.get<TeacherDiagnosisWorkflow[]>(
    '/api/v1/diagnosis-workflows/review-queue/pending',
    { headers: { Authorization: `Bearer ${accessToken}` } },
  )
  return response.data
}

export async function getRecentDiagnosisWorkflows(
  accessToken: string,
): Promise<TeacherDiagnosisWorkflow[]> {
  const response = await apiClient.get<TeacherDiagnosisWorkflow[]>(
    '/api/v1/diagnosis-workflows/review-queue/recent',
    { headers: { Authorization: `Bearer ${accessToken}` } },
  )
  return response.data
}

export async function getDiagnosisWorkflowMetrics(
  accessToken: string,
): Promise<DiagnosisWorkflowMetrics> {
  const response = await apiClient.get<DiagnosisWorkflowMetrics>(
    '/api/v1/diagnosis-workflows/metrics/summary',
    { headers: { Authorization: `Bearer ${accessToken}` } },
  )
  return response.data
}

export async function reviewDiagnosisWorkflow(
  accessToken: string,
  workflowId: string,
  payload: {
    action: 'approve' | 'edit' | 'reject'
    comment?: string
    edited_result?: {
      summary: string
      possible_causes?: string[]
      steps?: string[]
      limitations?: string[]
    }
  },
): Promise<TeacherDiagnosisWorkflow> {
  const response = await apiClient.post<TeacherDiagnosisWorkflow>(
    `/api/v1/diagnosis-workflows/${encodeURIComponent(workflowId)}/review`,
    payload,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  )
  return response.data
}

export async function getTeacherDashboard(accessToken: string): Promise<TeacherDashboard> {
  const response = await apiClient.get<TeacherDashboard>('/api/v1/teacher/dashboard', {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return response.data
}

export async function actOnTeacherIntervention(
  accessToken: string,
  caseId: string,
  payload: {
    action: 'claim' | 'resolve' | 'close'
    expected_version: number
    note?: string
    is_private: boolean
  },
): Promise<void> {
  // Scope pending commands to the signed-in account, without persisting its token.
  const auth = JSON.parse(
    sessionStorage.getItem('xinjian-teacher-session') ?? 'null',
  ) as UserSession | null
  if (!auth || auth.access_token !== accessToken) throw new Error('TEACHER_SESSION_REQUIRED')
  const key = `xinjian-intervention:${auth.user_id}:${caseId}`
  const previous = sessionStorage.getItem(key)
  const pending = previous
    ? (JSON.parse(previous) as {
        request_id: string
        payload: { action: string; expected_version: number; note?: string; is_private: boolean }
      })
    : { request_id: newRequestId(), payload }
  if (JSON.stringify(pending.payload) !== JSON.stringify(payload)) {
    throw new Error('请先确认上次工单操作的结果，不能用新内容覆盖待确认请求。')
  }
  sessionStorage.setItem(key, JSON.stringify(pending))
  try {
    await apiClient.post(
      `/api/v1/teacher-workflow/interventions/${caseId}/actions`,
      {
        ...pending.payload,
        request_id: pending.request_id,
      },
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
  } catch (error) {
    // A received conflict is a definite rejection; retain only uncertain outcomes.
    if (isAxiosError(error) && error.response?.status === 409) sessionStorage.removeItem(key)
    throw error
  }
  sessionStorage.removeItem(key)
}

export function pendingInterventionCommand(
  userId: string,
  caseId: string,
): {
  request_id: string
  payload: Parameters<typeof actOnTeacherIntervention>[2]
} | null {
  const raw = sessionStorage.getItem(`xinjian-intervention:${userId}:${caseId}`)
  return raw ? JSON.parse(raw) : null
}

export async function reportTeacherProblemResolved(
  accessToken: string,
  userId: string,
  caseId: string,
  revision: number,
): Promise<void> {
  const key = `xinjian-problem-report:${userId}:${caseId}`
  const previous = sessionStorage.getItem(key)
  const payload = previous
    ? JSON.parse(previous)
    : { request_id: newRequestId(), expected_revision: revision }
  sessionStorage.setItem(key, JSON.stringify(payload))
  try {
    await apiClient.post(
      `/api/v1/teacher-workflow/interventions/${caseId}/problem-resolution`,
      payload,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 409) sessionStorage.removeItem(key)
    throw error
  }
  sessionStorage.removeItem(key)
}
