import {
  assertCommandRecoverable,
  recordCommandFailure,
  completeCommand,
  commandOutcome,
} from './commandOutcome'
import { apiClient } from './client'
import { newRequestId, feedbackSessionScope } from './feedbackRetry'
import type { DeviceCredentials, DiagnosisWorkflow } from '@/types/student'

export interface CheckPayload {
  request_id: string
  baseline_id?: string | null
  target_episode_id?: string | null
  [key: string]: unknown
}
export interface CheckReceipt {
  request_id: string
  status: 'pending' | 'completed' | 'no_new_data'
  checked_at: string
  diagnosis_result_id?: string
  new_records?: number
  data_change?: 'none' | 'new_records' | 'monitoring_only'
  data_window?: { earliest: string | null; latest: string | null }
  time_notice?: string
  issues?: Array<{
    episode_id: string
    error_type: string
    label?: string
    scope?: { kind: string; keys: string[] }
    observation: string
    handling_status: string
    new_records?: number
  }>
  request_payload?: CheckPayload | null
}
export type CheckRecoveryAction = 'login' | 'refresh' | 'confirm' | 'review' | 'retry'
export class CheckRequestError extends Error {
  constructor(
    message: string,
    public action: CheckRecoveryAction,
  ) {
    super(message)
  }
}
function rejectedRequest(status: number): CheckRequestError {
  if (status === 401)
    return new CheckRequestError('登录已失效，请重新登录后查看检查结果。', 'login')
  if (status === 403)
    return new CheckRequestError(
      '实验资格或访问权限已变化，请重新登录并选择有权使用的实验。',
      'login',
    )
  if (status === 409)
    return new CheckRequestError(
      '实验会话或记录已变化，请先刷新状态查看最新结果；不会自动重新提交。',
      'refresh',
    )
  return new CheckRequestError(
    '检查参数未被接受，请刷新状态核对当前实验；仍有问题时联系教师。',
    'review',
  )
}
const key = (c: DeviceCredentials) => `xinjian-pending-check:${feedbackSessionScope(c)}`
export function pendingCheck(c: DeviceCredentials): CheckPayload | null {
  const raw = sessionStorage.getItem(key(c))
  if (!raw) return null
  const value = JSON.parse(raw) as CheckPayload
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.request_id))
    throw new Error('检查请求记录损坏，请核对服务端状态')
  return value
}
export async function latestCheck(
  c: DeviceCredentials,
  headers: Record<string, string>,
): Promise<CheckReceipt | null> {
  return (
    await apiClient.get<CheckReceipt | null>(
      `/api/v1/diagnosis-workflows/devices/${encodeURIComponent(c.deviceId)}/checks/latest`,
      { headers },
    )
  ).data
}
export async function submitCheck(
  c: DeviceCredentials,
  headers: Record<string, string>,
  baselineId?: string | null,
): Promise<DiagnosisWorkflow> {
  if (!c.experimentSessionId) throw new Error('请先连接有效实验会话')
  const identity = sessionStorage.getItem('xinjian-student-device-session')
  const assertCurrent = () => {
    if (sessionStorage.getItem('xinjian-student-device-session') !== identity)
      throw new CheckRequestError('实验会话已变化，请重新登录。', 'login')
  }
  const recoveryRaw = sessionStorage.getItem(`${key(c)}:recovery`)
  if (recoveryRaw) {
    const bookmark = JSON.parse(recoveryRaw) as { request_id: string }
    const receipt = await latestCheck(c, headers)
    assertCurrent()
    if (receipt?.request_id === bookmark.request_id && receipt.status !== 'pending') {
      const response = await apiClient.get<DiagnosisWorkflow | null>(
        `/api/v1/diagnosis-workflows/devices/${encodeURIComponent(c.deviceId)}/latest`,
        { headers },
      )
      assertCurrent()
      if (sessionStorage.getItem(`${key(c)}:recovery`) !== recoveryRaw)
        throw new CheckRequestError('恢复记录已变化，请重新查询。', 'refresh')
      if (response.data) {
        completeCommand(key(c), bookmark.request_id)
        return response.data
      }
    }
  }
  assertCommandRecoverable(key(c))
  let payload = pendingCheck(c)
  if (!payload) {
    let server: CheckReceipt | null
    try {
      server = await latestCheck(c, headers)
      assertCurrent()
    } catch (error) {
      const outcome = commandOutcome('submitCheck', error)
      if (!outcome.retainPayload) throw rejectedRequest(outcome.status!)
      throw new CheckRequestError(
        '暂时无法查询上次检查状态，本次尚未提交。请恢复网络后重新查询。',
        'retry',
      )
    }
    if (server?.status === 'pending' && server.request_payload) {
      sessionStorage.setItem(key(c), JSON.stringify(server.request_payload))
      throw new CheckRequestError(
        '找到上次未完成检查，请点击“确认上次检查结果”继续原请求',
        'confirm',
      )
    }
    payload = { request_id: newRequestId(), baseline_id: baselineId ?? null }
    sessionStorage.setItem(key(c), JSON.stringify(payload))
  }
  try {
    const response = await apiClient.post<DiagnosisWorkflow>(
      `/api/v1/diagnosis-workflows/devices/${encodeURIComponent(c.deviceId)}`,
      payload,
      { headers },
    )
    assertCurrent()
    completeCommand(key(c), payload.request_id)
    return response.data
  } catch (error) {
    assertCurrent()
    recordCommandFailure(key(c), 'submitCheck', payload.request_id, error)
    const outcome = commandOutcome('submitCheck', error)
    if (!outcome.retainPayload) throw rejectedRequest(outcome.status!)
    throw new CheckRequestError(
      '检查结果尚未确认，请点击“确认上次检查结果”沿用原请求重试',
      'confirm',
    )
  }
}
