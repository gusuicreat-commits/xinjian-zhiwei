// Isolated, tab-local demo state. Never use these keys for an authenticated session.
export function readReviewState<T>(key: string, fallback: T): T {
  try {
    const saved = sessionStorage.getItem(`xinjian-review-v2:${key}`)
    return saved ? (JSON.parse(saved) as T) : structuredClone(fallback)
  } catch {
    return structuredClone(fallback)
  }
}
export function saveReviewState(key: string, value: unknown): void {
  sessionStorage.setItem(`xinjian-review-v2:${key}`, JSON.stringify(value))
}
