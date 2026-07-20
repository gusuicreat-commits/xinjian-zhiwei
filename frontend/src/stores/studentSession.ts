import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { createStudentSession } from '@/api/student'
import type { DeviceCredentials, StudentSession } from '@/types/student'

const STORAGE_KEY = 'xinjian-student-device-session'

export function hasStoredStudentSession(): boolean {
  return restoreCredentials() !== null
}

function restoreCredentials(): DeviceCredentials | null {
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<DeviceCredentials>
    return value.deviceId && value.deviceToken
      ? { deviceId: value.deviceId, deviceToken: value.deviceToken }
      : null
  } catch {
    sessionStorage.removeItem(STORAGE_KEY)
    return null
  }
}

export const useStudentSessionStore = defineStore('student-session', () => {
  const credentials = ref<DeviceCredentials | null>(restoreCredentials())
  const session = ref<StudentSession | null>(null)
  const loading = ref(false)
  const errorMessage = ref('')
  const isAuthenticated = computed(() => credentials.value !== null)

  async function login(nextCredentials: DeviceCredentials): Promise<void> {
    loading.value = true
    errorMessage.value = ''
    try {
      session.value = await createStudentSession(nextCredentials)
      credentials.value = nextCredentials
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(nextCredentials))
    } catch {
      errorMessage.value = '设备凭据无效，或后端尚未部署 Phase 6 接口。'
      throw new Error(errorMessage.value)
    } finally {
      loading.value = false
    }
  }

  function logout(): void {
    credentials.value = null
    session.value = null
    errorMessage.value = ''
    sessionStorage.removeItem(STORAGE_KEY)
  }

  return {
    credentials,
    session,
    loading,
    errorMessage,
    isAuthenticated,
    login,
    logout,
  }
})
