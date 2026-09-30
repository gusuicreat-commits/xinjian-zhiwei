import { beforeEach, expect, it, vi } from 'vitest'
import { commandOutcome, recordCommandFailure, assertCommandRecoverable } from './commandOutcome'
import { actOnTeacherIntervention } from './teacher'
import { apiClient } from './client'
vi.mock('./client', () => ({ apiClient: { post: vi.fn(), get: vi.fn() } }))
const failure = (status: number) => ({ isAxiosError: true, response: { status } })
beforeEach(() => {
  sessionStorage.clear()
  vi.resetAllMocks()
})
it.each([401, 403, 422, 409, 429])(
  'releases definitively rejected intervention payload: %s',
  async (status) => {
    sessionStorage.setItem(
      'xinjian-teacher-session',
      JSON.stringify({ user_id: 'teacher', access_token: 'token' }),
    )
    vi.mocked(apiClient.post).mockRejectedValue(failure(status))
    await expect(
      actOnTeacherIntervention('token', 'case', {
        action: 'claim',
        expected_version: 1,
        note: 'private note',
        is_private: true,
      }),
    ).rejects.toBeDefined()
    expect(sessionStorage.getItem('xinjian-intervention:teacher:case')).toBeNull()
    expect(sessionStorage.getItem('xinjian-intervention:teacher:case:recovery')).toBeNull()
  },
)
it('keeps minimal same-account recovery identity after timeout then revoked access', async () => {
  sessionStorage.setItem(
    'xinjian-teacher-session',
    JSON.stringify({ user_id: 'teacher', access_token: 'token' }),
  )
  const payload = {
    action: 'claim' as const,
    expected_version: 1,
    note: 'private note',
    is_private: true,
  }
  vi.mocked(apiClient.post)
    .mockRejectedValueOnce({ isAxiosError: true })
    .mockRejectedValueOnce(failure(403))
  await expect(actOnTeacherIntervention('token', 'case', payload)).rejects.toBeDefined()
  const original = JSON.parse(sessionStorage.getItem('xinjian-intervention:teacher:case')!)
  await expect(actOnTeacherIntervention('token', 'case', payload)).rejects.toBeDefined()
  const bookmark = sessionStorage.getItem('xinjian-intervention:teacher:case:recovery')!
  expect(JSON.parse(bookmark).request_id).toBe(original.request_id)
  expect(bookmark).not.toContain('private note')
  expect(bookmark).not.toContain('token')
  vi.mocked(apiClient.get).mockResolvedValueOnce({ data: [] })
  await expect(actOnTeacherIntervention('token', 'case', payload)).rejects.toThrow('此前操作')
  vi.mocked(apiClient.get).mockResolvedValueOnce({
    data: [{ actor_user_id: 'teacher', metadata: { request_id: original.request_id } }],
  })
  await actOnTeacherIntervention('token', 'case', payload)
  expect(sessionStorage.getItem('xinjian-intervention:teacher:case:recovery')).toBeNull()
  expect(apiClient.post).toHaveBeenCalledTimes(2)
})
it('keeps feedback conflict distinct from session version conflict', () => {
  expect(commandOutcome('sendFeedback', failure(409)).retainPayload).toBe(true)
  expect(commandOutcome('finishExperiment', failure(409)).retainPayload).toBe(false)
})
it('retains uncertainty through subsequent validation refusal', () => {
  recordCommandFailure('command', 'finishExperiment', 'request', { isAxiosError: true })
  recordCommandFailure('command', 'finishExperiment', 'request', failure(422))
  expect(() => assertCommandRecoverable('command')).toThrow('此前操作')
})

it('recovers a session command only from an authorized positive receipt without another POST', async () => {
  const { recoverSessionCommand } = await import('./commandOutcome')
  const key = 'xinjian-end-session:session'
  sessionStorage.setItem(
    `${key}:recovery`,
    JSON.stringify({ operation: 'finishExperiment', request_id: 'original-request' }),
  )
  vi.mocked(apiClient.get).mockRejectedValueOnce(failure(404))
  await expect(recoverSessionCommand(key, 'token', () => true)).rejects.toThrow(
    '核查编号：original-request',
  )
  expect(sessionStorage.getItem(`${key}:recovery`)).not.toBeNull()
  vi.mocked(apiClient.get).mockRejectedValueOnce(failure(403))
  await expect(recoverSessionCommand(key, 'token', () => true)).rejects.toBeDefined()
  expect(sessionStorage.getItem(`${key}:recovery`)).not.toBeNull()
  vi.mocked(apiClient.get).mockResolvedValueOnce({
    data: { status: 'applied', result: { id: 'session', status: 'ended' } },
  })
  await expect(recoverSessionCommand(key, 'token', () => true)).resolves.toMatchObject({
    id: 'session',
    status: 'ended',
  })
  expect(sessionStorage.getItem(`${key}:recovery`)).toBeNull()
  expect(apiClient.get).toHaveBeenLastCalledWith(
    '/api/v1/student/experiment-session-commands/original-request',
    { headers: { Authorization: 'Bearer token' } },
  )
  expect(apiClient.post).not.toHaveBeenCalled()
})

it('a late receipt cannot clear a replacement bookmark for the same resource', async () => {
  const { recoverSessionCommand } = await import('./commandOutcome')
  const key = 'xinjian-end-session:session'
  sessionStorage.setItem(`${key}:recovery`, JSON.stringify({ request_id: 'old' }))
  let resolve!: (value: unknown) => void
  vi.mocked(apiClient.get).mockReturnValue(
    new Promise((done) => {
      resolve = done
    }) as never,
  )
  const pending = recoverSessionCommand(key, 'old-token', () => true)
  await vi.waitFor(() => expect(apiClient.get).toHaveBeenCalled())
  sessionStorage.setItem(`${key}:recovery`, JSON.stringify({ request_id: 'new' }))
  resolve({ data: { status: 'applied', result: { id: 'session' } } })
  await pending
  expect(JSON.parse(sessionStorage.getItem(`${key}:recovery`)!)).toEqual({ request_id: 'new' })
})
