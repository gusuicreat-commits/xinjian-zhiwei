import { apiClient } from '@/api/client'
import type { ClassroomSummary, CurrentUser, UserSession } from '@/types/auth'

const bearer = (token: string) => ({ Authorization: `Bearer ${token}` })

export async function createUserSession(username: string, password: string): Promise<UserSession> {
  const response = await apiClient.post<UserSession>('/api/v1/auth/session', {
    username,
    password,
  })
  return response.data
}

export async function getCurrentUser(token: string): Promise<CurrentUser> {
  const response = await apiClient.get<CurrentUser>('/api/v1/auth/me', {
    headers: bearer(token),
  })
  return response.data
}

export async function getMyClasses(token: string): Promise<ClassroomSummary[]> {
  const response = await apiClient.get<ClassroomSummary[]>('/api/v1/auth/classes', {
    headers: bearer(token),
  })
  return response.data
}
