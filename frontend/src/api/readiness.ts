import { apiClient } from '@/api/client'
import type { ReadinessStatus } from '@/types/readiness'

export async function getReadiness(): Promise<ReadinessStatus> {
  const response = await apiClient.get<ReadinessStatus>('/api/v1/readiness/status')
  return response.data
}
