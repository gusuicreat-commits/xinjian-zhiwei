import {
  createRouter,
  createWebHashHistory,
  createWebHistory,
  type RouteRecordRaw,
} from 'vue-router'

import { hasStoredStudentSession } from '@/stores/studentSession'
import { hasStoredTeacherSession } from '@/stores/teacherSession'

const reviewMode = import.meta.env.MODE === 'review'
const routes: RouteRecordRaw[] = [
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
]

if (!reviewMode) {
  routes.push({
    path: '/readiness',
    name: 'readiness',
    component: () => import('@/views/ReadinessView.vue'),
  })
}

const router = createRouter({
  history: reviewMode
    ? createWebHashHistory(import.meta.env.BASE_URL)
    : createWebHistory(import.meta.env.BASE_URL),
  routes,
})

router.beforeEach((to) => {
  if (reviewMode) return true
  const hasSession = hasStoredStudentSession()
  const hasTeacherSession = hasStoredTeacherSession()
  if (to.meta.requiresSession && !hasSession) return { name: 'login' }
  if (to.meta.requiresTeacherSession && !hasTeacherSession) return { name: 'teacher-login' }
  if (to.name === 'login' && hasSession) return { name: 'student-dashboard' }
  if (to.name === 'teacher-login' && hasTeacherSession) return { name: 'teacher-dashboard' }
  return true
})

export default router
