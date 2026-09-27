import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { createTeacherSession } from '@/api/teacher'
import { REVIEW_MODE, reviewTeacherSession } from '@/review/fixtures'
import { useTeacherDashboardStore } from './teacherDashboard'
import type { UserSession } from '@/types/auth'

const STORAGE_KEY = 'xinjian-teacher-session'

function restoreSession(): UserSession | null {
  if (REVIEW_MODE) return { ...reviewTeacherSession }
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
  let revision = 0
  const loading = ref(false)
  const errorMessage = ref('')

  async function login(username: string, password: string): Promise<void> {
    logout()
    const request = revision
    loading.value = true
    errorMessage.value = ''
    try {
      if (REVIEW_MODE) {
        session.value = { ...reviewTeacherSession, username }
        return
      }
      const result = await createTeacherSession(username, password)
      if (request !== revision) return
      session.value = result
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session.value))
    } catch (error) {
      if (request !== revision) return
      errorMessage.value =
        error instanceof Error && error.message === 'TEACHER_ROLE_REQUIRED'
          ? '该账号没有教师或管理员角色，不能进入教师端。'
          : '用户名或密码不正确，请使用演示数据脚本生成的教师账号。'
      throw new Error(errorMessage.value)
    } finally {
      if (request === revision) loading.value = false
    }
  }

  function logout(): void {
    revision += 1
    loading.value = false
    useTeacherDashboardStore().clear()
    session.value = null
    errorMessage.value = ''
    sessionStorage.removeItem(STORAGE_KEY)
  }

  return { session, accessToken, loading, errorMessage, login, logout }
})
