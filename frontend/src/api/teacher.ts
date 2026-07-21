import { apiClient } from '@/api/client'
import type { TeacherCredentials, TeacherDashboard, TeacherSession } from '@/types/teacher'

function headers(credentials: TeacherCredentials): Record<string, string> {
  return { 'X-Review-Token': credentials.reviewToken }
}

export async function createTeacherSession(
  credentials: TeacherCredentials,
): Promise<TeacherSession> {
  const response = await apiClient.post<TeacherSession>('/api/v1/teacher/session', null, {
    headers: headers(credentials),
  })
  return response.data
}

export async function getTeacherDashboard(
  credentials: TeacherCredentials,
): Promise<TeacherDashboard> {
  const response = await apiClient.get<TeacherDashboard>('/api/v1/teacher/dashboard', {
    headers: headers(credentials),
  })
  return response.data
}
