<script setup lang="ts">
import { issueLabel, readableText, logLevel, logSummary } from '@/presentation/userLanguage'
import {
  Bell,
  Cpu,
  DataAnalysis,
  HomeFilled,
  Management,
  Monitor,
  Refresh,
  Search,
  SwitchButton,
  TrendCharts,
  UserFilled,
  Warning,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { pendingInterventionCommand, reportTeacherProblemResolved } from '@/api/teacher'
import ManagedExperimentSessions from '@/components/ManagedExperimentSessions.vue'
import TeacherDeviceChart from '@/components/TeacherDeviceChart.vue'
import TeacherErrorRankingChart from '@/components/TeacherErrorRankingChart.vue'
import TeacherErrorTrendChart from '@/components/TeacherErrorTrendChart.vue'
import WorkflowEvidenceSummary from '@/components/WorkflowEvidenceSummary.vue'
import { REVIEW_MODE } from '@/review/fixtures'
import { useTeacherDashboardStore } from '@/stores/teacherDashboard'
import { useTeacherSessionStore } from '@/stores/teacherSession'
import type { TeacherDiagnosisWorkflow, TeacherIntervention } from '@/types/teacher'

const router = useRouter()
const sessionStore = useTeacherSessionStore()
const dashboardStore = useTeacherDashboardStore()
const activeNavTarget = ref('class-handling')
const sectionPositions: Record<string, number> = {}
const expandedInterventionKey = ref<string | null>(null)
const sessionManagementOpen = ref(false)
const sessionManagementStatus = ref({ pendingCount: 0, error: '', loading: false })
function updateSessionManagementStatus(status: typeof sessionManagementStatus.value): void {
  sessionManagementStatus.value = status
  if (status.pendingCount > 0 || status.error) sessionManagementOpen.value = true
}
async function openSessionManagement(): Promise<void> {
  await navigateTo('class-handling')
  sessionManagementOpen.value = true
  await nextTick()
  const panel = document.getElementById('teacher-session-management')
  panel?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  panel?.querySelector('summary')?.focus({ preventScroll: true })
}
const showRefreshFlash = ref(false)
const searchQuery = ref('')
const selectedDeviceId = ref('')
let deviceListScrollPosition = 0
const expandedWorkflowId = ref<string | null>(null)
let refreshTimer: number | undefined

const dashboard = computed(() => dashboardStore.dashboard)
const filteredAnomalies = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return dashboard.value?.anomalies ?? []
  return (dashboard.value?.anomalies ?? []).filter((item) =>
    [
      item.device_id,
      item.device_name,
      item.latest_error_code,
      issueLabel(item.latest_error_code),
      item.latest_summary,
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query)),
  )
})
const selectedDevice = computed(
  () => selectedDeviceId.value || filteredAnomalies.value[0]?.device_id || '',
)
const selectedLogs = computed(() => {
  const logs = dashboard.value?.recent_logs ?? []
  return selectedDevice.value ? logs.filter((item) => item.device_id === selectedDevice.value) : []
})
const hasTestData = computed(() =>
  Boolean(
    dashboard.value?.anomalies.some((item) => item.is_test_data) ||
    dashboard.value?.recent_logs.some((item) => item.is_test_data) ||
    dashboard.value?.interventions.some((item) => item.is_test_data),
  ),
)
const workflowMetrics = computed(() => dashboardStore.workflowMetrics)
const workflowInProgressOrOtherCount = computed(() => {
  const metrics = workflowMetrics.value
  if (!metrics) return 0
  if (typeof metrics.in_progress === 'number' && Number.isFinite(metrics.in_progress)) {
    return Math.max(0, metrics.in_progress)
  }
  const terminalOrWaiting =
    (metrics.completed ?? 0) +
    (metrics.waiting_teacher ?? 0) +
    (metrics.rejected ?? 0) +
    (metrics.failed ?? 0)
  return Math.max(0, (metrics.total ?? 0) - terminalOrWaiting)
})

const navItems = [
  { label: '课堂处置', description: '求助与异常', target: 'class-handling', icon: Warning },
  { label: '课堂概览', description: '设备与趋势', target: 'class-overview', icon: DataAnalysis },
  {
    label: '资料与审核',
    description: '诊断审核与知识',
    target: 'class-resources',
    icon: Management,
  },
]
const activeSection = computed(() =>
  navItems.find((item) => item.target === activeNavTarget.value)!,
)
const pendingInterventionCount = computed(
  () =>
    (dashboard.value?.interventions ?? []).filter((item) =>
      ['open', 'claimed', 'unconfirmed', 'recommended'].includes(item.status),
    ).length,
)
function interventionKey(item: TeacherIntervention): string {
  return item.case_id ?? `${item.diagnosis_result_id}:${item.episode_id ?? item.tree_title}`
}
function toggleIntervention(item: TeacherIntervention): void {
  const key = interventionKey(item)
  expandedInterventionKey.value = expandedInterventionKey.value === key ? null : key
}

async function refresh(showTransition = false): Promise<void> {
  if (!sessionStore.accessToken) return
  if (showTransition && showRefreshFlash.value) return

  const startedAt = window.performance.now()
  if (showTransition) showRefreshFlash.value = true

  try {
    await dashboardStore.load(sessionStore.accessToken)
  } finally {
    if (showTransition) {
      const remainingTime = Math.max(0, 460 - (window.performance.now() - startedAt))
      await new Promise((resolve) => window.setTimeout(resolve, remainingTime))
      showRefreshFlash.value = false
    }
  }
}
async function navigateTo(target: string): Promise<void> {
  if (target === activeNavTarget.value) return
  sectionPositions[activeNavTarget.value] = window.scrollY
  activeNavTarget.value = target
  await nextTick()
  window.scrollTo({ top: sectionPositions[target] ?? 0, behavior: 'instant' })
}
function navigateWithKeyboard(event: KeyboardEvent, index: number): void {
  const offsets: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1 }
  let nextIndex: number
  if (event.key === 'Home') nextIndex = 0
  else if (event.key === 'End') nextIndex = navItems.length - 1
  else if (event.key in offsets)
    nextIndex = (index + offsets[event.key]! + navItems.length) % navItems.length
  else return
  event.preventDefault()
  const target = navItems[nextIndex]!.target
  void navigateTo(target)
  document.getElementById(`teacher-tab-${target}`)?.focus()
}
async function selectDevice(deviceId: string): Promise<void> {
  deviceListScrollPosition = window.scrollY
  selectedDeviceId.value = deviceId
  await navigateTo('class-handling')
  await nextTick()
  document
    .getElementById('device-log-detail')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function returnToDeviceList(): void {
  window.scrollTo({ top: deviceListScrollPosition, behavior: 'smooth' })
  document
    .querySelector<HTMLElement>('#anomaly-list .device-selection-button[aria-pressed="true"]')
    ?.focus({ preventScroll: true })
}
function toggleWorkflow(workflowId: string): void {
  expandedWorkflowId.value = expandedWorkflowId.value === workflowId ? null : workflowId
}
function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}
function reviewActionLabel(action: 'approve' | 'edit' | 'reject'): string {
  return { approve: '批准', edit: '修订', reject: '驳回' }[action]
}
function latestReview(item: TeacherDiagnosisWorkflow) {
  const reviews = item.reviews ?? []
  return reviews[reviews.length - 1]
}
const interventionStatusLabels: Record<TeacherIntervention['status'], string> = {
  open: '待认领',
  claimed: '处理中',
  resolved: '处理完成',
  unconfirmed: '待补充证据',
  closed: '已关闭',
  recommended: '建议介入',
}

async function reportProblemResolved(item: TeacherIntervention): Promise<void> {
  if (
    !sessionStore.session ||
    !sessionStore.accessToken ||
    !item.case_id ||
    item.evidence_revision == null
  )
    return
  const actingToken = sessionStore.accessToken
  const actingUser = sessionStore.session.user_id
  try {
    await ElMessageBox.confirm(
      '记录教师报告的问题已解决。这不会声明硬件已通过复测，也不会自动关闭工单。若上次请求未确认，将继续确认原请求。',
      '报告问题状态',
      {
        confirmButtonText: '记录教师报告',
        cancelButtonText: '取消',
      },
    )
    if (sessionStore.accessToken !== actingToken) return
    await reportTeacherProblemResolved(
      actingToken,
      actingUser,
      item.case_id,
      item.evidence_revision,
    )
    if (sessionStore.accessToken !== actingToken) return
    await dashboardStore.load(actingToken)
    if (sessionStore.accessToken !== actingToken) return
    ElMessage.success('问题状态已记录，工单处理状态保持独立')
  } catch (error) {
    if (sessionStore.accessToken !== actingToken || error === 'cancel' || error === 'close') return
    ElMessage.error('结果尚未确认或证据已更新，请刷新并核对原请求；不要重复提交新请求。')
  }
}

async function handleIntervention(item: TeacherIntervention): Promise<void> {
  if (!sessionStore.accessToken || !item.case_id || item.version_no === null) return
  const actingToken = sessionStore.accessToken
  try {
    const pending =
      sessionStore.session && pendingInterventionCommand(sessionStore.session.user_id, item.case_id)
    if (pending) {
      await ElMessageBox.confirm(
        '此工单有一次结果尚未确认的操作。将查询或继续原操作，不会发起新的处理。',
        '确认上次工单操作',
        {
          confirmButtonText: '确认原操作',
          cancelButtonText: '取消',
        },
      )
      if (!(await dashboardStore.act(actingToken, item.case_id, pending.payload))) return
      ElMessage.success('原操作已确认，请查看最新工单状态')
      return
    }
    if (item.status === 'open') {
      if (
        !(await dashboardStore.act(actingToken, item.case_id, {
          action: 'claim',
          expected_version: item.version_no,
          is_private: false,
        }))
      )
        return
      ElMessage.success('已认领该学生求助')
      return
    }
    if (item.status === 'claimed') {
      const result = await ElMessageBox.prompt(
        '请填写将同步给学生的处理结果。',
        '完成教师协助工单',
        {
          confirmButtonText: '标记处理完成',
          cancelButtonText: '取消',
          inputPlaceholder: '例如：已指导重新连接传感器并确认读数恢复',
          inputValidator: (value) => Boolean(value.trim()) || '请填写处理结果',
        },
      )
      if (
        !(await dashboardStore.act(actingToken, item.case_id, {
          action: 'resolve',
          expected_version: item.version_no,
          note: result.value.trim(),
          is_private: false,
        }))
      )
        return
      ElMessage.success('处理结果已同步给学生')
      return
    }
    if (item.status === 'resolved' || item.status === 'unconfirmed') {
      await ElMessageBox.confirm('关闭后该工单将保留在历史记录中。', '关闭教师协助工单', {
        confirmButtonText: '确认关闭',
        cancelButtonText: '取消',
        type: 'warning',
      })
      if (
        !(await dashboardStore.act(actingToken, item.case_id, {
          action: 'close',
          expected_version: item.version_no,
          is_private: false,
        }))
      )
        return
      ElMessage.success('工单已关闭')
    }
  } catch (error) {
    if (sessionStore.accessToken !== actingToken || error === 'cancel' || error === 'close') return
    ElMessage.error('工单操作失败，可能已被其他教师更新，请刷新后重试')
  }
}
async function handleWorkflowReview(
  workflowId: string,
  action: 'approve' | 'edit' | 'reject',
): Promise<void> {
  if (!sessionStore.accessToken) return
  const actingToken = sessionStore.accessToken
  try {
    const result = await ElMessageBox.prompt(
      action === 'approve'
        ? '可填写本次审核说明。'
        : action === 'edit'
          ? '请填写修订后的诊断总结。规则证据和提示层级不会被修改。'
          : '请填写驳回原因。',
      action === 'approve' ? '批准诊断解释' : action === 'edit' ? '修订诊断解释' : '驳回诊断解释',
      {
        confirmButtonText: action === 'approve' ? '批准' : action === 'edit' ? '保存修订' : '驳回',
        cancelButtonText: '取消',
        inputPlaceholder:
          action === 'approve'
            ? '审核说明（可选）'
            : action === 'edit'
              ? '修订后的诊断总结'
              : '需要补充的证据',
        inputValidator: (value) => action === 'approve' || Boolean(value.trim()) || '请填写内容',
      },
    )
    if (
      !(await dashboardStore.reviewWorkflow(
        actingToken,
        workflowId,
        action === 'edit'
          ? {
              action,
              comment: '教师修订了自然语言诊断总结',
              edited_result: {
                summary: result.value.trim(),
              },
            }
          : { action, comment: result.value.trim() || undefined },
      ))
    )
      return
    ElMessage.success(
      action === 'approve' ? '诊断已批准' : action === 'edit' ? '诊断已修订并批准' : '诊断已驳回',
    )
  } catch (error) {
    if (sessionStore.accessToken !== actingToken || error === 'cancel' || error === 'close') return
    ElMessage.error('诊断审核失败，请刷新后重试')
  }
}
async function logout(): Promise<void> {
  sessionStore.logout()
  dashboardStore.clear()
  await router.replace('/teacher/login')
}
onMounted(() => {
  void refresh()
  refreshTimer = window.setInterval(() => void refresh(), 30_000)
})
onBeforeUnmount(() => {
  window.clearInterval(refreshTimer)
})
</script>

<template>
  <main class="teacher-app">
    <Transition name="workspace-refresh">
      <div
        v-if="showRefreshFlash"
        class="workspace-refresh-flash"
        role="status"
        aria-label="正在刷新教师端数据"
      />
    </Transition>
    <header class="teacher-topbar">
      <div class="teacher-brand">
        <Cpu />
        <div><strong>芯鉴知微</strong><small>嵌入式实验智能分析平台</small></div>
        <b>教师端</b>
      </div>
      <div class="teacher-breadcrumb">
        <HomeFilled /><span>/</span><b>{{ activeSection.label }}</b>
      </div>
      <button type="button" class="teacher-icon-button" aria-label="通知"><Bell /></button>
      <div class="teacher-user">
        <span><UserFilled /></span>
        <div>
          <strong>{{ sessionStore.session?.display_name || '教师账号' }}</strong>
          <small>教师账号会话</small>
        </div>
      </div>
      <button type="button" class="teacher-icon-button" aria-label="退出教师端" @click="logout">
        <SwitchButton />
      </button>
    </header>

    <aside class="teacher-sidebar">
      <nav role="tablist" aria-label="教师端导航">
        <button
          v-for="(item, index) in navItems"
          :key="item.target"
          :id="`teacher-tab-${item.target}`"
          type="button"
          role="tab"
          :aria-selected="activeNavTarget === item.target"
          :aria-controls="item.target"
          :aria-label="item.label"
          :tabindex="activeNavTarget === item.target ? 0 : -1"
          @keydown="navigateWithKeyboard($event, index)"
          :class="{ active: activeNavTarget === item.target }"
          :title="`${item.label}：${item.description}`"
          @click="navigateTo(item.target)"
        >
          <component :is="item.icon" />
          <span class="teacher-nav-copy"
            ><b>{{ item.label }}</b
            ><small>{{ item.description }}</small></span
          >
        </button>
      </nav>
    </aside>

    <section class="teacher-content">
      <el-skeleton
        v-if="dashboardStore.state === 'loading'"
        :rows="14"
        animated
        class="teacher-loading"
      />
      <el-result
        v-else-if="dashboardStore.state === 'error'"
        icon="error"
        title="教师端数据加载失败"
        :sub-title="dashboardStore.errorMessage"
      >
        <template #extra
          ><el-button type="primary" @click="refresh(true)">重新加载</el-button></template
        >
      </el-result>
      <template v-else-if="dashboard">
        <header class="teacher-hero">
          <div>
            <p>教师工作台</p>
            <h1>{{ activeSection.label }}</h1>
            <span>当前账号获授权的课堂范围 · {{ activeSection.description }}</span>
          </div>
          <div class="teacher-task-counts" aria-label="当前课堂事项">
            <span
              ><b>{{ pendingInterventionCount }}</b
              >项求助或介入待处理</span
            >
            <span
              ><b>{{ dashboard.metrics.abnormal_devices }}</b
              >台设备需关注</span
            >
            <button type="button" @click="navigateTo('class-resources')">
              <b>{{
                dashboardStore.workflowSections.queue.state === 'ready'
                  ? dashboardStore.workflowQueue.length
                  : '—'
              }}</b
              >项诊断待审核
            </button>
          </div>
        </header>
        <div class="teacher-notice" :class="{ warning: hasTestData }">
          <Warning /><span>{{ dashboard.data_notice }}</span
          ><button type="button" :disabled="showRefreshFlash" @click="refresh(true)">
            <Refresh />刷新
          </button>
        </div>
        <section
          v-if="
            sessionManagementStatus.pendingCount > 0 ||
            sessionManagementStatus.error ||
            sessionManagementStatus.loading
          "
          class="teacher-recovery-notice"
          role="status"
          aria-label="设备交接恢复提示"
        >
          <div>
            <strong v-if="sessionManagementStatus.pendingCount > 0"
              >有 {{ sessionManagementStatus.pendingCount }} 项设备交接操作待确认</strong
            >
            <strong v-else-if="sessionManagementStatus.error">设备交接状态需要核对</strong>
            <strong v-else>正在核对设备交接记录</strong>
            <p v-if="sessionManagementStatus.error">{{ sessionManagementStatus.error }}</p>
            <p v-else-if="sessionManagementStatus.pendingCount > 0">
              请继续确认原操作；切换栏目不会重新提交。
            </p>
          </div>
          <button
            v-if="!sessionManagementStatus.loading"
            type="button"
            @click="openSessionManagement"
          >
            {{
              sessionManagementStatus.pendingCount > 0 ? '查看待确认的设备交接' : '查看设备交接状态'
            }}
          </button>
        </section>
        <section
          id="class-handling"
          v-show="activeNavTarget === 'class-handling'"
          class="teacher-task-panel"
          role="tabpanel"
          aria-labelledby="teacher-tab-class-handling"
        >
          <article class="teacher-panel intervention-panel classroom-interventions">
            <header>
              <h2>学生求助与教学介入</h2>
              <i>{{ dashboard.interventions.length }}</i>
            </header>
            <div v-if="dashboard.interventions.length" class="teacher-action-list">
              <article
                v-for="item in dashboard.interventions"
                :key="interventionKey(item)"
                class="intervention-record"
              >
                <button
                  type="button"
                  class="intervention-summary"
                  :aria-expanded="expandedInterventionKey === interventionKey(item)"
                  @click="toggleIntervention(item)"
                >
                  <span
                    ><b>{{ item.device_id }}</b
                    ><small>{{ item.tree_title }}</small></span
                  >
                  <span>
                    <small>{{
                      item.source === 'student_request'
                        ? '学生主动求助'
                        : item.source === 'automatic_guidance'
                          ? '系统建议介入'
                          : '人工创建'
                    }}</small>
                    <time>{{
                      new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })
                    }}</time>
                  </span>
                  <span
                    ><em :class="`intervention-${item.status}`">{{
                      interventionStatusLabels[item.status]
                    }}</em
                    ><small v-if="item.is_test_data">测试/模拟</small
                    ><small>{{
                      expandedInterventionKey === interventionKey(item) ? '收起详情' : '查看详情'
                    }}</small></span
                  >
                </button>
                <div
                  v-show="expandedInterventionKey === interventionKey(item)"
                  class="intervention-details"
                >
                  <p>当前记录未提供学生明确执行过的步骤；提示或“仍未解决”反馈不等于已经执行。</p>
                  <p>工单处理完成、问题报告解决与硬件恢复分别记录。</p>
                  <p v-if="item.resolution_summary">处理说明：{{ item.resolution_summary }}</p>
                  <div class="intervention-action-copy">
                    <small v-if="item.episode_id"
                      >问题：{{
                        item.problem_status === 'resolved' ? '已报告解决' : '待处理'
                      }}</small
                    >
                    <el-button
                      v-if="item.case_id && item.episode_id && item.problem_status !== 'resolved'"
                      size="small"
                      :disabled="REVIEW_MODE"
                      :title="REVIEW_MODE ? '离线演示不支持真实问题状态变更' : undefined"
                      @click.stop="reportProblemResolved(item)"
                      >报告问题已解决</el-button
                    >
                    <el-button
                      v-if="
                        item.case_id &&
                        ['open', 'claimed', 'resolved', 'unconfirmed'].includes(item.status)
                      "
                      size="small"
                      :type="item.status === 'claimed' ? 'success' : 'primary'"
                      :loading="dashboardStore.actionLoadingCaseId === item.case_id"
                      @click.stop="handleIntervention(item)"
                    >
                      {{
                        item.status === 'open'
                          ? '认领'
                          : item.status === 'claimed'
                            ? '处理完成'
                            : '关闭'
                      }}
                    </el-button>
                  </div>
                  <button
                    type="button"
                    class="device-selection-button"
                    @click="selectDevice(item.device_id)"
                  >
                    查看该设备日志
                  </button>
                </div>
              </article>
            </div>
            <p v-else class="teacher-compact-empty">当前没有学生求助或教学介入记录。</p>
          </article>
          <label class="teacher-search"
            ><input
              v-model="searchQuery"
              aria-label="搜索异常设备或错误代码"
              placeholder="搜索设备或错误代码…" /><Search
          /></label>
          <section id="anomaly-workbench" class="teacher-detail-grid">
            <article id="anomaly-list" class="teacher-panel anomaly-table-panel">
              <header>
                <h2>
                  设备异常列表 <i>{{ filteredAnomalies.length }}</i>
                </h2>
                <small>
                  {{
                    filteredAnomalies.some((item) => item.student_identity_configured)
                      ? '归属以服务器授权记录为准'
                      : '未建立学生归属关系'
                  }}
                </small>
              </header>
              <div v-if="filteredAnomalies.length" class="teacher-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>设备</th>
                      <th>异常类型</th>
                      <th>状态</th>
                      <th>数据来源</th>
                      <th>处理建议</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="item in filteredAnomalies"
                      :key="item.device_id"
                      :class="{ selected: selectedDevice === item.device_id }"
                    >
                      <td>
                        <button
                          type="button"
                          class="device-selection-button"
                          :aria-pressed="selectedDevice === item.device_id"
                          @click="selectDevice(item.device_id)"
                        >
                          {{ item.device_name || item.device_id }}</button
                        ><small>{{ item.device_id }}</small>
                      </td>
                      <td>
                        <span>{{ issueLabel(item.latest_error_code) }}</span>
                        <details>
                          <summary>查看编号</summary>
                          <code>{{ item.latest_error_code }}</code>
                        </details>
                      </td>
                      <td><span class="status-badge danger">待核查</span></td>
                      <td>
                        <span
                          class="status-badge"
                          :class="item.is_test_data ? 'warning' : 'success'"
                          >{{ item.is_test_data ? '测试/模拟' : '未标记测试' }}</span
                        >
                      </td>
                      <td>{{ readableText(item.latest_summary) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p v-else class="teacher-compact-empty">
                {{
                  searchQuery
                    ? '没有匹配的异常设备，请调整搜索内容。'
                    : '当前没有规则命中的异常设备；这不代表已完成硬件验收。'
                }}
              </p>
            </article>

            <article id="device-log-detail" class="teacher-panel teacher-log-panel">
              <header>
                <h2>单个设备日志详情</h2>
                <small>{{ selectedDevice || '未选择设备' }}</small>
              </header>
              <button
                v-if="selectedDeviceId"
                type="button"
                class="device-selection-button"
                @click="returnToDeviceList"
              >
                返回异常列表
              </button>
              <div v-if="selectedLogs.length" class="teacher-log-list">
                <div v-for="log in selectedLogs" :key="log.id" class="teacher-log-row">
                  <time :datetime="log.occurred_at">{{
                    new Date(log.occurred_at).toLocaleTimeString('zh-CN', { hour12: false })
                  }}</time>
                  <div class="teacher-log-content">
                    <div class="teacher-log-meta">
                      <span class="teacher-log-level" :class="`log-${log.level.toLowerCase()}`">
                        {{ logLevel(log.level) }}
                      </span>
                      <span>{{ logSummary(log) }}</span>
                    </div>
                    <details>
                      <summary>查看原始日志</summary>
                      <code>{{ log.level }} · {{ log.event_code }}</code>
                      <p>{{ log.message }}</p>
                    </details>
                  </div>
                </div>
              </div>
              <p v-else class="teacher-compact-empty">
                {{ selectedDevice ? '该设备暂无日志。' : '选择设备后查看对应日志。' }}
              </p>
            </article>
          </section>
          <details
            v-if="
              !REVIEW_MODE &&
              sessionStore.session?.permissions.includes('assignment.manage') &&
              sessionStore.accessToken
            "
            id="teacher-session-management"
            class="teacher-management-details"
            :open="sessionManagementOpen"
            @toggle="sessionManagementOpen = ($event.target as HTMLDetailsElement).open"
          >
            <summary>管理实验会话与设备交接</summary>
            <ManagedExperimentSessions
              :access-token="sessionStore.accessToken"
              :user-id="sessionStore.session.user_id"
              @status-change="updateSessionManagementStatus"
            />
          </details>
        </section>
        <section
          id="class-overview"
          v-show="activeNavTarget === 'class-overview'"
          class="teacher-task-panel"
          role="tabpanel"
          aria-labelledby="teacher-tab-class-overview"
        >
          <section class="teacher-kpis" aria-label="设备统计概览">
            <article class="teacher-kpi kpi-blue">
              <span><Monitor /></span>
              <div>
                <small>在线设备数</small><strong>{{ dashboard.metrics.online_devices }}</strong
                ><em>实时数据库</em>
              </div>
            </article>
            <article class="teacher-kpi kpi-cyan">
              <span><Cpu /></span>
              <div>
                <small>离线设备数</small><strong>{{ dashboard.metrics.offline_devices }}</strong
                ><em>超时阈值可配置</em>
              </div>
            </article>
            <article class="teacher-kpi kpi-orange">
              <span><Warning /></span>
              <div>
                <small>异常设备数</small><strong>{{ dashboard.metrics.abnormal_devices }}</strong
                ><em>最新规则诊断</em>
              </div>
            </article>
            <article class="teacher-kpi kpi-purple">
              <span><TrendCharts /></span>
              <div><small>实验完成率</small><strong>—</strong><em>任务数据未配置</em></div>
            </article>
          </section>

          <section id="device-analysis" class="teacher-chart-grid">
            <article id="device-status" class="teacher-panel">
              <header>
                <h2>设备状态图</h2>
                <small>当前快照</small>
              </header>
              <TeacherDeviceChart
                v-if="activeNavTarget === 'class-overview'"
                :data="dashboard.device_status"
              />
            </article>
            <article class="teacher-panel">
              <header>
                <h2>高频错误排行</h2>
                <small>各设备最新诊断</small>
              </header>
              <TeacherErrorRankingChart
                v-if="activeNavTarget === 'class-overview'"
                :data="dashboard.error_ranking"
              />
            </article>
            <article class="teacher-panel">
              <header>
                <h2>错误趋势图</h2>
                <small>近 7 天</small>
              </header>
              <TeacherErrorTrendChart
                v-if="activeNavTarget === 'class-overview'"
                :data="dashboard.error_trend"
              />
            </article>
          </section>

          <p id="class-progress" class="teacher-compact-empty">
            <b>班级实验进度：</b>{{ dashboard.class_progress.notice }}
          </p>
        </section>
        <section
          id="class-resources"
          v-show="activeNavTarget === 'class-resources'"
          class="teacher-task-panel teacher-resource-stack"
          role="tabpanel"
          aria-labelledby="teacher-tab-class-resources"
        >
          <p class="teacher-section-note">
            诊断解释审核、工单处理与正式案例审核各自独立。批准解释不代表确认硬件恢复或发布正式案例。
          </p>
          <article class="teacher-panel intervention-panel">
            <header>
              <h2>诊断解释审核</h2>
              <i>{{
                dashboardStore.workflowSections.queue.state === 'ready'
                  ? dashboardStore.workflowQueue.length
                  : '—'
              }}</i>
            </header>
            <p
              v-if="dashboardStore.workflowSections.queue.state === 'error'"
              role="alert"
              class="teacher-compact-empty"
            >
              审核队列读取失败，无法判断是否有记录。已有记录仅供参考。
              <router-link
                v-if="
                  ['unauthorized', 'forbidden'].includes(
                    dashboardStore.workflowSections.queue.failureKind || '',
                  )
                "
                to="/teacher/login"
                >权限已变化，请重新登录</router-link
              >
              <el-button v-else size="small" @click="refresh">重新读取</el-button>
            </p>
            <p
              v-else-if="dashboardStore.workflowSections.queue.state === 'loading'"
              class="teacher-compact-empty"
            >
              正在读取审核队列…
            </p>
            <div v-if="dashboardStore.workflowQueue.length" class="teacher-action-list">
              <article
                v-for="item in dashboardStore.workflowQueue"
                :key="item.id"
                class="teacher-workflow-card"
              >
                <header>
                  <button
                    type="button"
                    :aria-expanded="expandedWorkflowId === item.id"
                    @click="toggleWorkflow(item.id)"
                  >
                    <b>{{ item.device_id }}</b>
                    <small>
                      需要教师确认 ·
                      {{ item.review_request?.candidates?.length ?? 0 }} 个可能原因 ·
                      {{
                        item.review_request?.retrieved_chunks?.filter(
                          (reference) => reference.metadata?.review_status === 'approved',
                        ).length ?? 0
                      }}
                      份已审核资料
                    </small>
                    <small class="intervention-source">
                      {{ expandedWorkflowId === item.id ? '收起诊断依据' : '查看诊断依据' }}
                    </small>
                  </button>
                  <div class="intervention-action-copy">
                    <el-button
                      size="small"
                      type="success"
                      :loading="dashboardStore.workflowReviewingId === item.id"
                      :disabled="dashboardStore.workflowSections.queue.state !== 'ready'"
                      @click.stop="handleWorkflowReview(item.id, 'approve')"
                      >批准</el-button
                    >
                    <el-button
                      size="small"
                      type="primary"
                      :loading="dashboardStore.workflowReviewingId === item.id"
                      :disabled="dashboardStore.workflowSections.queue.state !== 'ready'"
                      @click.stop="handleWorkflowReview(item.id, 'edit')"
                      >修订</el-button
                    >
                    <el-button
                      size="small"
                      type="danger"
                      :loading="dashboardStore.workflowReviewingId === item.id"
                      :disabled="dashboardStore.workflowSections.queue.state !== 'ready'"
                      @click.stop="handleWorkflowReview(item.id, 'reject')"
                      >驳回</el-button
                    >
                  </div>
                </header>
                <WorkflowEvidenceSummary v-if="expandedWorkflowId === item.id" :workflow="item" />
              </article>
            </div>
            <p
              v-else-if="dashboardStore.workflowSections.queue.state === 'ready'"
              class="teacher-compact-empty"
            >
              暂无等待审核的诊断。
            </p>
          </article>
          <article class="teacher-panel workflow-history-panel">
            <header>
              <h2>近期诊断审核历史</h2>
              <i>{{
                dashboardStore.workflowSections.history.state === 'ready'
                  ? dashboardStore.workflowHistory.length
                  : '—'
              }}</i>
            </header>
            <p
              v-if="dashboardStore.workflowSections.history.state === 'error'"
              role="alert"
              class="teacher-compact-empty"
            >
              审核历史读取失败，无法判断是否有记录。已有记录仅供参考。
              <router-link
                v-if="
                  ['unauthorized', 'forbidden'].includes(
                    dashboardStore.workflowSections.history.failureKind || '',
                  )
                "
                to="/teacher/login"
                >权限已变化，请重新登录</router-link
              >
              <el-button v-else size="small" @click="refresh">重新读取</el-button>
            </p>
            <p
              v-else-if="dashboardStore.workflowSections.history.state === 'loading'"
              class="teacher-compact-empty"
            >
              正在读取审核历史…
            </p>
            <div v-if="dashboardStore.workflowHistory.length" class="workflow-history-list">
              <article v-for="item in dashboardStore.workflowHistory" :key="item.id">
                <button
                  type="button"
                  :aria-expanded="expandedWorkflowId === item.id"
                  @click="toggleWorkflow(item.id)"
                >
                  <span>
                    <b>{{ item.device_id }}</b>
                    <small>{{
                      new Date(item.updated_at).toLocaleString('zh-CN', { hour12: false })
                    }}</small>
                  </span>
                  <em :class="`review-${latestReview(item)?.action || item.status}`">
                    {{
                      latestReview(item)
                        ? reviewActionLabel(latestReview(item)!.action)
                        : item.status
                    }}
                  </em>
                </button>
                <WorkflowEvidenceSummary v-if="expandedWorkflowId === item.id" :workflow="item" />
              </article>
            </div>
            <p
              v-else-if="dashboardStore.workflowSections.history.state === 'ready'"
              class="teacher-compact-empty"
            >
              暂无诊断审核历史。
            </p>
          </article>
          <article id="knowledge-review" class="teacher-panel knowledge-panel">
            <header>
              <h2>知识案例与审核状态</h2>
              <small>现有结构化知识</small>
            </header>
            <Management />
            <div>
              <b>{{ dashboard.knowledge_cases.configured ? '结构化案例可用' : '等待审核案例' }}</b>
              <p>{{ dashboard.knowledge_cases.notice }}</p>
              <p>
                案例 {{ dashboard.knowledge_cases.case_count ?? 0 }} · 已审核
                {{ dashboard.knowledge_cases.approved_case_count ?? 0 }} · 待审核
                {{ dashboard.knowledge_cases.pending_review_count ?? 0 }}
              </p>
            </div>
            <span class="knowledge-status-chip"
              >本页展示状态，案例审核操作通过现有审核接口进行</span
            >
          </article>
          <p v-if="dashboardStore.workflowSections.metrics.state === 'error'" role="alert">
            诊断统计读取失败，不能视为零。<el-button size="small" @click="refresh"
              >重新读取</el-button
            >
          </p>
          <details v-if="workflowMetrics" class="teacher-system-details">
            <summary>系统详情与诊断统计</summary>
            <p>沿用当前账号可读取的统计；已解决诊断比例不代表课堂通过率。</p>
            <div v-if="workflowMetrics" class="workflow-metric-strip" aria-label="诊断工作流指标">
              <span
                ><small>流程</small><b>{{ workflowMetrics.total ?? 0 }}</b></span
              >
              <span
                ><small>待审</small><b>{{ workflowMetrics.waiting_teacher ?? 0 }}</b></span
              >
              <span
                ><small>完成</small><b>{{ workflowMetrics.completed ?? 0 }}</b></span
              >
              <span
                ><small>驳回</small><b>{{ workflowMetrics.rejected ?? 0 }}</b></span
              >
              <span
                ><small>失败</small><b>{{ workflowMetrics.failed ?? 0 }}</b></span
              >
              <span
                ><small>运行中/其他</small><b>{{ workflowInProgressOrOtherCount }}</b></span
              >
              <span
                ><small>已审</small><b>{{ workflowMetrics.reviewed ?? 0 }}</b></span
              >
              <span
                ><small>修订率</small><b>{{ percent(workflowMetrics.edit_rate ?? 0) }}</b></span
              >
              <span
                ><small>驳回率</small><b>{{ percent(workflowMetrics.reject_rate ?? 0) }}</b></span
              >
              <span
                ><small>恢复</small><b>{{ workflowMetrics.resume_count ?? 0 }}</b></span
              >
              <span>
                <small>节点均耗时</small>
                <b>{{ workflowMetrics.average_node_duration_ms?.toFixed(1) ?? '—' }}ms</b>
              </span>
              <span
                ><small>AI 调用</small><b>{{ workflowMetrics.ai_call_count ?? 0 }}</b></span
              >
              <span>
                <small>模型用量（Token）</small>
                <b>{{
                  (workflowMetrics.ai_input_tokens ?? 0) + (workflowMetrics.ai_output_tokens ?? 0)
                }}</b>
              </span>
              <span>
                <small>估算成本（元）</small
                ><b>{{ (workflowMetrics.ai_estimated_cost ?? 0).toFixed(4) }}</b>
              </span>
              <span>
                <small>有反馈诊断</small>
                <b>{{ workflowMetrics.student_feedback_count ?? 0 }}</b>
              </span>
              <span>
                <small>已解决诊断</small>
                <b>{{ workflowMetrics.student_resolved_count ?? 0 }}</b>
              </span>
              <span>
                <small>按每个诊断最新反馈计算解决率</small>
                <b>{{
                  workflowMetrics.student_resolution_rate === null
                    ? '—'
                    : percent(workflowMetrics.student_resolution_rate)
                }}</b>
              </span>
            </div>
          </details>
        </section>
        <footer class="teacher-footer">
          <span>页面数据更新时间（不是采样时间）</span><span>每 30 秒读取一次</span
          ><time>{{ new Date(dashboard.generated_at).toLocaleString('zh-CN') }}</time>
        </footer>
      </template>
    </section>
  </main>
</template>

<style scoped>
.teacher-recovery-notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 20px 0;
  padding: 16px;
  border: 1px solid #c8a55a;
  background: #fff8e9;
  color: #5a451b;
}
.teacher-recovery-notice p {
  margin: 6px 0 0;
  font-size: 14px;
  line-height: 1.65;
}
.teacher-recovery-notice button {
  border: 1px solid currentColor;
  padding: 10px 14px;
  color: inherit;
  background: transparent;
  cursor: pointer;
}
#teacher-session-management {
  scroll-margin-top: 172px;
}
.teacher-content {
  padding-bottom: 40px;
}
.teacher-topbar {
  display: flex;
  gap: 16px;
}
.teacher-brand {
  margin-right: auto;
}
.teacher-hero {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 24px;
  padding: 24px 0 20px;
}
.teacher-hero::after {
  display: none;
}
.teacher-hero > div {
  grid-column: auto;
  padding: 0;
}
.teacher-hero h1 {
  font-size: clamp(1.6rem, 3vw, 2rem);
  line-height: 1.25;
}
.teacher-hero .teacher-task-counts {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px 18px;
  max-width: 410px;
  font-size: 13px;
}
.teacher-task-counts span,
.teacher-task-counts button {
  color: var(--studio-copy);
  font-size: inherit;
}
.teacher-task-counts b {
  margin-right: 6px;
  color: var(--studio-blue);
  font-size: 18px;
}
.teacher-task-counts button {
  border: 0;
  border-bottom: 1px solid var(--studio-line);
  background: transparent;
  padding: 0 0 4px;
  cursor: pointer;
}
.teacher-task-panel {
  min-width: 0;
  margin-top: 24px;
}
.teacher-panel {
  min-width: 0;
}
.teacher-panel > header {
  min-height: 52px;
  margin-bottom: 16px;
}
.classroom-interventions {
  margin-bottom: 28px;
}
.teacher-compact-empty,
.teacher-section-note {
  margin: 12px 0;
  color: var(--studio-copy);
  font-size: 14px;
  line-height: 1.7;
}
.teacher-search {
  display: flex;
  width: min(100%, 340px);
  margin: 0 0 20px;
}
.intervention-record {
  border: 1px solid var(--studio-line);
  min-width: 0;
}
.intervention-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  width: 100%;
  border: 0;
  padding: 16px;
  color: var(--studio-ink);
  text-align: left;
  background: transparent;
  cursor: pointer;
}
.intervention-summary span {
  display: grid;
  gap: 6px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.intervention-summary small,
.intervention-summary time {
  font-size: 12px;
  color: var(--studio-copy);
}
.intervention-summary em {
  font-size: 13px;
  font-style: normal;
  color: var(--studio-blue);
}
.intervention-details {
  padding: 0 16px 16px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.intervention-details p {
  font-size: 14px;
  margin: 8px 0;
}
.intervention-details .intervention-action-copy {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  flex-wrap: wrap;
  margin: 12px 0;
}
.device-selection-button {
  border: 0;
  padding: 4px 0;
  background: transparent;
  color: var(--studio-blue);
  font: inherit;
  text-align: left;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
  overflow-wrap: anywhere;
}
.teacher-detail-grid {
  gap: 24px;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
}
.anomaly-table-panel,
.teacher-log-panel {
  min-height: 0;
  grid-column: auto;
  margin: 0;
  padding: 0;
  border-right: 0;
}
.teacher-log-panel {
  scroll-margin-top: 172px;
}
.teacher-log-list {
  height: auto;
  max-height: 320px;
  margin-bottom: 16px;
  padding: 0;
}
.teacher-log-list > .teacher-log-row {
  grid-template-columns: 66px minmax(0, 1fr);
  gap: 12px;
  padding: 14px 0;
  font-size: 13px;
}
.teacher-log-row time {
  padding-top: 3px;
  font-size: 12px;
  line-height: 20px;
  font-variant-numeric: tabular-nums;
}
.teacher-log-content {
  min-width: 0;
}
.teacher-log-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
}
.teacher-log-list .teacher-log-level {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  padding: 2px 7px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  line-height: 20px;
  color: #37556d;
  background: #e8edf0;
}
.teacher-log-list .teacher-log-level.log-error {
  color: #9b3039;
  background: #f3e6e7;
}
.teacher-log-list .teacher-log-level.log-warn,
.teacher-log-list .teacher-log-level.log-warning {
  color: #805b19;
  background: #f3eddd;
}
.teacher-log-meta code {
  min-width: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--studio-ink);
  overflow-wrap: anywhere;
}
.teacher-log-list .teacher-log-content p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}
.teacher-table-wrap table {
  font-size: 13px;
}
.teacher-table-wrap td {
  white-space: normal;
  overflow-wrap: anywhere;
  height: auto;
  min-height: 52px;
}
.teacher-table-wrap code {
  font-size: 12px;
}
.teacher-table-wrap tr {
  cursor: default;
}
.teacher-kpis {
  margin-bottom: 28px;
}
.teacher-kpi {
  min-height: 130px;
  padding: 24px 20px;
}
.teacher-kpi strong {
  font-size: 36px;
}
.teacher-chart-grid {
  gap: 28px;
  margin-bottom: 24px;
}
.teacher-chart-grid > .teacher-panel:nth-child(odd),
.teacher-chart-grid > .teacher-panel:nth-child(even) {
  margin: 0;
  padding: 0;
  border-right: 0;
}
:deep(.teacher-chart) {
  height: 270px;
}
.teacher-resource-stack > .teacher-panel,
.teacher-management-details,
.teacher-system-details {
  margin-top: 24px;
}
.teacher-management-details,
.teacher-system-details {
  padding: 16px;
  border: 1px solid var(--studio-line);
}
.teacher-management-details summary,
.teacher-system-details summary {
  cursor: pointer;
  font-weight: 600;
  line-height: 1.6;
}
.teacher-system-details > p {
  font-size: 14px;
  line-height: 1.7;
}
.teacher-system-details .workflow-metric-strip {
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  margin: 16px 0 0;
}
.workflow-metric-strip span {
  min-width: 0;
  overflow-wrap: anywhere;
}
.teacher-workflow-card > header > button {
  color: var(--studio-ink);
}
:deep(.workflow-evidence-summary) {
  font-size: 13px;
}
:deep(.workflow-summary-line strong) {
  color: var(--studio-ink);
}
.workflow-metric-strip small {
  font-size: 12px;
}
.workflow-metric-strip b {
  font-size: 16px;
}
.knowledge-panel {
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 0 12px;
}
.knowledge-panel > div {
  min-width: 0;
}
.knowledge-panel b,
.knowledge-panel p {
  font-size: 14px;
  line-height: 1.65;
}
.knowledge-status-chip {
  grid-column: 2;
  justify-self: start;
  margin-top: 12px;
  font-size: 12px;
  display: inline-block;
  white-space: normal;
  line-height: 1.6;
}
.teacher-footer {
  margin-top: 32px;
  font-size: 12px;
}
@media (max-width: 1000px) {
  .teacher-hero {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .teacher-hero .teacher-task-counts {
    justify-content: flex-start;
    max-width: none;
  }
  .teacher-detail-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 820px) {
  .teacher-topbar {
    left: 0;
    right: 0;
    width: 100%;
  }
  .teacher-sidebar nav button .teacher-nav-copy {
    display: grid;
  }
  .teacher-content {
    padding-bottom: 96px;
  }
}
@media (max-width: 680px) {
  .teacher-topbar {
    gap: 8px;
  }
  .teacher-topbar .teacher-breadcrumb {
    display: none;
  }
  .teacher-sidebar nav button {
    padding: 8px 4px;
    gap: 4px;
  }
  .teacher-nav-copy b {
    font-size: 14px;
  }
  .teacher-nav-copy small {
    display: none;
  }
  .intervention-summary {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 12px;
  }
  .intervention-summary > span:nth-child(2) {
    grid-row: 2;
    grid-column: 1 / -1;
  }
  .teacher-kpi {
    padding: 20px 12px;
    min-height: 120px;
  }
  .teacher-kpi strong {
    font-size: 30px;
  }
  .teacher-management-details,
  .teacher-system-details {
    padding: 12px;
  }
  .teacher-task-counts {
    gap: 8px 12px;
  }
}
</style>
