import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './client'
import { createDiagnosisFeedback } from './student'

vi.mock('./client', () => ({ apiClient: { post: vi.fn() } }))

describe('feedback API contract', () => {
  beforeEach(() => vi.resetAllMocks())

  it('sends the caller-owned request ID and explicit experiment session together', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: 'saved-feedback' } })
    const payload = {
      request_id: '655b30d0-27e4-4280-8769-c00f039fc88d',
      action: 'unresolved' as const,
    }
    await createDiagnosisFeedback(
      { deviceId: 'device-a', deviceToken: 'test-token', experimentSessionId: 'session-a' },
      'diagnosis-a',
      payload,
    )
    expect(apiClient.post).toHaveBeenCalledWith(
      '/api/v1/student/diagnoses/diagnosis-a/feedback',
      payload,
      {
        headers: {
          'X-Device-ID': 'device-a',
          'X-Device-Token': 'test-token',
          'X-Experiment-Session-ID': 'session-a',
        },
      },
    )
  })

  it('cannot submit a device-only feedback request', async () => {
    await expect(
      createDiagnosisFeedback({ deviceId: 'device-a', deviceToken: 'test-token' }, 'diagnosis-a', {
        request_id: '655b30d0-27e4-4280-8769-c00f039fc88d',
        action: 'unresolved',
      }),
    ).rejects.toThrow('需要实验会话')
    expect(apiClient.post).not.toHaveBeenCalled()
  })
})
