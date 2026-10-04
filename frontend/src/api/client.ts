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

// The default workflow has two governed 30s stages plus bounded local work.
// This is a client waiting budget, not permission to resend an unknown command.
const MODEL_OPERATION_TIMEOUT_MS = 75_000
const modelOperationPaths = [
  /^\/api\/v1\/diagnosis-workflows\/devices\/[^/]+\/?$/,
  /^\/api\/v1\/diagnosis-workflows\/[^/]+\/review\/?$/,
  /^\/api\/v1\/student\/diagnoses\/[^/]+\/feedback\/?$/,
  /^\/api\/v1\/diagnosis\/results\/[^/]+\/ai-explanation\/?$/,
  /^\/api\/v1\/knowledge\/case-drafts\/[^/]+\/ai-polish\/?$/,
]
apiClient.interceptors.request.use((config) => {
  const path = (config.url ?? '').split('?')[0] ?? ''
  if (config.method === 'post' && modelOperationPaths.some((pattern) => pattern.test(path))) {
    config.timeout = MODEL_OPERATION_TIMEOUT_MS
  }
  return config
})

// Fail closed for any future API path missed by a demo adapter.
if (import.meta.env.MODE === 'review') {
  apiClient.interceptors.request.use(() => {
    throw new Error('离线演示不连接业务接口；该操作暂不支持。')
  })
}
