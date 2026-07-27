import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { createUserSession, getCurrentUser, getMyClasses } from '@/api/auth'
import type { ClassroomSummary, CurrentUser, UserSession } from '@/types/auth'

const STORAGE_KEY = 'xinjian-classroom-session'

function restore(): UserSession | null {
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    const session = JSON.parse(raw) as UserSession
    if (new Date(session.expires_at).getTime() <= Date.now()) {
      sessionStorage.removeItem(STORAGE_KEY)
      return null
    }
    return session
  } catch {
    sessionStorage.removeItem(STORAGE_KEY)
    return null
  }
}

export const useClassroomSessionStore = defineStore('classroom-session', () => {
  const session = ref<UserSession | null>(restore())
  const user = ref<CurrentUser | null>(null)
  const classes = ref<ClassroomSummary[]>([])
  const isAuthenticated = computed(() => session.value !== null)

  async function login(username: string, password: string) {
    const next = await createUserSession(username, password)
    session.value = next
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    await refreshScope()
  }

  async function refreshScope() {
    if (!session.value) return
    ;[user.value, classes.value] = await Promise.all([
      getCurrentUser(session.value.access_token),
      getMyClasses(session.value.access_token),
    ])
  }

  function logout() {
    session.value = null
    user.value = null
    classes.value = []
    sessionStorage.removeItem(STORAGE_KEY)
  }

  return { session, user, classes, isAuthenticated, login, refreshScope, logout }
})
