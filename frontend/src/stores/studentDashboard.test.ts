import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createDiagnosisFeedback,
  getFeedbackRecovery,
  getLatestDiagnosisWorkflow,
  getStudentDashboard,
  requestAIExplanation,
  startDiagnosisWorkflow,
} from '@/api/student'
import {
  reviewAIExplanation,
  reviewStudentDashboard,
  reviewStudentWorkflow,
} from '@/review/fixtures'
import type { DeviceCredentials, FeedbackRecoveryItem, StudentFeedback } from '@/types/student'

import { useStudentDashboardStore } from './studentDashboard'

vi.mock('@/api/student', () => ({
  createDiagnosisFeedback: vi.fn(),
  getFeedbackRecovery: vi.fn(),
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
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: null,
      has_more_pending: false,
    })
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
    await restored.recoverFeedback(credentials, restored.pendingFeedback[0]!)
    expect(vi.mocked(createDiagnosisFeedback).mock.calls[1]![2]).toEqual(pending)
  })

  it('blocks a changed action until the uncertain original feedback has been retried', async () => {
    vi.mocked(createDiagnosisFeedback).mockRejectedValueOnce(new Error('response lost'))
    const store = await loadedStore()
    await expect(store.submitFeedback(credentials, 'unresolved')).rejects.toThrow()
    await expect(store.submitFeedback(credentials, 'resolved')).rejects.toThrow('继续确认原反馈')
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
    await vi.waitFor(() => expect(createDiagnosisFeedback).toHaveBeenCalledTimes(1))
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
    await expect(store.submitFeedback(other, 'unresolved')).rejects.toThrow('继续确认原反馈')

    const requests = vi.mocked(createDiagnosisFeedback).mock.calls.map((call) => call[2].request_id)
    expect(new Set(requests).size).toBe(2)
    expect(sessionStorage.length).toBe(2)
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
    await store.recoverFeedback(credentials, store.pendingFeedback[0]!)
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
    await vi.waitFor(() => expect(createDiagnosisFeedback).toHaveBeenCalledTimes(1))
    const other = { ...credentials, experimentSessionId: 'student-session-b' }
    await store.load(other)
    finish(feedback)
    await first
    expect(store.dashboard?.feedback).toBeNull()
    expect(getStudentDashboard).toHaveBeenCalledTimes(2)
  })
})

const recoveryItem: FeedbackRecoveryItem = {
  ...feedback,
  diagnosis_result_id: 'older-diagnosis',
  request_id: '655b30d0-27e4-4280-8769-c00f039fc88d',
  note: '保留原备注：检查后仍未解决',
  processing_status: 'pending',
}

function recoveryWith(item: FeedbackRecoveryItem = recoveryItem) {
  return { pending: [structuredClone(item)], latest_applied: null, has_more_pending: false }
}

describe('server-backed feedback recovery', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.resetAllMocks()
    vi.mocked(getStudentDashboard).mockImplementation(async () =>
      structuredClone(reviewStudentDashboard),
    )
    vi.mocked(getLatestDiagnosisWorkflow).mockResolvedValue(null)
    vi.mocked(getFeedbackRecovery).mockResolvedValue(recoveryWith())
    vi.mocked(createDiagnosisFeedback).mockResolvedValue(feedback)
  })

  it('finds a prior diagnosis in a new tab and explicitly resumes with the complete original payload', async () => {
    const store = await loadedStore()
    expect(sessionStorage.length).toBe(0)
    expect(createDiagnosisFeedback).not.toHaveBeenCalled()
    expect(store.pendingFeedback).toHaveLength(1)
    await store.recoverFeedback(credentials, store.pendingFeedback[0]!)
    expect(createDiagnosisFeedback).toHaveBeenCalledWith(
      credentials,
      recoveryItem.diagnosis_result_id,
      {
        request_id: recoveryItem.request_id,
        action: recoveryItem.action,
        note: recoveryItem.note,
      },
    )
    expect(sessionStorage.length).toBe(0)
  })

  it('blocks a new request when server pending exists without creating a local identity', async () => {
    const store = await loadedStore()
    await expect(store.submitFeedback(credentials, 'resolved')).rejects.toThrow('继续确认原反馈')
    expect(createDiagnosisFeedback).not.toHaveBeenCalled()
    expect(sessionStorage.length).toBe(0)
    expect(getFeedbackRecovery).toHaveBeenCalledTimes(2)
  })

  it('fails closed when the initial or pre-submission recovery query fails', async () => {
    vi.mocked(getFeedbackRecovery).mockRejectedValue(new Error('offline'))
    const store = await loadedStore()
    expect(store.state).toBe('ready')
    expect(store.feedbackRecoveryState).toBe('error')
    await expect(store.submitFeedback(credentials, 'resolved')).rejects.toThrow('无法查询')
    expect(createDiagnosisFeedback).not.toHaveBeenCalled()
    expect(sessionStorage.length).toBe(0)
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: null,
      has_more_pending: false,
    })
    expect(await store.refreshFeedbackRecovery(credentials)).toBe(true)
    vi.mocked(getFeedbackRecovery).mockRejectedValue(new Error('offline again'))
    await expect(store.submitFeedback(credentials, 'resolved')).rejects.toThrow('无法查询')
    expect(createDiagnosisFeedback).not.toHaveBeenCalled()
  })

  it('shows an applied result when the successful original response was lost and clears only its local copy', async () => {
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: null,
      has_more_pending: false,
    })
    vi.mocked(createDiagnosisFeedback).mockRejectedValueOnce(new Error('ack lost'))
    const store = await loadedStore()
    await expect(store.submitFeedback(credentials, 'unresolved')).rejects.toThrow('尚未确认')
    const original = vi.mocked(createDiagnosisFeedback).mock.calls[0]![2]
    const applied = {
      ...recoveryItem,
      ...original,
      note: original.note ?? null,
      diagnosis_result_id: store.dashboard!.diagnosis!.id,
      processing_status: 'applied' as const,
    }
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: applied,
      has_more_pending: false,
    })
    await store.refreshFeedbackRecovery(credentials)
    expect(store.feedbackRecovery?.latest_applied).toEqual(applied)
    expect(store.pendingFeedback).toEqual([])
    expect(sessionStorage.length).toBe(0)
    expect(createDiagnosisFeedback).toHaveBeenCalledTimes(1)
  })

  it('accepts a concurrently completed request without resubmitting it', async () => {
    const store = await loadedStore()
    const original = store.pendingFeedback[0]!
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: { ...recoveryItem, processing_status: 'applied' },
      has_more_pending: false,
    })
    expect(await store.recoverFeedback(credentials, original)).toBe(true)
    expect(createDiagnosisFeedback).not.toHaveBeenCalled()
    expect(store.pendingFeedback).toEqual([])
  })

  it('replays the original key if a concurrent completion is older than latest_applied', async () => {
    const store = await loadedStore()
    const original = store.pendingFeedback[0]!
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: {
        ...recoveryItem,
        request_id: '735db861-8e5b-42bf-8e21-8c5300497de2',
        processing_status: 'applied',
      },
      has_more_pending: false,
    })
    await store.recoverFeedback(credentials, original)
    expect(vi.mocked(createDiagnosisFeedback).mock.calls[0]![2].request_id).toBe(
      recoveryItem.request_id,
    )
  })

  it('preserves an unrelated local prepared request while recovering a server request', async () => {
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: null,
      has_more_pending: false,
    })
    vi.mocked(createDiagnosisFeedback).mockRejectedValueOnce(new Error('request not delivered'))
    const store = await loadedStore()
    await expect(store.submitFeedback(credentials, 'resolved')).rejects.toThrow()
    const originalStorage = sessionStorage.getItem(sessionStorage.key(0)!)
    vi.mocked(getFeedbackRecovery).mockResolvedValue(
      recoveryWith({ ...recoveryItem, diagnosis_result_id: store.dashboard!.diagnosis!.id }),
    )
    await store.refreshFeedbackRecovery(credentials)
    expect(store.pendingFeedback).toHaveLength(2)
    await store.recoverFeedback(
      credentials,
      store.pendingFeedback.find((item) => item.source === 'server')!,
    )
    expect(sessionStorage.getItem(sessionStorage.key(0)!)).toBe(originalStorage)
    expect(store.pendingFeedback.some((item) => item.source === 'browser')).toBe(true)
  })

  it('does not put a late recovery query into another session', async () => {
    let finish!: (value: ReturnType<typeof recoveryWith>) => void
    vi.mocked(getFeedbackRecovery).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const store = useStudentDashboardStore()
    const first = store.load(credentials)
    const other = { ...credentials, experimentSessionId: 'student-session-b' }
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: null,
      has_more_pending: false,
    })
    await store.load(other)
    finish(recoveryWith())
    await first
    expect(store.pendingFeedback).toEqual([])
    expect(store.feedbackRecovery?.latest_applied).toBeNull()
  })

  it('does not send an old-session feedback if the session changes during preflight', async () => {
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: null,
      has_more_pending: false,
    })
    const store = await loadedStore()
    let finish!: (value: ReturnType<typeof recoveryWith>) => void
    vi.mocked(getFeedbackRecovery).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const submitting = store.submitFeedback(credentials, 'resolved')
    const assertion = expect(submitting).rejects.toThrow('尚未确认')
    await store.load({ ...credentials, experimentSessionId: 'student-session-b' })
    finish(recoveryWith())
    await assertion
    expect(createDiagnosisFeedback).not.toHaveBeenCalled()
    expect(sessionStorage.length).toBe(0)
  })

  it('keeps feedback blocked when the server reports more pending records', async () => {
    vi.mocked(getFeedbackRecovery).mockResolvedValue({
      pending: [],
      latest_applied: null,
      has_more_pending: true,
    })
    const store = await loadedStore()
    await expect(store.submitFeedback(credentials, 'resolved')).rejects.toThrow('继续确认原反馈')
    expect(createDiagnosisFeedback).not.toHaveBeenCalled()
  })
})

it('can recover a server record even when browser storage is unavailable', async () => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  vi.mocked(getStudentDashboard).mockResolvedValue(structuredClone(reviewStudentDashboard))
  vi.mocked(getLatestDiagnosisWorkflow).mockResolvedValue(null)
  vi.mocked(getFeedbackRecovery).mockResolvedValue(recoveryWith())
  vi.mocked(createDiagnosisFeedback).mockResolvedValue(feedback)
  vi.stubGlobal('sessionStorage', {
    get length() {
      throw new Error('storage blocked')
    },
    getItem() {
      throw new Error('storage blocked')
    },
  })
  try {
    const store = await loadedStore()
    expect(store.feedbackRecoveryState).toBe('ready')
    expect(store.localFeedbackError).toBeTruthy()
    expect(await store.recoverFeedback(credentials, store.pendingFeedback[0]!)).toBe(true)
    expect(vi.mocked(createDiagnosisFeedback).mock.calls[0]![2].request_id).toBe(
      recoveryItem.request_id,
    )
  } finally {
    vi.unstubAllGlobals()
  }
})

it('does not restore the old session or its recovery records after a late workflow start response', async () => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  vi.resetAllMocks()
  vi.mocked(getStudentDashboard).mockImplementation(async () =>
    structuredClone(reviewStudentDashboard),
  )
  vi.mocked(getLatestDiagnosisWorkflow).mockResolvedValue(null)
  vi.mocked(getFeedbackRecovery).mockResolvedValue({
    pending: [],
    latest_applied: null,
    has_more_pending: false,
  })
  let finish!: (value: typeof reviewStudentWorkflow) => void
  vi.mocked(startDiagnosisWorkflow).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  const store = await loadedStore()
  const old = store.runDiagnosisWorkflow(credentials)
  store.clear()
  const other = { ...credentials, experimentSessionId: 'student-session-b' }
  await store.load(other)
  finish(structuredClone(reviewStudentWorkflow))
  await old
  expect(store.workflow).toBeNull()
  expect(store.pendingFeedback).toEqual([])
  expect(getStudentDashboard).toHaveBeenCalledTimes(2)
  expect(getFeedbackRecovery).toHaveBeenCalledTimes(2)
  expect(store.workflowLoading).toBe(false)
})

it('does not apply a late AI explanation to another session', async () => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  vi.resetAllMocks()
  vi.mocked(getStudentDashboard).mockImplementation(async () =>
    structuredClone(reviewStudentDashboard),
  )
  vi.mocked(getLatestDiagnosisWorkflow).mockResolvedValue(null)
  vi.mocked(getFeedbackRecovery).mockResolvedValue({
    pending: [],
    latest_applied: null,
    has_more_pending: false,
  })
  let finish!: (value: typeof reviewAIExplanation) => void
  vi.mocked(requestAIExplanation).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  const store = await loadedStore()
  const old = store.generateAIExplanation(credentials)
  store.clear()
  await store.load({ ...credentials, experimentSessionId: 'student-session-b' })
  finish(structuredClone(reviewAIExplanation))
  await old
  expect(store.dashboard?.ai_explanation).toEqual(reviewStudentDashboard.ai_explanation)
  expect(store.aiLoading).toBe(false)
})
