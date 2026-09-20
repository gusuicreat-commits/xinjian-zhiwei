import { beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from './client'
import {
  authorizedPendingReleases,
  pendingReleases,
  releaseManagedSession,
  type ManagedSession,
} from './sessionManagement'
vi.mock('./client', () => ({ apiClient: { post: vi.fn(), get: vi.fn() } }))
const session: ManagedSession = {
  id: 'old',
  device_id: 'device',
  display_name: 'Device',
  student_name: 'A',
  class_name: 'Class',
  assignment_title: 'Task',
  started_at: '2026-09-20',
  status: 'active',
  version_no: 1,
  is_test_data: true,
}
beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  sessionStorage.setItem(
    'xinjian-teacher-session',
    JSON.stringify({ user_id: 'teacher', access_token: 'token' }),
  )
})
it('lost response retains original target and version even after refreshed state', async () => {
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('network'))
  await expect(releaseManagedSession('token', 'teacher', session, '交接')).rejects.toThrow(
    'network',
  )
  const original = pendingReleases('teacher')[0]!
  vi.mocked(apiClient.post).mockResolvedValueOnce({ data: {} })
  await releaseManagedSession('token', 'teacher', { ...session, version_no: 2 }, '交接')
  expect(vi.mocked(apiClient.post).mock.calls[1]?.[1]).toEqual(original.payload)
  expect(pendingReleases('teacher')).toEqual([])
})
it('changed reason and different actor cannot reuse pending operation', async () => {
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('network'))
  await expect(releaseManagedSession('token', 'teacher', session, '交接')).rejects.toThrow()
  await expect(releaseManagedSession('token', 'teacher', session, '其他')).rejects.toThrow('原操作')
  await expect(releaseManagedSession('token', 'other', session, '交接')).rejects.toThrow('登录')
  expect(apiClient.post).toHaveBeenCalledTimes(1)
})
it('409 removes rejected command and never generates an automatic retry', async () => {
  vi.mocked(apiClient.post).mockRejectedValueOnce({ isAxiosError: true, response: { status: 409 } })
  await expect(releaseManagedSession('token', 'teacher', session, '交接')).rejects.toBeTruthy()
  expect(apiClient.post).toHaveBeenCalledTimes(1)
  expect(pendingReleases('teacher')).toEqual([])
})

it('pending entries from a revoked class are not returned for display', async () => {
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('network'))
  await expect(releaseManagedSession('token', 'teacher', session, '交接')).rejects.toThrow()
  vi.mocked(apiClient.get).mockRejectedValueOnce({ isAxiosError: true, response: { status: 403 } })
  expect(await authorizedPendingReleases('token', 'teacher')).toEqual([])
  expect(apiClient.post).toHaveBeenCalledTimes(1)
})
