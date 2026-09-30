import { assertCommandRecoverable, recordCommandFailure, completeCommand } from './commandOutcome'
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
  const auth = JSON.parse(
    sessionStorage.getItem('xinjian-teacher-session') ?? 'null',
  ) as UserSession | null
  if (!auth || auth.access_token !== accessToken) throw new Error('TEACHER_SESSION_REQUIRED')
  const key = `xinjian-workflow-review:${auth.user_id}:${workflowId}`
  const identity = sessionStorage.getItem('xinjian-teacher-session')
  const recoveryRaw = sessionStorage.getItem(`${key}:recovery`)
  if (recoveryRaw) {
    const current = await apiClient.get<TeacherDiagnosisWorkflow>(
      `/api/v1/diagnosis-workflows/${encodeURIComponent(workflowId)}`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
    if (
      sessionStorage.getItem('xinjian-teacher-session') !== identity ||
      sessionStorage.getItem(`${key}:recovery`) !== recoveryRaw
    )
      throw new Error('TEACHER_SESSION_REQUIRED')
    if (['completed', 'rejected'].includes(current.data.status)) {
      completeCommand(key, workflowId)
      return current.data
    }
  }
  assertCommandRecoverable(key)
  try {
    const response = await apiClient.post<TeacherDiagnosisWorkflow>(
      `/api/v1/diagnosis-workflows/${encodeURIComponent(workflowId)}/review`,
      payload,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
    completeCommand(key, workflowId)
    return response.data
  } catch (error) {
    recordCommandFailure(key, 'reviewDiagnosisWorkflow', workflowId, error)
    // This endpoint has no command receipt ID. Require an explicit read-only
    // review of workflow history before any further manual review submission.
    if (sessionStorage.getItem(`${key}:uncertain`)) {
      sessionStorage.setItem(
        `${key}:recovery`,
        JSON.stringify({ operation: 'reviewDiagnosisWorkflow', workflow_id: workflowId }),
      )
    }
    throw error
  }
}

export async function getTeacherDashboard(accessToken: string): Promise<TeacherDashboard> {
  const response = await apiClient.get<TeacherDashboard>('/api/v1/teacher/dashboard', {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return response.data
}

async function recoverInterventionCommand(
  accessToken: string,
  userId: string,
  caseId: string,
  key: string,
): Promise<boolean> {
  const raw = sessionStorage.getItem(`${key}:recovery`)
  if (!raw) return false
  const bookmark = JSON.parse(raw) as { request_id: string }
  const response = await apiClient.get<
    Array<{ actor_user_id: string; metadata: { request_id?: string } }>
  >(`/api/v1/teacher-workflow/interventions/${encodeURIComponent(caseId)}/timeline`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  const auth = JSON.parse(
    sessionStorage.getItem('xinjian-teacher-session') ?? 'null',
  ) as UserSession | null
  if (auth?.user_id !== userId || auth?.access_token !== accessToken)
    throw new Error('TEACHER_SESSION_REQUIRED')
  if (sessionStorage.getItem(`${key}:recovery`) !== raw)
    throw new Error('恢复请求已变化，请重新查询。')
  if (
    response.data.some(
      (event) =>
        event.actor_user_id === userId && event.metadata.request_id === bookmark.request_id,
    )
  ) {
    completeCommand(key, bookmark.request_id)
    return true
  }
  assertCommandRecoverable(key)
  return false
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
  if (await recoverInterventionCommand(accessToken, auth.user_id, caseId, key)) return
  const currentAuth = JSON.parse(
    sessionStorage.getItem('xinjian-teacher-session') ?? 'null',
  ) as UserSession | null
  if (currentAuth?.access_token !== accessToken || currentAuth?.user_id !== auth.user_id)
    throw new Error('TEACHER_SESSION_REQUIRED')
  assertCommandRecoverable(key)
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
    recordCommandFailure(key, 'actOnTeacherIntervention', pending.request_id, error)
    throw error
  }
  completeCommand(key, pending.request_id)
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
  const auth = JSON.parse(
    sessionStorage.getItem('xinjian-teacher-session') ?? 'null',
  ) as UserSession | null
  if (auth?.user_id !== userId || auth?.access_token !== accessToken)
    throw new Error('TEACHER_SESSION_REQUIRED')
  const key = `xinjian-problem-report:${userId}:${caseId}`
  if (await recoverInterventionCommand(accessToken, userId, caseId, key)) return
  const currentAuth = JSON.parse(
    sessionStorage.getItem('xinjian-teacher-session') ?? 'null',
  ) as UserSession | null
  if (currentAuth?.access_token !== accessToken || currentAuth?.user_id !== auth.user_id)
    throw new Error('TEACHER_SESSION_REQUIRED')
  assertCommandRecoverable(key)
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
    recordCommandFailure(key, 'reportTeacherProblemResolved', payload.request_id, error)
    throw error
  }
  completeCommand(key, payload.request_id)
}
