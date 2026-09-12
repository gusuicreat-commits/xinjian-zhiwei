import type { DeviceCredentials, FeedbackAction, StudentFeedbackCreate } from '@/types/student'

const STORAGE_PREFIX = 'xinjian-pending-feedback:'
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const ACTIONS: FeedbackAction[] = ['resolved', 'unresolved', 'request_teacher_help']
const ACTION_LABELS: Record<FeedbackAction, string> = {
  resolved: '问题已解决',
  unresolved: '仍未解决',
  request_teacher_help: '请求教师帮助',
}

export class FeedbackRequestError extends Error {}

function newRequestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  // randomUUID is unavailable on plain HTTP LAN origins; getRandomValues remains usable.
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function feedbackSessionScope(credentials: DeviceCredentials): string {
  return JSON.stringify([credentials.deviceId, credentials.experimentSessionId ?? null])
}

function storageKey(credentials: DeviceCredentials, diagnosisId: string): string {
  // A pending request belongs to one diagnosis and one experiment session. No token is saved.
  return `${STORAGE_PREFIX}${JSON.stringify([
    credentials.deviceId,
    credentials.experimentSessionId,
    diagnosisId,
  ])}`
}

export function getOrCreateFeedbackRequest(
  credentials: DeviceCredentials,
  diagnosisId: string,
  action: FeedbackAction,
): StudentFeedbackCreate {
  if (!credentials.experimentSessionId) {
    throw new FeedbackRequestError('反馈需要实验会话，请重新登录。')
  }
  const key = storageKey(credentials, diagnosisId)
  try {
    const raw = sessionStorage.getItem(key)
    if (raw) {
      const pending = JSON.parse(raw) as Partial<StudentFeedbackCreate>
      if (
        !pending.request_id ||
        !UUID_PATTERN.test(pending.request_id) ||
        !pending.action ||
        !ACTIONS.includes(pending.action)
      ) {
        throw new FeedbackRequestError('未决反馈记录无法读取，请联系教师核对提交状态。')
      }
      if (pending.action !== action) {
        throw new FeedbackRequestError(
          `上一条“${ACTION_LABELS[pending.action]}”反馈的提交结果尚未确认，请先点击原反馈重试。`,
        )
      }
      return { request_id: pending.request_id, action: pending.action }
    }
    const pending = { request_id: newRequestId(), action }
    sessionStorage.setItem(key, JSON.stringify(pending))
    return pending
  } catch (error) {
    if (error instanceof FeedbackRequestError) throw error
    throw new FeedbackRequestError('浏览器无法保存反馈重试记录，请恢复浏览器存储后再提交。')
  }
}

export function completeFeedbackRequest(credentials: DeviceCredentials, diagnosisId: string): void {
  sessionStorage.removeItem(storageKey(credentials, diagnosisId))
}
