import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getHealth } from '@/api/health'
import type { HealthResponse } from '@/types/health'

export type HealthState = 'idle' | 'loading' | 'ready' | 'error'

export const useHealthStore = defineStore('health', () => {
  const state = ref<HealthState>('idle')
  const health = ref<HealthResponse | null>(null)
  const errorMessage = ref('')

  async function loadHealth(): Promise<void> {
    state.value = 'loading'
    errorMessage.value = ''

    try {
      health.value = await getHealth()
      state.value = 'ready'
    } catch {
      health.value = null
      errorMessage.value = '暂时无法连接后端服务，请确认 FastAPI 已启动。'
      state.value = 'error'
    }
  }

  return { state, health, errorMessage, loadHealth }
})
