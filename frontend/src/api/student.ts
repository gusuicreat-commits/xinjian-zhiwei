import { submitCheck } from './diagnosisChecks'
import { apiClient } from '@/api/client'
import type {
  AIExplanationResponse,
  DiagnosisWorkflow,
  DeviceCredentials,
  FeedbackRecovery,
  StudentDashboard,
  StudentFeedback,
  StudentFeedbackCreate,
  StudentSession,
  StudentExperimentSession,
  StudentAssignment,
} from '@/types/student'

function authHeaders(credentials: DeviceCredentials): Record<string, string> {
  const headers: Record<string, string> = {
    'X-Device-ID': credentials.deviceId,
  }
  if (credentials.accessToken) headers.Authorization = `Bearer ${credentials.accessToken}`
  else headers['X-Device-Token'] = credentials.deviceToken
  if (credentials.experimentSessionId) {
    headers['X-Experiment-Session-ID'] = credentials.experimentSessionId
  }
  return headers
}

export async function getStudentExperimentSessions(
  token: string,
): Promise<StudentExperimentSession[]> {
  const response = await apiClient.get<StudentExperimentSession[]>(
    '/api/v1/student/experiment-sessions',
    {
      headers: { Authorization: `Bearer ${token}` },
    },
  )
  return response.data
}

export async function getStudentAssignments(token: string): Promise<StudentAssignment[]> {
  const response = await apiClient.get<StudentAssignment[]>('/api/v1/student/assignments', {
    headers: { Authorization: `Bearer ${token}` },
  })
  return response.data
}

export async function startStudentExperiment(
  token: string,
  payload: {
    request_id: string
    device_id: string
    experiment_assignment_id: string
  },
): Promise<StudentExperimentSession> {
  const response = await apiClient.post<StudentExperimentSession>(
    '/api/v1/student/experiment-sessions',
    payload,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
  )
  return response.data
}

export async function endStudentExperiment(
  credentials: DeviceCredentials,
  requestId: string,
  version: number,
): Promise<void> {
  await apiClient.post(
    `/api/v1/student/experiment-sessions/${credentials.experimentSessionId}/end`,
    {
      request_id: requestId,
      expected_version: version,
      reason: 'completed',
    },
    { headers: authHeaders(credentials) },
  )
}

export async function startDiagnosisWorkflow(
  credentials: DeviceCredentials,
  baselineId?: string | null,
): Promise<DiagnosisWorkflow> {
  return submitCheck(credentials, authHeaders(credentials), baselineId)
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

export async function getFeedbackRecovery(
  credentials: DeviceCredentials,
): Promise<FeedbackRecovery> {
  if (!credentials.experimentSessionId) {
    throw new Error('反馈需要实验会话，请重新登录。')
  }
  const response = await apiClient.get<FeedbackRecovery>('/api/v1/student/feedback-recovery', {
    headers: authHeaders(credentials),
  })
  return response.data
}

export async function createDiagnosisFeedback(
  credentials: DeviceCredentials,
  diagnosisId: string,
  payload: StudentFeedbackCreate,
): Promise<StudentFeedback> {
  if (!credentials.experimentSessionId) {
    throw new Error('反馈需要实验会话，请重新登录。')
  }
  const response = await apiClient.post<StudentFeedback>(
    `/api/v1/student/diagnoses/${encodeURIComponent(diagnosisId)}/feedback`,
    payload,
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

export type QueryAnswerValue = 'matches_table' | 'differs' | 'unclear'
export interface QueryAnswerPayload {
  request_id: string
  question_id: string
  question_version: string
  value: QueryAnswerValue
}
export interface QueryTask {
  id: string
  contract_version: string
  status: 'waiting_answer' | 'completed_satisfied' | 'finish_unknown' | 'stale'
  terminal_reason: string | null
  requirements: Record<string, { status: string; judgement: string; gap: string | null }>
  question: {
    question_id: string
    version: string
    requirement: string
    options: QueryAnswerValue[]
    synthetic: boolean
  } | null
  query_count: number
  question_count: number
  is_test_data: boolean
  root_cause_status: 'unconfirmed'
  physical_verification: 'not_asserted'
}
export async function findStudentQuery(credentials: DeviceCredentials, diagnosisId: string) {
  return (
    await apiClient.get<QueryTask | null>(
      `/api/v1/student/diagnoses/${encodeURIComponent(diagnosisId)}/queries`,
      { headers: authHeaders(credentials) },
    )
  ).data
}
export async function startStudentQuery(credentials: DeviceCredentials, diagnosisId: string) {
  return (
    await apiClient.post<QueryTask>(
      `/api/v1/student/diagnoses/${encodeURIComponent(diagnosisId)}/queries`,
      null,
      { headers: authHeaders(credentials) },
    )
  ).data
}
export async function readStudentQuery(credentials: DeviceCredentials, taskId: string) {
  return (
    await apiClient.get<QueryTask>(`/api/v1/student/queries/${encodeURIComponent(taskId)}`, {
      headers: authHeaders(credentials),
    })
  ).data
}
export async function answerStudentQuery(
  credentials: DeviceCredentials,
  taskId: string,
  payload: QueryAnswerPayload,
) {
  return (
    await apiClient.post<{ id: string; request_id: string; value: QueryAnswerValue }>(
      `/api/v1/student/queries/${encodeURIComponent(taskId)}/answers`,
      payload,
      { headers: authHeaders(credentials) },
    )
  ).data
}
