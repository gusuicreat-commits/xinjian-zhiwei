import { createRouter, createWebHistory } from 'vue-router'

import { hasStoredStudentSession } from '@/stores/studentSession'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/student',
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/student',
      name: 'student-dashboard',
      component: () => import('@/views/StudentDashboardView.vue'),
      meta: { requiresSession: true },
    },
  ],
})

router.beforeEach((to) => {
  const hasSession = hasStoredStudentSession()
  if (to.meta.requiresSession && !hasSession) return { name: 'login' }
  if (to.name === 'login' && hasSession) return { name: 'student-dashboard' }
  return true
})

export default router
