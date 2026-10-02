<script setup lang="ts">
import {
  HomeFilled,
  List,
  Monitor,
  Refresh,
  SwitchButton,
  TrendCharts,
  UserFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { CheckRequestError } from '@/api/diagnosisChecks'
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
type StudentView = 'work' | 'data' | 'reference'
const activeView = ref<StudentView>('work')
const scrollPositions: Record<StudentView, number> = { work: 0, data: 0, reference: 0 }
const showRefreshFlash = ref(false)
const checkError = ref<CheckRequestError | null>(null)
const readOnly = computed(
  () =>
    dashboardStore.readOnly || Boolean(checkError.value && checkError.value.action !== 'confirm'),
)
const mustLogin = computed(
  () =>
    ['unauthorized', 'forbidden'].includes(dashboardStore.failureKind ?? '') ||
    checkError.value?.action === 'login',
)
const recoveryLabel = computed(
  () =>
    ({
      login: '重新登录',
      refresh: '查看最新状态',
      confirm: '继续确认原检查',
      review: '核对当前实验',
      retry: '重新查询状态',
    })[checkError.value?.action ?? 'refresh'],
)
watch(
  () => sessionStore.credentials,
  () => {
    checkError.value = null
    activeView.value = 'work'
    scrollPositions.work = scrollPositions.data = scrollPositions.reference = 0
  },
)
async function recoverCheck() {
  if (checkError.value?.action === 'login') return logout()
  if (checkError.value?.action === 'confirm') return runDiagnosisWorkflow()
  await refresh(true)
}

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

const deviceStatus = computed(() => {
  const status = dashboardStore.dashboard?.device.status
  return status
    ? { online: '设备在线', offline: '设备离线', never_seen: '等待设备上报' }[status]
    : '状态加载中'
})
const navItems = [
  { label: '当前实验', target: 'work' as const, icon: HomeFilled },
  { label: '数据记录', target: 'data' as const, icon: TrendCharts },
  { label: '实验参考', target: 'reference' as const, icon: List },
]
const latestReadingAt = computed(() => {
  const times = (dashboardStore.dashboard?.readings ?? [])
    .map((item) => Date.parse(item.observed_at))
    .filter(Number.isFinite)
  return times.length ? new Date(Math.max(...times)).toLocaleString('zh-CN') : '尚无读数'
})
const showObservationChart = computed(
  () =>
    activeView.value === 'work' &&
    !dashboardStore.dashboard?.diagnosis?.matches.length &&
    Boolean(dashboardStore.dashboard?.readings.length),
)

async function refresh(showTransition = false): Promise<void> {
  if (!sessionStore.credentials) return
  if (showTransition && showRefreshFlash.value) return

  const startedAt = window.performance.now()
  if (showTransition) showRefreshFlash.value = true

  try {
    await dashboardStore.load(sessionStore.credentials)
    if (dashboardStore.state === 'ready' && checkError.value?.action !== 'confirm')
      checkError.value = null
  } finally {
    if (showTransition) {
      const remainingTime = Math.max(0, 460 - (window.performance.now() - startedAt))
      await new Promise((resolve) => window.setTimeout(resolve, remainingTime))
      showRefreshFlash.value = false
    }
  }
}

async function submitFeedback(
  action: FeedbackAction,
  episodeId: string | null = null,
): Promise<void> {
  if (!sessionStore.credentials) return
  const credentials = sessionStore.credentials
  try {
    if (
      (await dashboardStore.submitFeedback(credentials, action, episodeId)) &&
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
  if (readOnly.value || !sessionStore.credentials) return
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
  if (readOnly.value || !sessionStore.credentials) return
  const credentials = sessionStore.credentials
  try {
    await dashboardStore.runDiagnosisWorkflow(credentials)
    if (credentials !== sessionStore.credentials) return
    checkError.value = null
    const workflow = dashboardStore.workflow
    if (workflow?.check?.status === 'no_new_data') ElMessage.info('暂无新的检查依据，保留上次诊断')
    else if (workflow?.status === 'waiting_teacher') ElMessage.warning('诊断已暂停，等待教师审核')
    else if (workflow?.status === 'waiting_feedback') {
      ElMessage.info('请按建议排查后反馈结果，系统将继续本次诊断')
    } else if (workflow?.status === 'completed') ElMessage.success('辅助诊断工作流已完成')
    else ElMessage.info(`工作流状态：${workflow?.status || '未知'}`)
  } catch (error) {
    if (credentials !== sessionStore.credentials) return
    checkError.value =
      error instanceof CheckRequestError
        ? error
        : new CheckRequestError(
            error instanceof Error ? error.message : '检查结果尚未确认，请刷新状态核对。',
            'review',
          )
  }
}

async function navigateTo(target: StudentView): Promise<void> {
  if (target === activeView.value) return
  scrollPositions[activeView.value] = window.scrollY
  activeView.value = target
  await nextTick()
  window.scrollTo({ top: scrollPositions[target], behavior: 'instant' })
}
function navigateWithKeyboard(event: KeyboardEvent, index: number): void {
  const offset = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
  if (!offset && !['Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const nextIndex =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? navItems.length - 1
        : (index + offset + navItems.length) % navItems.length
  const next = navItems[nextIndex]!
  void navigateTo(next.target)
  document.getElementById(`student-tab-${next.target}`)?.focus()
}

async function logout(): Promise<void> {
  const revocation = sessionStore.logout()
  dashboardStore.clear()
  await revocation
  await router.replace('/login')
}

async function finishExperiment(): Promise<void> {
  if (readOnly.value) return
  const actingCredentials = sessionStore.credentials
  try {
    await sessionStore.finishExperiment()
    if (sessionStore.credentials && sessionStore.credentials !== actingCredentials) return
    dashboardStore.clear()
    await router.replace('/login')
  } catch {
    if (sessionStore.credentials && sessionStore.credentials !== actingCredentials) return
    if (!sessionStore.isAuthenticated) {
      dashboardStore.clear()
      await router.replace('/login')
    }
    ElMessage.warning(
      sessionStore.errorMessage || '结束结果尚未确认，请重试原操作或重新登录查看会话状态。',
    )
  }
}

onMounted(() => {
  void refresh()
  refreshTimer = window.setInterval(() => void refresh(), 15_000)
})
onBeforeUnmount(() => {
  window.clearInterval(refreshTimer)
})
</script>

<template>
  <main class="student-app task-organized-student">
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
      <div class="topbar-context">
        <List /> {{ dashboardStore.dashboard?.task.title || '当前实验' }}
      </div>
      <div class="topbar-user">
        <div class="avatar"><UserFilled /></div>
        <div>
          <strong>{{ deviceLabel }}</strong
          ><small>{{ sessionStore.credentials?.accessToken ? '学生账号' : '测试设备会话' }}</small>
        </div>
        <el-button
          v-if="sessionStore.credentials?.accessToken"
          :disabled="readOnly || dashboardStore.feedbackBlocked"
          @click="finishExperiment"
          >结束本次实验</el-button
        >
        <button type="button" aria-label="退出登录" @click="logout"><SwitchButton /></button>
      </div>
    </header>

    <section id="main-student-content" class="app-content" tabindex="-1">
      <div class="content-toolbar">
        <div>
          <h1>学生实验<span class="workspace-title-accent">工作台</span></h1>
          <small>查看当前实验，按问题排查，记录你的反馈。</small>
          <span v-if="dashboardStore.dashboard"
            >页面读取时间
            {{ new Date(dashboardStore.dashboard.generated_at).toLocaleTimeString('zh-CN') }}</span
          >
        </div>
        <el-button
          :loading="dashboardStore.state === 'loading' || showRefreshFlash"
          @click="refresh(true)"
          ><Refresh /> 刷新数据</el-button
        >
      </div>
      <nav class="student-section-nav" role="tablist" aria-label="学生工作区">
        <button
          v-for="(item, index) in navItems"
          :id="`student-tab-${item.target}`"
          :key="item.target"
          type="button"
          role="tab"
          :class="{ active: activeView === item.target }"
          :aria-selected="activeView === item.target"
          aria-controls="student-task-panel"
          :tabindex="activeView === item.target ? 0 : -1"
          @click="navigateTo(item.target)"
          @keydown="navigateWithKeyboard($event, index)"
        >
          <component :is="item.icon" />
          <span class="student-nav-copy"
            ><b>{{ item.label }}</b></span
          >
        </button>
      </nav>

      <section v-if="checkError" class="recovery-notice" role="alert" aria-label="检查恢复提示">
        <div>
          <strong>下一步如何继续</strong>
          <p>{{ checkError.message }}</p>
        </div>
        <el-button type="primary" :loading="dashboardStore.workflowLoading" @click="recoverCheck">{{
          recoveryLabel
        }}</el-button>
      </section>
      <el-skeleton
        v-if="dashboardStore.state === 'loading'"
        :rows="10"
        animated
        class="dashboard-skeleton"
      />
      <el-result
        v-else-if="dashboardStore.state === 'error' && !dashboardStore.dashboard"
        icon="error"
        title="数据加载失败"
        :sub-title="dashboardStore.errorMessage"
      >
        <template #extra
          ><el-button v-if="mustLogin" type="primary" @click="logout">重新登录</el-button
          ><el-button v-else type="primary" :disabled="showRefreshFlash" @click="refresh(true)"
            >重新加载</el-button
          ></template
        >
      </el-result>
      <div v-else-if="dashboardStore.dashboard" class="dashboard-content">
        <section
          v-if="dashboardStore.failureKind"
          class="recovery-notice"
          role="alert"
          aria-label="数据暂未更新"
        >
          <div>
            <strong>暂未更新 · 当前内容仅供查看</strong>
            <p>{{ dashboardStore.errorMessage }}</p>
            <p>
              上次成功读取：{{
                new Date(dashboardStore.dashboard.generated_at).toLocaleString('zh-CN')
              }}。这不是设备的最新采样时间。
            </p>
          </div>
          <el-button type="primary" :disabled="showRefreshFlash" @click="refresh(true)"
            >重新连接并刷新</el-button
          >
        </section>
        <el-alert
          v-if="hasTestData"
          title="当前展示测试或模拟数据，不代表真实设备诊断结果。"
          type="warning"
          :closable="false"
          show-icon
        />
        <section class="experiment-context" aria-label="本次实验与数据时间">
          <div>
            <strong>{{ dashboardStore.dashboard.task.title || '当前实验任务待配置' }}</strong
            ><span>{{ deviceLabel }} · {{ deviceStatus }}</span>
          </div>
          <p>
            最近心跳：{{
              dashboardStore.dashboard.device.last_seen_at
                ? new Date(dashboardStore.dashboard.device.last_seen_at).toLocaleString('zh-CN')
                : '尚未上报'
            }}
            · 最新展示读数记录：{{ latestReadingAt }}
          </p>
          <small>通信状态不代表硬件正常；记录时间不等于现场已复测。</small>
        </section>
        <section
          v-if="dashboardStore.checkPending && activeView !== 'work'"
          class="recovery-notice"
          role="status"
          aria-label="检查结果待确认"
        >
          <p>上次检查结果尚未确认，切换页面不会重新提交。</p>
          <el-button @click="navigateTo('work')">返回当前实验确认原请求</el-button>
        </section>
        <fieldset class="feedback-recovery-wrapper" :disabled="readOnly">
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
        </fieldset>
        <section
          id="student-task-panel"
          role="tabpanel"
          :aria-labelledby="`student-tab-${activeView}`"
          tabindex="0"
        >
          <section
            v-show="activeView === 'data'"
            class="student-data-workspace"
            aria-label="实验数据记录"
          >
            <div class="data-workspace-heading">
              <h2>数据记录</h2>
              <p>这里展示已上传的数据；切换页面不会启动检查。</p>
            </div>
            <details class="experiment-details">
              <summary>实验与设备详情</summary>
              <DeviceOverview
                :task="dashboardStore.dashboard.task"
                :device="dashboardStore.dashboard.device"
              />
            </details>
            <div class="student-data-grid">
              <RealtimeLogList :logs="dashboardStore.dashboard.logs" />
              <SensorTrendChart
                v-if="activeView === 'data'"
                :readings="dashboardStore.dashboard.readings"
              />
            </div>
          </section>
          <section
            v-if="showObservationChart"
            class="observation-preview"
            aria-label="当前实验读数"
          >
            <p>
              当前展示的读数可用于观察实验；最新记录时间见上方。未发现异常不代表整套硬件验收通过。
            </p>
            <SensorTrendChart :readings="dashboardStore.dashboard.readings" />
          </section>
          <DiagnosisPanel
            v-show="activeView !== 'data'"
            :view="activeView === 'reference' ? 'reference' : 'work'"
            :read-only="readOnly"
            :issues="dashboardStore.dashboard.issues"
            :diagnosis="dashboardStore.dashboard.diagnosis"
            :guidance="dashboardStore.dashboard.guidance"
            :feedback="dashboardStore.dashboard.feedback"
            :intervention="dashboardStore.dashboard.intervention"
            :interventions="dashboardStore.dashboard.interventions"
            :feedback-loading="dashboardStore.feedbackLoading"
            :feedback-blocked="dashboardStore.feedbackBlocked"
            :ai-status="dashboardStore.dashboard.ai_status"
            :ai-explanation="dashboardStore.dashboard.ai_explanation"
            :ai-loading="dashboardStore.aiLoading"
            :workflow="dashboardStore.workflow"
            :workflow-loading="dashboardStore.workflowLoading"
            :check-pending="dashboardStore.checkPending"
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

<style scoped>
.task-organized-student .content-toolbar {
  min-height: 0;
  padding: 26px 0 22px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}
.task-organized-student .content-toolbar::after {
  display: none;
}
.task-organized-student .content-toolbar h1 {
  font-size: clamp(26px, 4vw, 34px);
}
.task-organized-student .content-toolbar > div {
  padding: 0;
}
.task-organized-student .content-toolbar > .el-button {
  margin: 0;
  min-height: 42px;
}
.task-organized-student .student-section-nav {
  margin-bottom: 18px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  overflow: visible;
}
.task-organized-student .student-section-nav button {
  min-height: 52px;
  padding: 12px;
  gap: 8px;
}
.task-organized-student .student-nav-copy b {
  font-size: 14px;
}
.experiment-context {
  padding: 18px 0;
  border-bottom: 1px solid var(--studio-line);
  margin-bottom: 18px;
  overflow-wrap: anywhere;
}
.experiment-context > div {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
}
.experiment-context p {
  font-size: 13px;
  line-height: 1.7;
  margin: 10px 0 4px;
}
.experiment-context small {
  color: #63665f;
  line-height: 1.6;
}
.student-data-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 24px;
  margin-top: 20px;
}
.student-data-grid :deep(.panel-card),
.observation-preview :deep(.panel-card) {
  grid-column: auto;
  min-height: 0;
  margin: 0;
  padding: 0;
  border-right: 0;
}
.student-data-grid :deep(.log-list),
.student-data-grid :deep(.sensor-chart) {
  height: 280px;
}
.student-data-grid :deep(.el-empty) {
  padding: 28px 10px;
}
.data-workspace-heading h2 {
  margin: 6px 0;
  font-size: 22px;
}
.data-workspace-heading p,
.observation-preview > p {
  color: #555;
  line-height: 1.7;
  font-size: 14px;
}
.experiment-details {
  border: 1px solid var(--studio-line);
  margin: 20px 0;
  padding: 16px;
}
.experiment-details summary {
  cursor: pointer;
  font-weight: 600;
}
.experiment-details :deep(.overview-grid) {
  margin: 16px 0 0;
}
.experiment-details :deep(.task-card),
.experiment-details :deep(.device-card) {
  min-height: 0;
  padding: 16px;
}
.experiment-details :deep(.task-icon) {
  display: none;
}
.experiment-details :deep(.task-card) {
  display: block;
}
.observation-preview {
  margin: 20px 0;
}
@media (max-width: 680px) {
  .task-organized-student .content-toolbar {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .task-organized-student .content-toolbar > .el-button {
    width: auto;
  }
  .task-organized-student .student-section-nav button {
    padding: 10px 6px;
  }
  .student-data-grid {
    grid-template-columns: 1fr;
  }
  .experiment-context > div {
    flex-direction: column;
  }
}

.topbar-user :deep(.el-button) {
  width: auto;
  min-width: max-content;
  padding: 0 12px;
}

.recovery-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 18px;
  padding: 20px;
  margin: 18px 0;
  border: 1px solid #d2b771;
  background: #fff9e9;
  color: #534626;
}
.recovery-notice p {
  margin: 8px 0 0;
  font-size: 14px;
  line-height: 1.7;
}
.recovery-notice :deep(.el-button) {
  margin: 0;
}
.feedback-recovery-wrapper {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
</style>
