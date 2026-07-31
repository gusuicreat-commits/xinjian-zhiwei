import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { createTeacherSession } from '@/api/teacher'
import type { UserSession } from '@/types/auth'

const STORAGE_KEY = 'xinjian-teacher-session'

function restoreSession(): UserSession | null {
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    const restored = JSON.parse(raw) as UserSession
    if (new Date(restored.expires_at).getTime() <= Date.now()) {
      sessionStorage.removeItem(STORAGE_KEY)
      return null
    }
    return restored
  } catch {
    sessionStorage.removeItem(STORAGE_KEY)
    return null
  }
}

export function hasStoredTeacherSession(): boolean {
  return restoreSession() !== null
}

export const useTeacherSessionStore = defineStore('teacher-session', () => {
  const session = ref<UserSession | null>(restoreSession())
  const accessToken = computed(() => session.value?.access_token ?? null)
  const loading = ref(false)
  const errorMessage = ref('')

  async function login(username: string, password: string): Promise<void> {
    loading.value = true
    errorMessage.value = ''
    try {
      session.value = await createTeacherSession(username, password)
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session.value))
    } catch (error) {
      errorMessage.value =
        error instanceof Error && error.message === 'TEACHER_ROLE_REQUIRED'
          ? '该账号没有教师或管理员角色，不能进入教师端。'
          : '用户名或密码不正确，请使用演示数据脚本生成的教师账号。'
      throw new Error(errorMessage.value)
    } finally {
      loading.value = false
    }
  }

  function logout(): void {
    session.value = null
    errorMessage.value = ''
    sessionStorage.removeItem(STORAGE_KEY)
  }

  return { session, accessToken, loading, errorMessage, login, logout }
})
