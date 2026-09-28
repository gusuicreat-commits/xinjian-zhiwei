import { apiClient } from '@/api/client'
import type {
  CleanupPlan,
  MemoryEvent,
  MemoryImpact,
  MemoryPage,
  ReviewDecision,
} from '@/types/memory'
const auth = (token: string) => ({ headers: { Authorization: `Bearer ${token}` } })
export async function memoryEvents(token: string, after = '') {
  return (
    await apiClient.get<MemoryPage<MemoryEvent>>('/api/v1/memory/events', {
      ...auth(token),
      params: { after_id: after },
    })
  ).data
}
export async function memoryImpacts(token: string, event: string, after = '') {
  return (
    await apiClient.get<MemoryPage<MemoryImpact>>(`/api/v1/memory/events/${event}/impacts`, {
      ...auth(token),
      params: { after_id: after },
    })
  ).data
}
export async function saveMemoryReview(
  token: string,
  event: string,
  item: MemoryImpact,
  decision: ReviewDecision,
  note: string,
) {
  return (
    await apiClient.post(
      `/api/v1/memory/events/${event}/impacts/${item.diagnosis_result_id}/review`,
      { expected_version: item.review?.version ?? 0, decision, note },
      auth(token),
    )
  ).data
}
export async function previewMemoryCleanup(token: string) {
  return (await apiClient.post<CleanupPlan>('/api/v1/memory/cleanup-plans', undefined, auth(token)))
    .data
}
export async function executeMemoryCleanup(token: string, plan: CleanupPlan) {
  return (
    await apiClient.post<CleanupPlan>(
      `/api/v1/memory/cleanup-plans/${plan.id}/execute`,
      { plan_hash: plan.plan_hash },
      auth(token),
    )
  ).data
}

export async function memoryImpactHistory(token: string, event: string, diagnosis: string) {
  return (
    await apiClient.get<{
      usable_as_current_advice: false
      rules: Array<{ summary?: string }>
      historical_result: { summary?: string; steps?: string[] } | null
    }>(`/api/v1/memory/events/${event}/impacts/${diagnosis}/history`, auth(token))
  ).data
}
