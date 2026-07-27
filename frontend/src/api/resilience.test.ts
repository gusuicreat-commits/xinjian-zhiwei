import axios from 'axios'
import { describe, expect, it, vi } from 'vitest'

import { classifyRequestFailure, withCappedRetry } from '@/api/resilience'

describe('request resilience', () => {
  it('distinguishes authentication and backend failures', () => {
    expect(
      classifyRequestFailure(new axios.AxiosError('unauthorized', 'ERR', undefined, undefined, {
        status: 401,
        statusText: 'Unauthorized',
        headers: {},
        config: { headers: {} } as never,
        data: {},
      })),
    ).toBe('unauthorized')
    expect(classifyRequestFailure(new axios.AxiosError('network'))).toBe('backend')
  })

  it('caps retries and succeeds without an infinite loop', async () => {
    const operation = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new axios.AxiosError('network'))
      .mockResolvedValue('ok')

    await expect(withCappedRetry(operation, 1)).resolves.toBe('ok')
    expect(operation).toHaveBeenCalledTimes(2)
  })
})
