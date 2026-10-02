import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { createTeacherSession } from '@/api/teacher'
import { useTeacherSessionStore } from './teacherSession'
import type { UserSession } from '@/types/auth'
vi.mock('@/api/auth', () => ({ revokeUserSession: vi.fn().mockResolvedValue(true) }))
vi.mock('@/api/teacher', async (original) => ({
  ...(await original<typeof import('@/api/teacher')>()),
  createTeacherSession: vi.fn(),
}))
beforeEach(() => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  vi.resetAllMocks()
})
it('logout invalidates an unfinished login and switching accounts clears old authorization', async () => {
  let resolve!: (value: UserSession) => void
  vi.mocked(createTeacherSession).mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done
      }),
  )
  const store = useTeacherSessionStore()
  store.session = { access_token: 'old-token' } as UserSession
  const login = store.login('new', 'synthetic')
  expect(store.accessToken).toBeNull()
  store.logout()
  resolve({ access_token: 'late-token' } as UserSession)
  await login
  expect(store.accessToken).toBeNull()
  expect(sessionStorage.getItem('xinjian-teacher-session')).toBeNull()
})
