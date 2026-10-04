import axios, { type AxiosAdapter } from 'axios'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from './client'
import { pendingCheck, submitCheck } from './diagnosisChecks'
import { createDiagnosisFeedback, requestAIExplanation } from './student'

const credentials = { deviceId: 'device', deviceToken: 'synthetic', experimentSessionId: 'session' }
const originalAdapter = apiClient.defaults.adapter
let delay = 9_000
let posts: string[] = []
const timedTransport: AxiosAdapter = (config) =>
  new Promise((resolve, reject) => {
    if (config.method !== 'post') {
      resolve({ data: null, status: 200, statusText: 'OK', headers: {}, config })
      return
    }
    posts.push(String(config.data))
    const response = setTimeout(() => {
      clearTimeout(deadline)
      resolve({ data: { id: 'saved' }, status: 200, statusText: 'OK', headers: {}, config })
    }, delay)
    const deadline = setTimeout(() => {
      clearTimeout(response)
      reject(new axios.AxiosError('timeout', 'ECONNABORTED', config))
    }, config.timeout)
  })
beforeEach(() => {
  vi.useFakeTimers()
  sessionStorage.clear()
  posts = []
  delay = 9_000
  apiClient.defaults.adapter = timedTransport
})
afterEach(() => {
  apiClient.defaults.adapter = originalAdapter
  vi.useRealTimers()
})
it.each(['check', 'feedback', 'explanation'])(
  'waits for a normal 9 second %s without resending',
  async (operation) => {
    const request =
      operation === 'check'
        ? submitCheck(credentials, {})
        : operation === 'feedback'
          ? createDiagnosisFeedback(credentials, 'diagnosis', {
              request_id: '11111111-1111-4111-8111-111111111111',
              action: 'unresolved',
            })
          : requestAIExplanation(credentials, 'diagnosis')
    const outcome = request.then(
      () => 'saved',
      () => 'failed',
    )
    await vi.advanceTimersByTimeAsync(9_100)
    expect(await outcome).toBe('saved')
    expect(posts).toHaveLength(1)
    expect(apiClient.defaults.timeout).toBe(8_000)
  },
)
it('ends a stalled check at 75 seconds and recovers the original request explicitly', async () => {
  delay = 100_000
  let settled = false
  const outcome = submitCheck(credentials, {}, 'original').then(
    () => {
      settled = true
      return 'saved'
    },
    () => {
      settled = true
      return 'failed'
    },
  )
  await vi.advanceTimersByTimeAsync(74_000)
  expect(settled).toBe(false)
  expect(posts).toHaveLength(1)
  expect(pendingCheck(credentials)?.baseline_id).toBe('original')
  await vi.advanceTimersByTimeAsync(1_100)
  expect(await outcome).toBe('failed')
  delay = 9_000
  const recovery = submitCheck(credentials, {}, 'different')
  await vi.advanceTimersByTimeAsync(9_100)
  await recovery
  expect(posts).toHaveLength(2)
  expect(posts[1]).toBe(posts[0])
  expect(pendingCheck(credentials)).toBeNull()
})
