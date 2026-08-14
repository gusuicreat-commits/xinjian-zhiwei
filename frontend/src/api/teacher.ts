import { apiClient } from '@/api/client'
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
  await apiClient.post(`/api/v1/teacher-workflow/interventions/${caseId}/actions`, payload, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
}
