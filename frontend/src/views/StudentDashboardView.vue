<script setup lang="ts">
import {
  Bell,
  Cpu,
  DataAnalysis,
  Document,
  Fold,
  HomeFilled,
  List,
  Menu as MenuIcon,
  Refresh,
  SwitchButton,
  TrendCharts,
  UserFilled,
  Warning,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import DeviceOverview from '@/components/DeviceOverview.vue'
import DiagnosisPanel from '@/components/DiagnosisPanel.vue'
import RealtimeLogList from '@/components/RealtimeLogList.vue'
import SensorTrendChart from '@/components/SensorTrendChart.vue'
import { useStudentDashboardStore } from '@/stores/studentDashboard'
import { useStudentSessionStore } from '@/stores/studentSession'
import type { FeedbackAction } from '@/types/student'

const router = useRouter()
const sessionStore = useStudentSessionStore()
const dashboardStore = useStudentDashboardStore()
const sidebarCollapsed = ref(false)
let refreshTimer: number | undefined

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

const navItems = [
  { label: '首页', target: 'overview', icon: HomeFilled },
  { label: '实验任务', target: 'overview', icon: List },
  { label: '实验设备', target: 'overview', icon: Cpu },
  { label: '数据监控', target: 'readings', icon: TrendCharts },
  { label: '日志分析', target: 'logs', icon: Document },
  { label: '异常诊断', target: 'diagnosis', icon: Warning },
  { label: '诊断报告', target: 'diagnosis', icon: DataAnalysis },
]

async function refresh(): Promise<void> {
  if (!sessionStore.credentials) return
  await dashboardStore.load(sessionStore.credentials)
}

async function submitFeedback(action: FeedbackAction): Promise<void> {
  if (!sessionStore.credentials) return
  try {
    await dashboardStore.submitFeedback(sessionStore.credentials, action)
    ElMessage.success('反馈已记录')
  } catch {
    ElMessage.error('反馈提交失败，请稍后重试')
  }
}

function navigateTo(target: string): void {
  document.getElementById(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function logout(): Promise<void> {
  sessionStore.logout()
  dashboardStore.clear()
  await router.replace('/login')
}

onMounted(() => {
  void refresh()
  refreshTimer = window.setInterval(() => void refresh(), 15_000)
})
onBeforeUnmount(() => window.clearInterval(refreshTimer))
</script>

<template>
  <main class="student-app" :class="{ 'sidebar-is-collapsed': sidebarCollapsed }">
    <header class="app-topbar">
      <div class="brand-lockup">
        <img src="/assets/xinjian-brand-mark.png" alt="芯鉴知微" />
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

    <aside class="app-sidebar">
      <nav aria-label="学生端导航">
        <button
          v-for="(item, index) in navItems"
          :key="item.label"
          type="button"
          :class="{ active: index === 0 }"
          :title="item.label"
          @click="navigateTo(item.target)"
        >
          <component :is="item.icon" /><span>{{ item.label }}</span>
        </button>
      </nav>
      <button
        type="button"
        class="collapse-button"
        :aria-label="sidebarCollapsed ? '展开菜单' : '收起菜单'"
        @click="sidebarCollapsed = !sidebarCollapsed"
      >
        <Fold v-if="!sidebarCollapsed" /><MenuIcon v-else />
        <span>{{ sidebarCollapsed ? '展开菜单' : '收起菜单' }}</span>
      </button>
    </aside>

    <section class="app-content">
      <div class="content-toolbar">
        <div>
          <p>学生实验工作台</p>
          <span v-if="dashboardStore.dashboard"
            >最近更新
            {{ new Date(dashboardStore.dashboard.generated_at).toLocaleTimeString('zh-CN') }}</span
          >
        </div>
        <el-button :loading="dashboardStore.state === 'loading'" @click="refresh"
          ><Refresh /> 刷新数据</el-button
        >
      </div>

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
        <template #extra><el-button type="primary" @click="refresh">重新加载</el-button></template>
      </el-result>
      <div v-else-if="dashboardStore.dashboard" class="dashboard-content">
        <el-alert
          v-if="hasTestData"
          title="当前展示测试或模拟数据，不代表真实设备诊断结果。"
          type="warning"
          :closable="false"
          show-icon
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
            :feedback-loading="dashboardStore.feedbackLoading"
            @feedback="submitFeedback"
          />
        </section>
      </div>
    </section>
  </main>
</template>
