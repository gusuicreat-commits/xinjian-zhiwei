import axios from 'axios'

function resolveApiBaseURL(): string {
  const configuredBaseURL = import.meta.env.VITE_API_BASE_URL?.trim()
  if (configuredBaseURL) return configuredBaseURL

  if (
    import.meta.env.DEV &&
    typeof window !== 'undefined' &&
    ['localhost', '127.0.0.1'].includes(window.location.hostname)
  ) {
    return `${window.location.protocol}//${window.location.hostname}:8000`
  }

  return ''
}

export const apiClient = axios.create({
  baseURL: resolveApiBaseURL(),
  timeout: 8_000,
  headers: {
    Accept: 'application/json',
  },
})

// Fail closed for any future API path missed by a demo adapter.
if (import.meta.env.MODE === 'review') {
  apiClient.interceptors.request.use(() => {
    throw new Error('离线演示不连接业务接口；该操作暂不支持。')
  })
}
