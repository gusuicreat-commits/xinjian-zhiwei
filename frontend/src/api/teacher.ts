import { apiClient } from '@/api/client'
import { createUserSession } from '@/api/auth'
import type { UserSession } from '@/types/auth'
import type { TeacherDashboard } from '@/types/teacher'

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
  await apiClient.post(
    `/api/v1/teacher-workflow/interventions/${caseId}/actions`,
    payload,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  )
}
