<script setup lang="ts">
import {
  Bell,
  HomeFilled,
  List,
  Monitor,
  Refresh,
  SwitchButton,
  TrendCharts,
  UserFilled,
  Warning,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { FeedbackRequestError } from '@/api/feedbackRetry'
import DeviceOverview from '@/components/DeviceOverview.vue'
import DiagnosisPanel from '@/components/DiagnosisPanel.vue'
import FeedbackRecoveryPanel from '@/components/FeedbackRecoveryPanel.vue'
import RealtimeLogList from '@/components/RealtimeLogList.vue'
import SensorTrendChart from '@/components/SensorTrendChart.vue'
import { useStudentDashboardStore } from '@/stores/studentDashboard'
import { useStudentSessionStore } from '@/stores/studentSession'
import type { FeedbackAction, FeedbackRecoveryTarget } from '@/types/student'

const router = useRouter()
const sessionStore = useStudentSessionStore()
const dashboardStore = useStudentDashboardStore()
const activeNavTarget = ref('overview')
const showRefreshFlash = ref(false)
let refreshTimer: number | undefined
let navigationFrame: number | undefined
let navigationLockUntil = 0

const hasTestData = computed(() => {
  const data = dashboardStore.dashboard
  return Boolean(
    data?.device.is_test_fixture ||
    data?.logs.some((item) => item.is_test_data) ||
    data?.readings.some((item) => item.is_test_data) ||
    data?.diagnosis?.is_test_data ||
    data?.guidance.some((item) => item.is_test_data) ||
    data?.feedback?.is_test_data,
  )
})

const deviceLabel = computed(
  () =>
    dashboardStore.dashboard?.device.display_name ||
    sessionStore.credentials?.deviceId ||
    '设备会话',
)

const navItems = computed(() => {
  const data = dashboardStore.dashboard
  const deviceStatus = data
    ? {
        online: '设备在线',
        offline: '设备离线',
        never_seen: '等待设备上报',
      }[data.device.status]
    : '状态加载中'
  const diagnosisStatus = !data
    ? '状态加载中'
    : data.intervention && !['resolved', 'closed'].includes(data.intervention.status)
      ? '教师协助中'
      : data.feedback?.action === 'resolved'
        ? '问题已解决'
        : data.diagnosis
          ? '已生成诊断'
          : '等待异常信号'

  return [
    { label: '实验概览', meta: deviceStatus, target: 'overview', icon: HomeFilled },
    {
      label: '日志与传感数据',
      meta: `${data?.logs.length ?? 0} 条日志 · ${data?.readings.length ?? 0} 组数据`,
      target: 'logs',
      icon: TrendCharts,
    },
    { label: '诊断与反馈', meta: diagnosisStatus, target: 'diagnosis', icon: Warning },
  ]
})

async function refresh(showTransition = false): Promise<void> {
  if (!sessionStore.credentials) return
  if (showTransition && showRefreshFlash.value) return

  const startedAt = window.performance.now()
  if (showTransition) showRefreshFlash.value = true

  try {
    await dashboardStore.load(sessionStore.credentials)
  } finally {
    if (showTransition) {
      const remainingTime = Math.max(0, 460 - (window.performance.now() - startedAt))
      await new Promise((resolve) => window.setTimeout(resolve, remainingTime))
      showRefreshFlash.value = false
    }
  }
}

async function submitFeedback(action: FeedbackAction): Promise<void> {
  if (!sessionStore.credentials) return
  const credentials = sessionStore.credentials
  try {
    if (
      (await dashboardStore.submitFeedback(credentials, action)) &&
      sessionStore.credentials === credentials
    ) {
      ElMessage.success('反馈已记录')
    }
  } catch (error) {
    if (sessionStore.credentials !== credentials) return
    ElMessage.error(
      error instanceof FeedbackRequestError ? error.message : '反馈提交失败，请稍后重试',
    )
  }
}

async function recoverFeedback(target: FeedbackRecoveryTarget): Promise<void> {
  if (!sessionStore.credentials) return
  const credentials = sessionStore.credentials
  try {
    if (
      (await dashboardStore.recoverFeedback(credentials, target)) &&
      sessionStore.credentials === credentials
    ) {
      ElMessage.success('原反馈已确认')
    }
  } catch (error) {
    if (sessionStore.credentials !== credentials) return
    ElMessage.error(
      error instanceof FeedbackRequestError ? error.message : '确认暂未完成，请稍后重试原反馈',
    )
  }
}

async function refreshFeedbackRecovery(): Promise<void> {
  if (sessionStore.credentials)
    await dashboardStore.refreshFeedbackRecovery(sessionStore.credentials)
}

async function generateAIExplanation(): Promise<void> {
  if (!sessionStore.credentials) return
  try {
    await dashboardStore.generateAIExplanation(sessionStore.credentials)
    const result = dashboardStore.dashboard?.ai_explanation
    if (result?.status === 'succeeded') ElMessage.success('AI 解释已生成')
    else ElMessage.info(result?.notice || '当前保持规则诊断模式')
  } catch {
    ElMessage.error('AI 解释请求失败，规则诊断结果不受影响')
  }
}

async function runDiagnosisWorkflow(): Promise<void> {
  if (!sessionStore.credentials) return
  try {
    await dashboardStore.runDiagnosisWorkflow(sessionStore.credentials)
    const workflow = dashboardStore.workflow
    if (workflow?.status === 'waiting_teacher') ElMessage.warning('诊断已暂停，等待教师审核')
    else if (workflow?.status === 'waiting_feedback') {
      ElMessage.info('请按建议排查后反馈结果，系统将继续本次诊断')
    } else if (workflow?.status === 'completed') ElMessage.success('辅助诊断工作流已完成')
    else ElMessage.info(`工作流状态：${workflow?.status || '未知'}`)
  } catch {
    ElMessage.error('辅助诊断工作流启动失败，原有诊断结果不受影响')
  }
}

function navigateTo(target: string): void {
  activeNavTarget.value = target
  navigationLockUntil = window.performance.now() + 1_200
  const section = document.getElementById(target)
  const scrollTarget = section?.firstElementChild ?? section
  scrollTarget?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function syncActiveNavigation(): void {
  const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight)
  if (maxScroll > 80 && window.scrollY >= maxScroll - 8) {
    activeNavTarget.value = navItems.value[navItems.value.length - 1]?.target ?? 'diagnosis'
    return
  }
  const activationLine = window.innerWidth <= 780 ? 150 : 160
  let nextTarget = navItems.value[0]?.target ?? 'overview'
  for (const item of navItems.value) {
    const section = document.getElementById(item.target)
    const measuredElement = section?.firstElementChild ?? section
    if (measuredElement && measuredElement.getBoundingClientRect().top <= activationLine) {
      nextTarget = item.target
    }
  }
  activeNavTarget.value = nextTarget
}

function handleWindowScroll(): void {
  if (window.performance.now() < navigationLockUntil) return
  if (navigationFrame !== undefined) return
  navigationFrame = window.requestAnimationFrame(() => {
    navigationFrame = undefined
    syncActiveNavigation()
  })
}

async function logout(): Promise<void> {
  sessionStore.logout()
  dashboardStore.clear()
  await router.replace('/login')
}

onMounted(() => {
  void refresh()
  refreshTimer = window.setInterval(() => void refresh(), 15_000)
  window.addEventListener('scroll', handleWindowScroll, { passive: true })
})
onBeforeUnmount(() => {
  window.clearInterval(refreshTimer)
  window.removeEventListener('scroll', handleWindowScroll)
  if (navigationFrame !== undefined) window.cancelAnimationFrame(navigationFrame)
})
</script>

<template>
  <main class="student-app">
    <Transition name="workspace-refresh">
      <div
        v-if="showRefreshFlash"
        class="workspace-refresh-flash"
        role="status"
        aria-label="正在刷新学生端数据"
      />
    </Transition>
    <a class="skip-link" href="#main-student-content">跳到主要内容</a>
    <header class="app-topbar">
      <div class="brand-lockup">
        <Monitor aria-hidden="true" />
        <strong>芯鉴知微</strong>
        <span>学生端</span>
      </div>
      <div class="topbar-context"><List /> 当前实验任务 <span>⌄</span></div>
      <div class="topbar-user">
        <button type="button" aria-label="通知"><Bell /></button>
        <div class="avatar"><UserFilled /></div>
        <div>
          <strong>{{ deviceLabel }}</strong
          ><small>临时设备会话</small>
        </div>
        <button type="button" aria-label="退出登录" @click="logout"><SwitchButton /></button>
      </div>
    </header>

    <section id="main-student-content" class="app-content" tabindex="-1">
      <div class="content-toolbar">
        <div>
          <p class="workspace-kicker">STUDENT EXPERIMENT CONSOLE</p>
          <h1>学生实验<span class="workspace-title-accent">工作台</span></h1>
          <small>查看设备状态，理解异常原因，并完成排查反馈。</small>
          <span v-if="dashboardStore.dashboard"
            >最近更新
            {{ new Date(dashboardStore.dashboard.generated_at).toLocaleTimeString('zh-CN') }}</span
          >
        </div>
        <el-button
          :loading="dashboardStore.state === 'loading' || showRefreshFlash"
          @click="refresh(true)"
          ><Refresh /> 刷新数据</el-button
        >
      </div>
      <nav class="student-section-nav" aria-label="页面快速定位与实时状态">
        <button
          v-for="item in navItems"
          :key="item.target"
          type="button"
          :class="{ active: activeNavTarget === item.target }"
          :aria-current="activeNavTarget === item.target ? 'location' : undefined"
          @click="navigateTo(item.target)"
        >
          <component :is="item.icon" />
          <span class="student-nav-copy">
            <b>{{ item.label }}</b>
            <small>{{ item.meta }}</small>
          </span>
        </button>
      </nav>

      <el-skeleton
        v-if="dashboardStore.state === 'loading'"
        :rows="10"
        animated
        class="dashboard-skeleton"
      />
      <el-result
        v-else-if="dashboardStore.state === 'error'"
        icon="error"
        title="数据加载失败"
        :sub-title="dashboardStore.errorMessage"
      >
        <template #extra
          ><el-button type="primary" @click="refresh(true)">重新加载</el-button></template
        >
      </el-result>
      <div v-else-if="dashboardStore.dashboard" class="dashboard-content">
        <el-alert
          v-if="hasTestData"
          title="当前展示测试或模拟数据，不代表真实设备诊断结果。"
          type="warning"
          :closable="false"
          show-icon
        />
        <FeedbackRecoveryPanel
          :state="dashboardStore.feedbackRecoveryState"
          :recovery="dashboardStore.feedbackRecovery"
          :pending="dashboardStore.pendingFeedback"
          :error="dashboardStore.feedbackRecoveryError"
          :local-error="dashboardStore.localFeedbackError"
          :loading="dashboardStore.feedbackLoading"
          :current-diagnosis-id="dashboardStore.dashboard.diagnosis?.id"
          @retry="refreshFeedbackRecovery"
          @recover="recoverFeedback"
        />
        <div id="overview">
          <DeviceOverview
            :task="dashboardStore.dashboard.task"
            :device="dashboardStore.dashboard.device"
          />
        </div>
        <section class="analysis-grid">
          <RealtimeLogList :logs="dashboardStore.dashboard.logs" />
          <SensorTrendChart :readings="dashboardStore.dashboard.readings" />
          <DiagnosisPanel
            :diagnosis="dashboardStore.dashboard.diagnosis"
            :guidance="dashboardStore.dashboard.guidance"
            :feedback="dashboardStore.dashboard.feedback"
            :intervention="dashboardStore.dashboard.intervention"
            :feedback-loading="dashboardStore.feedbackLoading"
            :feedback-blocked="dashboardStore.feedbackBlocked"
            :ai-status="dashboardStore.dashboard.ai_status"
            :ai-explanation="dashboardStore.dashboard.ai_explanation"
            :ai-loading="dashboardStore.aiLoading"
            :workflow="dashboardStore.workflow"
            :workflow-loading="dashboardStore.workflowLoading"
            :has-experiment-session="Boolean(sessionStore.credentials?.experimentSessionId)"
            :device-state-explanation="dashboardStore.dashboard.device_state_explanation"
            @feedback="submitFeedback"
            @request-ai="generateAIExplanation"
            @request-workflow="runDiagnosisWorkflow"
          />
        </section>
      </div>
    </section>
  </main>
</template>
