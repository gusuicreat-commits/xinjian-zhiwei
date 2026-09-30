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

vi.mock('@/api/auth', () => ({ createUserSession: vi.fn() }))

it('a definitive forbidden start permits another authorized task', async () => {
  const { createUserSession } = await import('@/api/auth')
  const { getStudentAssignments, getStudentExperimentSessions, startStudentExperiment } =
    await import('@/api/student')
  vi.mocked(createUserSession).mockResolvedValue({
    access_token: 'account',
    token_type: 'bearer',
    expires_at: '2099-01-01',
    user_id: 'student',
    username: 'student',
    display_name: 'Student',
    roles: ['student'],
    permissions: [],
    is_test_data: true,
  })
  vi.mocked(getStudentExperimentSessions).mockResolvedValue([])
  vi.mocked(getStudentAssignments).mockResolvedValue([
    { id: 'b', title: 'B', is_test_data: true, devices: [{ id: 'b', name: 'B' }] },
  ])
  vi.mocked(startStudentExperiment).mockRejectedValue({
    isAxiosError: true,
    response: { status: 403 },
  })
  const store = useStudentSessionStore()
  await store.authenticateAccount('student', 'password')
  await expect(store.beginExperiment('a', 'a')).rejects.toThrow()
  expect(sessionStorage.getItem('xinjian-start-session:student')).toBeNull()
  await expect(store.beginExperiment('b', 'b')).rejects.toThrow()
  expect(startStudentExperiment).toHaveBeenCalledTimes(2)
  expect(vi.mocked(startStudentExperiment).mock.calls[1]![1].device_id).toBe('b')
})

async function authenticatedStore() {
  const { createUserSession } = await import('@/api/auth')
  const { getStudentAssignments, getStudentExperimentSessions } = await import('@/api/student')
  vi.mocked(createUserSession).mockResolvedValue({
    access_token: 'account',
    token_type: 'bearer',
    expires_at: '2099-01-01',
    user_id: 'student',
    username: 'student',
    display_name: 'Student',
    roles: ['student'],
    permissions: [],
    is_test_data: true,
  })
  vi.mocked(getStudentExperimentSessions).mockResolvedValue([])
  vi.mocked(getStudentAssignments).mockResolvedValue([])
  const store = useStudentSessionStore()
  await store.authenticateAccount('student', 'password')
  return store
}

it.each([401, 422])('a definitive %i start releases the pending command', async (status) => {
  const { startStudentExperiment } = await import('@/api/student')
  const store = await authenticatedStore()
  vi.mocked(startStudentExperiment).mockRejectedValue({ isAxiosError: true, response: { status } })
  await expect(store.beginExperiment('a', 'a')).rejects.toThrow()
  expect(sessionStorage.getItem('xinjian-start-session:student')).toBeNull()
  if (status === 401) {
    await expect(store.beginExperiment('a', 'a')).rejects.toThrow('account required')
    expect(startStudentExperiment).toHaveBeenCalledTimes(1)
  }
})

it.each([undefined, 503])(
  'an uncertain %s start preserves its identity across retries',
  async (status) => {
    const { startStudentExperiment } = await import('@/api/student')
    const store = await authenticatedStore()
    vi.mocked(startStudentExperiment).mockRejectedValue({
      isAxiosError: true,
      response: { status },
    })
    await expect(store.beginExperiment('a', 'a')).rejects.toThrow()
    const pending = sessionStorage.getItem('xinjian-start-session:student')
    expect(pending).not.toBeNull()
    await expect(store.beginExperiment('b', 'b')).rejects.toThrow('上次开始实验')
    expect(startStudentExperiment).toHaveBeenCalledTimes(1)
    await expect(store.beginExperiment('a', 'a')).rejects.toThrow()
    expect(vi.mocked(startStudentExperiment).mock.calls[1]![1]).toEqual(JSON.parse(pending!))
  },
)

it('a permissions refresh arriving after logout cannot restore authorized tasks', async () => {
  const { getStudentAssignments, startStudentExperiment } = await import('@/api/student')
  const store = await authenticatedStore()
  let finish!: (tasks: Awaited<ReturnType<typeof getStudentAssignments>>) => void
  vi.mocked(getStudentAssignments).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve
    }),
  )
  vi.mocked(startStudentExperiment).mockRejectedValue({
    isAxiosError: true,
    response: { status: 403 },
  })
  const pending = store.beginExperiment('a', 'a')
  await vi.waitFor(() => expect(getStudentAssignments).toHaveBeenCalledTimes(2))
  store.logout()
  finish([{ id: 'b', title: 'B', is_test_data: true, devices: [{ id: 'b', name: 'B' }] }])
  await pending
  expect(store.assignments).toEqual([])
  expect(store.availableSessions).toEqual([])
  expect(store.isAuthenticated).toBe(false)
})

it.each([401, 403, 422])(
  'clears rejected end command %s and drops revoked credentials',
  async (status) => {
    const { endStudentExperiment } = await import('@/api/student')
    sessionStorage.setItem(
      'xinjian-student-device-session',
      JSON.stringify({
        deviceId: 'a',
        deviceToken: '',
        accessToken: 'account',
        experimentSessionId: 'session-a',
      }),
    )
    sessionStorage.setItem(
      'xinjian-end-session:session-a',
      JSON.stringify({ requestId: 'request', version: 1 }),
    )
    vi.mocked(endStudentExperiment).mockRejectedValue({ isAxiosError: true, response: { status } })
    const store = useStudentSessionStore()
    await expect(store.finishExperiment()).rejects.toThrow()
    expect(sessionStorage.getItem('xinjian-end-session:session-a')).toBeNull()
    if (status !== 422) expect(store.credentials).toBeNull()
  },
)

vi.mock('@/api/client', () => ({ apiClient: { get: vi.fn() } }))
it('a delayed end receipt cannot log out a new account or erase its replacement bookmark', async () => {
  const { apiClient } = await import('@/api/client')
  sessionStorage.setItem(
    'xinjian-student-device-session',
    JSON.stringify({
      deviceId: 'a',
      deviceToken: '',
      accessToken: 'old-account',
      experimentSessionId: 'session-a',
    }),
  )
  const key = 'xinjian-end-session:session-a:recovery'
  sessionStorage.setItem(key, JSON.stringify({ request_id: 'old-request' }))
  let resolve!: (value: unknown) => void
  vi.mocked(apiClient.get).mockReturnValue(
    new Promise((done) => {
      resolve = done
    }) as never,
  )
  const store = useStudentSessionStore()
  const pending = store.finishExperiment()
  await vi.waitFor(() => expect(apiClient.get).toHaveBeenCalled())
  store.logout()
  vi.mocked(createStudentSession).mockResolvedValue({
    device_id: 'b',
    experiment_session_id: 'session-b',
  } as never)
  await store.login({ deviceId: 'b', deviceToken: '', accessToken: 'new-account' })
  sessionStorage.setItem(key, JSON.stringify({ request_id: 'replacement' }))
  resolve({ data: { status: 'applied', result: { id: 'session-a', status: 'ended' } } })
  await pending
  expect(store.credentials?.accessToken).toBe('new-account')
  expect(store.credentials?.experimentSessionId).toBe('session-b')
  expect(JSON.parse(sessionStorage.getItem(key)!)).toEqual({ request_id: 'replacement' })
})
