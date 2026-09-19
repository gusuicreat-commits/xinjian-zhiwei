import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  completeFeedbackRequest,
  getOrCreateFeedbackRequest,
  listLocalFeedbackRequests,
} from './feedbackRetry'

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

it('retains the original note and will not erase a different prepared payload', () => {
  sessionStorage.clear()
  const first = getOrCreateFeedbackRequest(
    credentials,
    'diagnosis-note',
    'unresolved',
    '原备注，不能改写',
  )
  expect(
    getOrCreateFeedbackRequest(credentials, 'diagnosis-note', 'unresolved', first.note),
  ).toEqual(first)
  expect(listLocalFeedbackRequests(credentials)[0]?.payload).toEqual(first)
  expect(() =>
    getOrCreateFeedbackRequest(credentials, 'diagnosis-note', 'unresolved', '改写后的备注'),
  ).toThrow('先点击原反馈重试')
  completeFeedbackRequest(credentials, 'diagnosis-note', { ...first, note: 'different note' })
  expect(listLocalFeedbackRequests(credentials)).toHaveLength(1)
  completeFeedbackRequest(credentials, 'diagnosis-note', first)
  expect(listLocalFeedbackRequests(credentials)).toEqual([])
})

it('a server receipt can confirm an old implicit single-problem request without accepting another explicit target', () => {
  sessionStorage.clear()
  const pending = getOrCreateFeedbackRequest(credentials, 'legacy-diagnosis', 'resolved')
  const target = '655b30d0-27e4-4280-8769-c00f039fc88d'
  completeFeedbackRequest(credentials, 'legacy-diagnosis', { ...pending, episode_id: target }, true)
  expect(listLocalFeedbackRequests(credentials)).toEqual([])
  const explicit = getOrCreateFeedbackRequest(
    credentials,
    'new-diagnosis',
    'resolved',
    null,
    target,
  )
  completeFeedbackRequest(
    credentials,
    'new-diagnosis',
    {
      ...explicit,
      episode_id: '755b30d0-27e4-4280-8769-c00f039fc88d',
    },
    true,
  )
  expect(listLocalFeedbackRequests(credentials)).toHaveLength(1)
  sessionStorage.clear()
})
