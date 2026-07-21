import { defineStore } from 'pinia'
import { ref } from 'vue'

import { createTeacherSession } from '@/api/teacher'
import type { TeacherCredentials, TeacherSession } from '@/types/teacher'

const STORAGE_KEY = 'xinjian-teacher-review-session'

function restoreCredentials(): TeacherCredentials | null {
  const reviewToken = sessionStorage.getItem(STORAGE_KEY)
  return reviewToken ? { reviewToken } : null
}

export function hasStoredTeacherSession(): boolean {
  return restoreCredentials() !== null
}

export const useTeacherSessionStore = defineStore('teacher-session', () => {
  const credentials = ref<TeacherCredentials | null>(restoreCredentials())
  const session = ref<TeacherSession | null>(null)
  const loading = ref(false)
  const errorMessage = ref('')

  async function login(nextCredentials: TeacherCredentials): Promise<void> {
    loading.value = true
    errorMessage.value = ''
    try {
      session.value = await createTeacherSession(nextCredentials)
      credentials.value = nextCredentials
      sessionStorage.setItem(STORAGE_KEY, nextCredentials.reviewToken)
    } catch {
      errorMessage.value = '审阅凭据无效，或后端尚未配置临时教师访问令牌。'
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

  return { credentials, session, loading, errorMessage, login, logout }
})
