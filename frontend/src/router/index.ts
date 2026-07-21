import { createRouter, createWebHistory } from 'vue-router'

import { hasStoredStudentSession } from '@/stores/studentSession'
import { hasStoredTeacherSession } from '@/stores/teacherSession'

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
    {
      path: '/teacher/login',
      name: 'teacher-login',
      component: () => import('@/views/TeacherLoginView.vue'),
    },
    {
      path: '/teacher',
      name: 'teacher-dashboard',
      component: () => import('@/views/TeacherDashboardView.vue'),
      meta: { requiresTeacherSession: true },
    },
  ],
})

router.beforeEach((to) => {
  const hasSession = hasStoredStudentSession()
  const hasTeacherSession = hasStoredTeacherSession()
  if (to.meta.requiresSession && !hasSession) return { name: 'login' }
  if (to.meta.requiresTeacherSession && !hasTeacherSession) return { name: 'teacher-login' }
  if (to.name === 'login' && hasSession) return { name: 'student-dashboard' }
  if (to.name === 'teacher-login' && hasTeacherSession) return { name: 'teacher-dashboard' }
  return true
})

export default router
