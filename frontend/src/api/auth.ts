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

// A 401 means this token is already unusable. Other failures remain unconfirmed.
export async function revokeUserSession(token: string): Promise<boolean> {
  if (!token) return true
  try {
    await apiClient.delete('/api/v1/auth/session', { headers: bearer(token) })
    return true
  } catch (error) {
    return (error as { response?: { status?: number } }).response?.status === 401
  }
}
