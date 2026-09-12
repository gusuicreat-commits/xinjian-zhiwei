import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createDiagnosisFeedback,
  getLatestDiagnosisWorkflow,
  getStudentDashboard,
} from '@/api/student'
import { reviewStudentDashboard } from '@/review/fixtures'
import type { DeviceCredentials, StudentFeedback } from '@/types/student'

import { useStudentDashboardStore } from './studentDashboard'

vi.mock('@/api/student', () => ({
  createDiagnosisFeedback: vi.fn(),
  getLatestDiagnosisWorkflow: vi.fn(),
  getStudentDashboard: vi.fn(),
  requestAIExplanation: vi.fn(),
  startDiagnosisWorkflow: vi.fn(),
}))

const credentials: DeviceCredentials = {
  deviceId: 'feedback-device',
  deviceToken: 'explicit-test-device-token',
  experimentSessionId: 'student-session-a',
}
const feedback: StudentFeedback = {
  id: 'feedback-a',
  action: 'unresolved',
  note: null,
  is_test_data: true,
  created_at: '2026-09-12T09:00:00Z',
}

function httpError(status: number) {
  return { isAxiosError: true, response: { status } }
}

async function loadedStore(scope = credentials) {
  const store = useStudentDashboardStore()
  await store.load(scope)
  return store
}

describe('student feedback submission boundaries', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.resetAllMocks()
    vi.mocked(getStudentDashboard).mockImplementation(async () =>
      structuredClone(reviewStudentDashboard),
    )
    vi.mocked(getLatestDiagnosisWorkflow).mockResolvedValue(null)
    vi.mocked(createDiagnosisFeedback).mockResolvedValue(feedback)
  })

  it('retries a 503 with the same payload, then gives a deliberate new feedback a new ID', async () => {
    vi.mocked(createDiagnosisFeedback).mockRejectedValueOnce(httpError(503))
    const store = await loadedStore()
    await store.submitFeedback(credentials, 'unresolved')
    const first = vi.mocked(createDiagnosisFeedback).mock.calls[0]![2]
    const retry = vi.mocked(createDiagnosisFeedback).mock.calls[1]![2]
    expect(first.request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(retry).toEqual(first)
    expect(sessionStorage.length).toBe(0)

    await store.submitFeedback(credentials, 'unresolved')
    expect(vi.mocked(createDiagnosisFeedback).mock.calls[2]![2].request_id).not.toBe(
      first.request_id,
    )
  })

  it('keeps an uncertain request through a store restart and never persists credentials', async () => {
    vi.mocked(createDiagnosisFeedback).mockRejectedValueOnce(new Error('response lost'))
    const store = await loadedStore()
    await expect(store.submitFeedback(credentials, 'unresolved')).rejects.toThrow('尚未确认')
    const pending = vi.mocked(createDiagnosisFeedback).mock.calls[0]![2]
    expect(sessionStorage.length).toBe(1)
    const saved = sessionStorage.getItem(sessionStorage.key(0)!)!
    expect(JSON.parse(saved)).toEqual(pending)
    expect(saved).not.toContain(credentials.deviceToken)
    expect(sessionStorage.key(0)).not.toContain(credentials.deviceToken)

    setActivePinia(createPinia()) // Browser reload creates a fresh store, sessionStorage survives.
    const restored = await loadedStore()
    await restored.submitFeedback(credentials, 'unresolved')
    expect(vi.mocked(createDiagnosisFeedback).mock.calls[1]![2]).toEqual(pending)
  })

  it('blocks a changed action until the uncertain original feedback has been retried', async () => {
    vi.mocked(createDiagnosisFeedback).mockRejectedValueOnce(new Error('response lost'))
    const store = await loadedStore()
    await expect(store.submitFeedback(credentials, 'unresolved')).rejects.toThrow()
    await expect(store.submitFeedback(credentials, 'resolved')).rejects.toThrow('先点击原反馈重试')
    expect(createDiagnosisFeedback).toHaveBeenCalledTimes(1)
  })

  it('does not create another request for a concurrent click', async () => {
    let finish!: (value: StudentFeedback) => void
    vi.mocked(createDiagnosisFeedback).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const store = await loadedStore()
    const first = store.submitFeedback(credentials, 'unresolved')
    expect(await store.submitFeedback(credentials, 'resolved')).toBe(false)
    expect(createDiagnosisFeedback).toHaveBeenCalledTimes(1)
    finish(feedback)
    expect(await first).toBe(true)
  })

  it('isolates pending feedback by experiment session and diagnosis', async () => {
    vi.mocked(createDiagnosisFeedback).mockRejectedValue(new Error('response lost'))
    const store = await loadedStore()
    await expect(store.submitFeedback(credentials, 'unresolved')).rejects.toThrow()

    const other = { ...credentials, experimentSessionId: 'student-session-b' }
    await store.load(other)
    await expect(store.submitFeedback(other, 'resolved')).rejects.toThrow('尚未确认')
    const nextDashboard = structuredClone(reviewStudentDashboard)
    nextDashboard.diagnosis!.id = 'different-diagnosis'
    vi.mocked(getStudentDashboard).mockResolvedValue(nextDashboard)
    await store.load(other)
    await expect(store.submitFeedback(other, 'unresolved')).rejects.toThrow('尚未确认')

    const requests = vi.mocked(createDiagnosisFeedback).mock.calls.map((call) => call[2].request_id)
    expect(new Set(requests).size).toBe(3)
    expect(sessionStorage.length).toBe(3)
  })

  it('rejects missing session credentials before sending or saving a request', async () => {
    const missing = { ...credentials, experimentSessionId: undefined }
    const store = await loadedStore(missing)
    await expect(store.submitFeedback(missing, 'unresolved')).rejects.toThrow('需要实验会话')
    expect(createDiagnosisFeedback).not.toHaveBeenCalled()
    expect(sessionStorage.length).toBe(0)
  })

  it.each([400, 401, 403, 404, 422])(
    'clears a request definitively rejected with %i',
    async (status) => {
      vi.mocked(createDiagnosisFeedback).mockRejectedValueOnce(httpError(status))
      const store = await loadedStore()
      await expect(store.submitFeedback(credentials, 'unresolved')).rejects.toThrow('已被拒绝')
      expect(sessionStorage.length).toBe(0)
    },
  )

  it('preserves a 409 request for resolution instead of creating a fresh submission', async () => {
    vi.mocked(createDiagnosisFeedback).mockRejectedValueOnce(httpError(409))
    const store = await loadedStore()
    await expect(store.submitFeedback(credentials, 'unresolved')).rejects.toThrow('尚未确认')
    const original = vi.mocked(createDiagnosisFeedback).mock.calls[0]![2]
    await store.submitFeedback(credentials, 'unresolved')
    expect(vi.mocked(createDiagnosisFeedback).mock.calls[1]![2]).toEqual(original)
  })

  it('does not put a late feedback response into another session dashboard', async () => {
    let finish!: (value: StudentFeedback) => void
    vi.mocked(createDiagnosisFeedback).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const store = await loadedStore()
    const first = store.submitFeedback(credentials, 'unresolved')
    const other = { ...credentials, experimentSessionId: 'student-session-b' }
    await store.load(other)
    finish(feedback)
    await first
    expect(store.dashboard?.feedback).toBeNull()
    expect(getStudentDashboard).toHaveBeenCalledTimes(2)
  })
})
