import { apiClient } from '@/api/client'
import type {
  AIExplanationResponse,
  DeviceCredentials,
  FeedbackAction,
  StudentDashboard,
  StudentFeedback,
  StudentSession,
} from '@/types/student'

function authHeaders(credentials: DeviceCredentials): Record<string, string> {
  return {
    'X-Device-ID': credentials.deviceId,
    'X-Device-Token': credentials.deviceToken,
  }
}

export async function createStudentSession(
  credentials: DeviceCredentials,
): Promise<StudentSession> {
  const response = await apiClient.post<StudentSession>('/api/v1/student/session', null, {
    headers: authHeaders(credentials),
  })
  return response.data
}

export async function getStudentDashboard(
  credentials: DeviceCredentials,
): Promise<StudentDashboard> {
  const response = await apiClient.get<StudentDashboard>('/api/v1/student/dashboard', {
    headers: authHeaders(credentials),
  })
  return response.data
}

export async function createDiagnosisFeedback(
  credentials: DeviceCredentials,
  diagnosisId: string,
  action: FeedbackAction,
): Promise<StudentFeedback> {
  const response = await apiClient.post<StudentFeedback>(
    `/api/v1/student/diagnoses/${encodeURIComponent(diagnosisId)}/feedback`,
    { action },
    { headers: authHeaders(credentials) },
  )
  return response.data
}

export async function requestAIExplanation(
  credentials: DeviceCredentials,
  diagnosisId: string,
): Promise<AIExplanationResponse> {
  const response = await apiClient.post<AIExplanationResponse>(
    `/api/v1/diagnosis/results/${encodeURIComponent(diagnosisId)}/ai-explanation`,
    null,
    { headers: authHeaders(credentials) },
  )
  return response.data
}
