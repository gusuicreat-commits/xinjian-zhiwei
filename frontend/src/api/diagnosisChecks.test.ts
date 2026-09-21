import { beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from './client'
import { latestCheck, pendingCheck, submitCheck } from './diagnosisChecks'
vi.mock('./client', () => ({ apiClient: { post: vi.fn(), get: vi.fn() } }))
const c = { deviceId: 'device', token: 'token', experimentSessionId: 'session-a' }
beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  vi.mocked(apiClient.get).mockResolvedValue({ data: null })
})
it('keeps the original identity and baseline across a lost response and refresh', async () => {
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('network'))
  await expect(submitCheck(c, {}, 'old')).rejects.toThrow('尚未确认')
  const first = pendingCheck(c)
  expect(first?.baseline_id).toBe('old')
  await latestCheck(c, {})
  expect(apiClient.post).toHaveBeenCalledTimes(1)
  vi.mocked(apiClient.post).mockResolvedValueOnce({ data: {} })
  await submitCheck(c, {}, 'new')
  expect(vi.mocked(apiClient.post).mock.calls[1]?.[1]).toEqual(first)
  expect(pendingCheck(c)).toBeNull()
})
it('only discovers an unfinished server command until explicit confirmation', async () => {
  const payload = { request_id: '11111111-1111-4111-8111-111111111111', baseline_id: 'original' }
  vi.mocked(apiClient.get).mockResolvedValue({
    data: { status: 'pending', request_payload: payload },
  })
  await expect(submitCheck(c, {}, 'new')).rejects.toThrow('确认上次检查结果')
  expect(apiClient.post).not.toHaveBeenCalled()
  expect(pendingCheck({ ...c, experimentSessionId: 'session-b' })).toBeNull()
  vi.mocked(apiClient.post).mockResolvedValue({ data: {} })
  await submitCheck(c, {})
  expect(vi.mocked(apiClient.post).mock.calls[0]?.[1]).toEqual(payload)
})
it.each([401, 403, 409, 422])(
  'never automatically retries a rejected %i command',
  async (status) => {
    vi.mocked(apiClient.post).mockRejectedValue({ isAxiosError: true, response: { status } })
    await expect(submitCheck(c, {})).rejects.toMatchObject({
      action: status === 401 || status === 403 ? 'login' : status === 409 ? 'refresh' : 'review',
    })
    expect(apiClient.post).toHaveBeenCalledTimes(1)
    expect(pendingCheck(c)).toBeNull()
  },
)

it('does not offer resend or create a new command when status lookup failed before POST', async () => {
  vi.mocked(apiClient.get).mockRejectedValue(new Error('offline'))
  await expect(submitCheck(c, {})).rejects.toMatchObject({ action: 'retry' })
  expect(apiClient.post).not.toHaveBeenCalled()
  expect(pendingCheck(c)).toBeNull()
})
it('an unknown submission keeps its identity and offers confirmation, not a new operation', async () => {
  vi.mocked(apiClient.post).mockRejectedValue(new Error('lost response'))
  await expect(submitCheck(c, {})).rejects.toMatchObject({ action: 'confirm' })
  expect(pendingCheck(c)?.request_id).toBeTruthy()
})
