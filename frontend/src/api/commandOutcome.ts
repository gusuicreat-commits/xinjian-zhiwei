import { isAxiosError } from 'axios'

export type CommandOperation =
  | 'beginExperiment'
  | 'finishExperiment'
  | 'actOnTeacherIntervention'
  | 'reportTeacherProblemResolved'
  | 'reviewDiagnosisWorkflow'
  | 'sendFeedback'
  | 'recoverFeedback'
  | 'submitCheck'
  | 'releaseManagedSession'
const keepConflict: Record<CommandOperation, boolean> = {
  beginExperiment: false,
  finishExperiment: false,
  actOnTeacherIntervention: false,
  reportTeacherProblemResolved: false,
  reviewDiagnosisWorkflow: true,
  sendFeedback: true,
  recoverFeedback: true,
  submitCheck: false,
  releaseManagedSession: false,
}
export function commandOutcome(operation: CommandOperation, error: unknown) {
  const status = isAxiosError(error) ? error.response?.status : undefined
  const permission = status === 401 || status === 403
  const rejected =
    status !== undefined &&
    ([400, 401, 403, 404, 422, 429].includes(status) ||
      (status === 409 && !keepConflict[operation]))
  return { status, permission, retainPayload: !rejected, uncertain: !rejected }
}
export class CommandRecoveryError extends Error {}
export function assertCommandRecoverable(key: string): void {
  const raw = sessionStorage.getItem(`${key}:recovery`)
  if (raw) {
    const bookmark = JSON.parse(raw)
    const reference = bookmark.request_id ?? bookmark.workflow_id
    throw new CommandRecoveryError(
      `此前操作结果仍需核查。请重新授权后核对原请求回执或联系教师管理员确认；不会自动创建新请求。核查编号：${reference}`,
    )
  }
}
// Unknown outcomes keep executable payload only while still authorized. A later
// rejection cannot establish that the earlier request did not commit.
export function recordCommandFailure(
  key: string,
  operation: CommandOperation,
  requestId: string,
  error: unknown,
): void {
  for (const candidate of [key, `${key}:recovery`]) {
    const raw = sessionStorage.getItem(candidate)
    if (!raw) continue
    const stored = JSON.parse(raw)
    const storedId = stored.request_id ?? stored.requestId ?? stored.workflow_id
    if (storedId && storedId !== requestId) return
  }
  const outcome = commandOutcome(operation, error)
  const uncertainKey = `${key}:uncertain`
  if (outcome.uncertain) sessionStorage.setItem(uncertainKey, '1')
  if (!outcome.retainPayload) {
    if (sessionStorage.getItem(uncertainKey)) {
      sessionStorage.setItem(
        `${key}:recovery`,
        JSON.stringify({ operation, request_id: requestId }),
      )
    }
    sessionStorage.removeItem(key)
    sessionStorage.removeItem(uncertainKey)
  }
}
export function completeCommand(key: string, expectedRequestId: string): void {
  for (const candidate of [key, `${key}:recovery`]) {
    const raw = sessionStorage.getItem(candidate)
    if (!raw) continue
    const stored = JSON.parse(raw)
    const storedId = stored.request_id ?? stored.requestId ?? stored.workflow_id
    if (storedId && storedId !== expectedRequestId) return
  }
  sessionStorage.removeItem(key)
  sessionStorage.removeItem(`${key}:uncertain`)
  sessionStorage.removeItem(`${key}:recovery`)
}

export async function recoverSessionCommand(
  key: string,
  token: string,
  isCurrent: () => boolean,
): Promise<import('@/types/student').StudentExperimentSession | null> {
  const raw = sessionStorage.getItem(`${key}:recovery`)
  if (!raw) return null
  const bookmark = JSON.parse(raw) as { request_id: string }
  const { apiClient } = await import('./client')
  try {
    const response = await apiClient.get<{
      status: 'applied'
      result: import('@/types/student').StudentExperimentSession
    }>(`/api/v1/student/experiment-session-commands/${encodeURIComponent(bookmark.request_id)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!isCurrent() || sessionStorage.getItem(`${key}:recovery`) !== raw) return null
    if (response.data.status === 'applied') {
      completeCommand(key, bookmark.request_id)
      return response.data.result
    }
  } catch (error) {
    if (!isCurrent() || sessionStorage.getItem(`${key}:recovery`) !== raw) return null
    if (!isAxiosError(error) || error.response?.status !== 404) throw error
  }
  assertCommandRecoverable(key)
  return null
}
