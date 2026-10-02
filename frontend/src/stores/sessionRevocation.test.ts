import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { revokeUserSession } from '@/api/auth'
import { useTeacherSessionStore } from './teacherSession'
import { useStudentSessionStore } from './studentSession'
import type { UserSession } from '@/types/auth'
vi.mock('@/api/auth', () => ({ createUserSession: vi.fn(), revokeUserSession: vi.fn() }))
beforeEach(() => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  vi.resetAllMocks()
  vi.mocked(revokeUserSession).mockResolvedValue(true)
})
it('explicit teacher logout revokes captured token and clears immediately', async () => {
  const store = useTeacherSessionStore()
  store.session = { access_token: 'old-token' } as UserSession
  const pending = store.logout()
  expect(store.accessToken).toBeNull()
  await pending
  expect(revokeUserSession).toHaveBeenCalledWith('old-token')
})
it('student logout uses personal session, never the device secret', async () => {
  const store = useStudentSessionStore()
  store.credentials = { deviceId: 'a', deviceToken: 'secret-device', accessToken: 'account-token' }
  await store.logout()
  expect(revokeUserSession).toHaveBeenCalledWith('account-token')
  expect(store.credentials).toBeNull()
})
it('failed remote logout clears locally but does not claim confirmed logout', async () => {
  vi.mocked(revokeUserSession).mockResolvedValue(false)
  const store = useTeacherSessionStore()
  store.session = { access_token: 'old-token' } as UserSession
  await store.logout()
  expect(store.accessToken).toBeNull()
  expect(store.errorMessage).toContain('服务端退出未确认')
})
