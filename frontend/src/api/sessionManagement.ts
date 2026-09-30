import { isAxiosError } from 'axios'
import {
  assertCommandRecoverable,
  recordCommandFailure,
  commandOutcome,
  completeCommand,
  recoverSessionCommand,
} from './commandOutcome'
import { apiClient } from './client'
import { newRequestId } from './feedbackRetry'

export interface ManagedSession {
  id: string
  device_id: string
  display_name: string | null
  student_name: string
  class_name: string
  assignment_title: string
  started_at: string
  status: string
  version_no: number
  is_test_data: boolean
}
export interface PendingRelease {
  session: ManagedSession
  payload: { request_id: string; expected_version: number; reason: string }
}
const key = (userId: string) => `xinjian-session-release:${userId}`

function authorize(token: string, userId: string) {
  const session = JSON.parse(sessionStorage.getItem('xinjian-teacher-session') || 'null')
  if (session?.user_id !== userId || session?.access_token !== token)
    throw new Error('教师登录已变化，请重新登录。')
}
export function pendingReleases(userId: string): PendingRelease[] {
  const value = JSON.parse(sessionStorage.getItem(key(userId)) || '[]')
  if (!Array.isArray(value)) throw new Error('待确认操作记录无法读取，请重新登录后核查。')
  return value
}
function save(userId: string, pending: PendingRelease[]) {
  sessionStorage.setItem(key(userId), JSON.stringify(pending))
}
export async function getManagedSessions(token: string): Promise<ManagedSession[]> {
  return (
    await apiClient.get('/api/v1/teacher/experiment-sessions', {
      headers: { Authorization: `Bearer ${token}` },
    })
  ).data
}
export async function releaseManagedSession(
  token: string,
  userId: string,
  session: ManagedSession,
  reason: string,
): Promise<void> {
  authorize(token, userId)
  const commandKey = `${key(userId)}:${session.id}`
  const identity = sessionStorage.getItem('xinjian-teacher-session')
  const isCurrent = () => sessionStorage.getItem('xinjian-teacher-session') === identity
  if (await recoverSessionCommand(commandKey, token, isCurrent)) {
    authorize(token, userId)
    return
  }
  authorize(token, userId)
  assertCommandRecoverable(commandKey)
  const pending = pendingReleases(userId)
  let command = pending.find((item) => item.session.id === session.id)
  if (command && command.payload.reason !== reason.trim())
    throw new Error('上次操作尚未确认，请先确认原操作。')
  if (!command) {
    if (!reason.trim()) throw new Error('请填写结束占用的原因。')
    command = {
      session,
      payload: {
        request_id: newRequestId(),
        expected_version: session.version_no,
        reason: reason.trim(),
      },
    }
    save(userId, [...pending, command]) // Store before sending; storage failure must prevent mutation.
  }
  const remove = () =>
    save(
      userId,
      pendingReleases(userId).filter(
        (item) => item.payload.request_id !== command.payload.request_id,
      ),
    )
  try {
    await apiClient.post(
      `/api/v1/teacher/experiment-sessions/${encodeURIComponent(session.id)}/release`,
      command.payload,
      { headers: { Authorization: `Bearer ${token}` } },
    )
  } catch (error) {
    recordCommandFailure(commandKey, 'releaseManagedSession', command.payload.request_id, error)
    if (!commandOutcome('releaseManagedSession', error).retainPayload) remove()
    throw error
  }
  authorize(token, userId)
  completeCommand(commandKey, command.payload.request_id)
  remove()
}

export async function authorizedPendingReleases(
  token: string,
  userId: string,
): Promise<PendingRelease[]> {
  authorize(token, userId)
  const pending = await Promise.all(
    pendingReleases(userId).map(async (item) => {
      try {
        await apiClient.get(
          `/api/v1/teacher/experiment-sessions/${encodeURIComponent(item.session.id)}`,
          { headers: { Authorization: `Bearer ${token}` } },
        )
        return item
      } catch (error) {
        if (isAxiosError(error) && error.response?.status === 403) return null
        throw error
      }
    }),
  )
  return pending.filter((item): item is PendingRelease => item !== null)
}
