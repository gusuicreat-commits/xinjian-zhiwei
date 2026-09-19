import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createStudentSession } from '@/api/student'
import { useStudentSessionStore } from './studentSession'

vi.mock('@/api/student', () => ({
  createStudentSession: vi.fn(),
  getStudentExperimentSessions: vi.fn(),
  getStudentAssignments: vi.fn(),
  startStudentExperiment: vi.fn(),
  endStudentExperiment: vi.fn(),
}))

beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  setActivePinia(createPinia())
})

it('a response arriving after logout cannot restore student credentials', async () => {
  let finish!: (value: Awaited<ReturnType<typeof createStudentSession>>) => void
  vi.mocked(createStudentSession).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve
    }),
  )
  const store = useStudentSessionStore()
  const pending = store.login({ deviceId: 'a', deviceToken: '', accessToken: 'account' })
  store.logout()
  finish({
    device_id: 'a',
    display_name: 'A',
    auth_mode: 'student_account',
    student_user_id: 'student-a',
    experiment_session_id: 'session-a',
    experiment_assignment_id: 'task-a',
    notice: 'test',
  })
  await pending
  expect(store.isAuthenticated).toBe(false)
  expect(sessionStorage.getItem('xinjian-student-device-session')).toBeNull()
})

it('restores an account session without requiring the device secret', async () => {
  sessionStorage.setItem(
    'xinjian-student-device-session',
    JSON.stringify({
      deviceId: 'a',
      deviceToken: '',
      accessToken: 'account',
      experimentSessionId: 'session-a',
    }),
  )
  const store = useStudentSessionStore()
  expect(store.isAuthenticated).toBe(true)
  expect(store.credentials?.accessToken).toBe('account')
})
