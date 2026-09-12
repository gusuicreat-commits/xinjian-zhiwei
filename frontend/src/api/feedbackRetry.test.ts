import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getOrCreateFeedbackRequest } from './feedbackRetry'

const credentials = {
  deviceId: 'test-device',
  deviceToken: 'test-token',
  experimentSessionId: 'test-session',
}

describe('pending feedback persistence', () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('can produce UUID v4 on a LAN origin without randomUUID', () => {
    vi.stubGlobal('crypto', { getRandomValues: (bytes: Uint8Array) => bytes.fill(0xaa) })
    expect(getOrCreateFeedbackRequest(credentials, 'diagnosis-a', 'unresolved').request_id).toBe(
      'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa',
    )
  })

  it('does not allow submission without first saving the retry identity', () => {
    vi.stubGlobal('sessionStorage', {
      getItem: () => null,
      setItem: () => {
        throw new Error('storage disabled')
      },
    })
    expect(() => getOrCreateFeedbackRequest(credentials, 'diagnosis-a', 'unresolved')).toThrow(
      '无法保存反馈重试记录',
    )
  })
})
