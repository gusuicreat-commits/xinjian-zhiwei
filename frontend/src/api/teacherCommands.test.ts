import { beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from './client'
import { actOnTeacherIntervention, pendingInterventionCommand } from './teacher'

vi.mock('./client', () => ({ apiClient: { post: vi.fn(), get: vi.fn() } }))
const payload = { action: 'claim' as const, expected_version: 1, is_private: false }
beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  sessionStorage.setItem(
    'xinjian-teacher-session',
    JSON.stringify({ user_id: 'teacher-a', access_token: 'token-a' }),
  )
})
it('a lost response keeps the same command identity and blocks changed content', async () => {
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('network'))
  await expect(actOnTeacherIntervention('token-a', 'case-a', payload)).rejects.toThrow('network')
  const first = pendingInterventionCommand('teacher-a', 'case-a')
  expect(first?.request_id).toBeTruthy()
  await expect(
    actOnTeacherIntervention('token-a', 'case-a', { ...payload, action: 'close' }),
  ).rejects.toThrow('上次工单')
  expect(apiClient.post).toHaveBeenCalledTimes(1)
  vi.mocked(apiClient.post).mockResolvedValueOnce({ data: {} })
  await actOnTeacherIntervention('token-a', 'case-a', payload)
  expect(vi.mocked(apiClient.post).mock.calls[1]?.[1]).toMatchObject({
    request_id: first?.request_id,
  })
  expect(pendingInterventionCommand('teacher-a', 'case-a')).toBeNull()
})
it('a received conflict does not automatically retry, and another account cannot reuse local commands', async () => {
  vi.mocked(apiClient.post).mockRejectedValueOnce({ isAxiosError: true, response: { status: 409 } })
  await expect(actOnTeacherIntervention('token-a', 'case-a', payload)).rejects.toBeTruthy()
  expect(apiClient.post).toHaveBeenCalledTimes(1)
  expect(pendingInterventionCommand('teacher-a', 'case-a')).toBeNull()
  await expect(actOnTeacherIntervention('another-token', 'case-a', payload)).rejects.toThrow(
    'TEACHER_SESSION_REQUIRED',
  )
  expect(apiClient.post).toHaveBeenCalledTimes(1)
})

it('a delayed review recovery cannot return protected results or clear state after account change', async () => {
  const { reviewDiagnosisWorkflow } = await import('./teacher')
  const key = 'xinjian-workflow-review:teacher-a:workflow:recovery'
  sessionStorage.setItem(key, JSON.stringify({ workflow_id: 'workflow' }))
  let resolve!: (value: unknown) => void
  vi.mocked(apiClient.get).mockReturnValue(
    new Promise((done) => {
      resolve = done
    }) as never,
  )
  const recovery = reviewDiagnosisWorkflow('token-a', 'workflow', { action: 'approve' })
  sessionStorage.setItem(
    'xinjian-teacher-session',
    JSON.stringify({ user_id: 'teacher-b', access_token: 'token-b' }),
  )
  resolve({ data: { id: 'workflow', status: 'completed' } })
  await expect(recovery).rejects.toThrow('TEACHER_SESSION_REQUIRED')
  expect(sessionStorage.getItem(key)).not.toBeNull()
  expect(apiClient.post).not.toHaveBeenCalled()
})
