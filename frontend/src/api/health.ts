import { apiClient } from './client'
import type { HealthResponse } from '@/types/health'

export async function getHealth(): Promise<HealthResponse> {
  const response = await apiClient.get<HealthResponse>('/api/v1/health')
  return response.data
}
