import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getTeacherDashboard } from '@/api/teacher'
import type { TeacherCredentials, TeacherDashboard } from '@/types/teacher'

export const useTeacherDashboardStore = defineStore('teacher-dashboard', () => {
  const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const dashboard = ref<TeacherDashboard | null>(null)
  const errorMessage = ref('')

  async function load(credentials: TeacherCredentials): Promise<void> {
    state.value = dashboard.value ? 'ready' : 'loading'
    errorMessage.value = ''
    try {
      dashboard.value = await getTeacherDashboard(credentials)
      state.value = 'ready'
    } catch {
      state.value = 'error'
      errorMessage.value = '教师端数据加载失败，请检查审阅会话或后端服务。'
    }
  }

  function clear(): void {
    state.value = 'idle'
    dashboard.value = null
    errorMessage.value = ''
  }

  return { state, dashboard, errorMessage, load, clear }
})
