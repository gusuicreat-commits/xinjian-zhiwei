import axios from 'axios'

export type RequestFailureKind = 'offline' | 'backend' | 'unauthorized' | 'forbidden' | 'unknown'

export function classifyRequestFailure(error: unknown): RequestFailureKind {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return 'offline'
  if (!axios.isAxiosError(error)) return 'unknown'
  if (!error.response || error.code === 'ECONNABORTED') return 'backend'
  if (error.response.status === 401) return 'unauthorized'
  if (error.response.status === 403) return 'forbidden'
  if (error.response.status >= 500) return 'backend'
  return 'unknown'
}

export function failureMessage(kind: RequestFailureKind): string {
  const messages: Record<RequestFailureKind, string> = {
    offline: '数据加载失败：当前浏览器离线，已保留上次数据；恢复网络后可重试。',
    backend: '数据加载失败：后端服务暂不可用，已保留上次数据，请稍后重试。',
    unauthorized: '数据加载失败：会话已失效，请重新登录。',
    forbidden: '数据加载失败：当前账号没有访问该资源的权限。',
    unknown: '数据加载失败：已保留上次数据，请重试。',
  }
  return messages[kind]
}

export async function withCappedRetry<T>(operation: () => Promise<T>, retries = 1): Promise<T> {
  let lastError: unknown
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      const kind = classifyRequestFailure(error)
      if (attempt >= retries || !['backend'].includes(kind)) throw error
      await new Promise((resolve) => window.setTimeout(resolve, 300 * 2 ** attempt))
    }
  }
  throw lastError
}
