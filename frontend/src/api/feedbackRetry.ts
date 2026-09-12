import type {
  DeviceCredentials,
  FeedbackAction,
  FeedbackRecoveryTarget,
  StudentFeedbackCreate,
} from '@/types/student'

const STORAGE_PREFIX = 'xinjian-pending-feedback:'
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const ACTIONS: FeedbackAction[] = ['resolved', 'unresolved', 'request_teacher_help']
export const FEEDBACK_ACTION_LABELS: Record<FeedbackAction, string> = {
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

function parseRequest(raw: string): StudentFeedbackCreate {
  const pending = JSON.parse(raw) as Partial<StudentFeedbackCreate>
  if (
    !pending.request_id ||
    !UUID_PATTERN.test(pending.request_id) ||
    !pending.action ||
    !ACTIONS.includes(pending.action) ||
    (pending.note !== undefined && pending.note !== null && typeof pending.note !== 'string')
  ) {
    throw new FeedbackRequestError('未决反馈记录无法读取，请联系教师核对提交状态。')
  }
  return { request_id: pending.request_id, action: pending.action, note: pending.note ?? null }
}

export function sameFeedbackPayload(a: StudentFeedbackCreate, b: StudentFeedbackCreate): boolean {
  return (
    a.request_id === b.request_id && a.action === b.action && (a.note ?? null) === (b.note ?? null)
  )
}

export function listLocalFeedbackRequests(
  credentials: DeviceCredentials,
): FeedbackRecoveryTarget[] {
  try {
    const pending: FeedbackRecoveryTarget[] = []
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index)
      if (!key?.startsWith(STORAGE_PREFIX)) continue
      const scope = JSON.parse(key.slice(STORAGE_PREFIX.length)) as string[]
      if (scope[0] !== credentials.deviceId || scope[1] !== credentials.experimentSessionId)
        continue
      if (!scope[2]) throw new FeedbackRequestError('未决反馈记录缺少诊断信息，请联系教师核对。')
      const raw = sessionStorage.getItem(key)
      if (raw)
        pending.push({
          diagnosis_result_id: scope[2],
          payload: parseRequest(raw),
          source: 'browser',
        })
    }
    return pending
  } catch (error) {
    if (error instanceof FeedbackRequestError) throw error
    throw new FeedbackRequestError('本页反馈记录无法读取；已保存到服务器的反馈仍可继续确认。')
  }
}

export function getOrCreateFeedbackRequest(
  credentials: DeviceCredentials,
  diagnosisId: string,
  action: FeedbackAction,
  note: string | null = null,
): StudentFeedbackCreate {
  if (!credentials.experimentSessionId) {
    throw new FeedbackRequestError('反馈需要实验会话，请重新登录。')
  }
  const key = storageKey(credentials, diagnosisId)
  try {
    const raw = sessionStorage.getItem(key)
    if (raw) {
      const pending = parseRequest(raw)
      if (pending.action !== action || pending.note !== note) {
        throw new FeedbackRequestError(
          `上一条“${FEEDBACK_ACTION_LABELS[pending.action]}”反馈的提交结果尚未确认，请先点击原反馈重试。`,
        )
      }
      return pending
    }
    const pending = { request_id: newRequestId(), action, note }
    sessionStorage.setItem(key, JSON.stringify(pending))
    return pending
  } catch (error) {
    if (error instanceof FeedbackRequestError) throw error
    throw new FeedbackRequestError('浏览器无法保存反馈重试记录，请恢复浏览器存储后再提交。')
  }
}

export function completeFeedbackRequest(
  credentials: DeviceCredentials,
  diagnosisId: string,
  expected: StudentFeedbackCreate,
): void {
  const key = storageKey(credentials, diagnosisId)
  const raw = sessionStorage.getItem(key)
  // A late response must never erase another locally prepared request.
  if (raw && sameFeedbackPayload(parseRequest(raw), expected)) sessionStorage.removeItem(key)
}
