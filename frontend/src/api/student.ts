import { apiClient } from '@/api/client'
import type {
  AIExplanationResponse,
  DiagnosisWorkflow,
  DeviceCredentials,
  FeedbackAction,
  StudentDashboard,
  StudentFeedback,
  StudentSession,
} from '@/types/student'

function authHeaders(credentials: DeviceCredentials): Record<string, string> {
  const headers: Record<string, string> = {
    'X-Device-ID': credentials.deviceId,
    'X-Device-Token': credentials.deviceToken,
  }
  if (credentials.experimentSessionId) {
    headers['X-Experiment-Session-ID'] = credentials.experimentSessionId
  }
  return headers
}

export async function startDiagnosisWorkflow(
  credentials: DeviceCredentials,
): Promise<DiagnosisWorkflow> {
  const response = await apiClient.post<DiagnosisWorkflow>(
    `/api/v1/diagnosis-workflows/devices/${encodeURIComponent(credentials.deviceId)}`,
    {},
    { headers: authHeaders(credentials) },
  )
  return response.data
}

export async function getLatestDiagnosisWorkflow(
  credentials: DeviceCredentials,
): Promise<DiagnosisWorkflow | null> {
  const response = await apiClient.get<DiagnosisWorkflow | null>(
    `/api/v1/diagnosis-workflows/devices/${encodeURIComponent(credentials.deviceId)}/latest`,
    { headers: authHeaders(credentials) },
  )
  return response.data
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
