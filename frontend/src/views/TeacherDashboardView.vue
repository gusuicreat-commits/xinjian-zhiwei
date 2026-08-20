<script setup lang="ts">
import {
  Bell,
  CircleCheckFilled,
  Cpu,
  DataAnalysis,
  Fold,
  HomeFilled,
  Management,
  Menu as MenuIcon,
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

import TeacherDeviceChart from '@/components/TeacherDeviceChart.vue'
import TeacherErrorRankingChart from '@/components/TeacherErrorRankingChart.vue'
import TeacherErrorTrendChart from '@/components/TeacherErrorTrendChart.vue'
import WorkflowEvidenceSummary from '@/components/WorkflowEvidenceSummary.vue'
import { useTeacherDashboardStore } from '@/stores/teacherDashboard'
import { useTeacherSessionStore } from '@/stores/teacherSession'
import type { TeacherDiagnosisWorkflow, TeacherIntervention } from '@/types/teacher'

const router = useRouter()
const sessionStore = useTeacherSessionStore()
const dashboardStore = useTeacherDashboardStore()
const sidebarCollapsed = ref(false)
const activeNavTarget = ref('teacher-overview')
const searchQuery = ref('')
const selectedDeviceId = ref('')
const expandedWorkflowId = ref<string | null>(null)
let refreshTimer: number | undefined
let navigationFrame: number | undefined

const dashboard = computed(() => dashboardStore.dashboard)
const filteredAnomalies = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return dashboard.value?.anomalies ?? []
  return (dashboard.value?.anomalies ?? []).filter((item) =>
    [item.device_id, item.device_name, item.latest_error_code, item.latest_summary]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query)),
  )
})
const selectedDevice = computed(
  () => selectedDeviceId.value || filteredAnomalies.value[0]?.device_id || '',
)
const selectedLogs = computed(() => {
  const logs = dashboard.value?.recent_logs ?? []
  return selectedDevice.value
    ? logs.filter((item) => item.device_id === selectedDevice.value)
    : logs
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
  {
    label: '数据总览',
    description: '设备核心指标',
    target: 'teacher-overview',
    icon: HomeFilled,
  },
  {
    label: '设备分析',
    description: '状态、错误与趋势',
    target: 'device-analysis',
    icon: DataAnalysis,
  },
  {
    label: '异常处置',
    description: '异常、日志与介入',
    target: 'anomaly-workbench',
    icon: Warning,
  },
]

async function refresh(): Promise<void> {
  if (!sessionStore.accessToken) return
  await dashboardStore.load(sessionStore.accessToken)
  await nextTick()
  syncActiveNavigation()
}
function navigateTo(target: string): void {
  activeNavTarget.value = target
  document.getElementById(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function syncActiveNavigation(): void {
  const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight)

  if (maxScroll > 80 && window.scrollY >= maxScroll - 8) {
    activeNavTarget.value = navItems[navItems.length - 1]?.target ?? 'teacher-overview'
    return
  }
  const activationLine = 150
  let nextTarget = navItems[0]?.target ?? 'teacher-overview'
  for (const item of navItems) {
    const section = document.getElementById(item.target)
    if (section && section.getBoundingClientRect().top <= activationLine) {
      nextTarget = item.target
    }
  }
  activeNavTarget.value = nextTarget
}
function handleWindowScroll(): void {
  if (navigationFrame !== undefined) return
  navigationFrame = window.requestAnimationFrame(() => {
    navigationFrame = undefined
    syncActiveNavigation()
  })
}
function selectDevice(deviceId: string): void {
  selectedDeviceId.value = deviceId
  activeNavTarget.value = 'anomaly-workbench'
  document
    .getElementById('device-log-detail')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
  resolved: '已解决',
  unconfirmed: '待补充证据',
  closed: '已关闭',
  recommended: '建议介入',
}

async function handleIntervention(item: TeacherIntervention): Promise<void> {
  if (!sessionStore.accessToken || !item.case_id || item.version_no === null) return
  try {
    if (item.status === 'open') {
      await dashboardStore.act(sessionStore.accessToken, item.case_id, {
        action: 'claim',
        expected_version: item.version_no,
        is_private: false,
      })
      ElMessage.success('已认领该学生求助')
      return
    }
    if (item.status === 'claimed') {
      const result = await ElMessageBox.prompt(
        '请填写将同步给学生的处理结果。',
        '解决教师协助工单',
        {
          confirmButtonText: '标记为已解决',
          cancelButtonText: '取消',
          inputPlaceholder: '例如：已指导重新连接传感器并确认读数恢复',
          inputValidator: (value) => Boolean(value.trim()) || '请填写处理结果',
        },
      )
      await dashboardStore.act(sessionStore.accessToken, item.case_id, {
        action: 'resolve',
        expected_version: item.version_no,
        note: result.value.trim(),
        is_private: false,
      })
      ElMessage.success('处理结果已同步给学生')
      return
    }
    if (item.status === 'resolved' || item.status === 'unconfirmed') {
      await ElMessageBox.confirm('关闭后该工单将保留在历史记录中。', '关闭教师协助工单', {
        confirmButtonText: '确认关闭',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await dashboardStore.act(sessionStore.accessToken, item.case_id, {
        action: 'close',
        expected_version: item.version_no,
        is_private: false,
      })
      ElMessage.success('工单已关闭')
    }
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error('工单操作失败，可能已被其他教师更新，请刷新后重试')
  }
}
async function handleWorkflowReview(
  workflowId: string,
  action: 'approve' | 'edit' | 'reject',
): Promise<void> {
  if (!sessionStore.accessToken) return
  try {
    const result = await ElMessageBox.prompt(
      action === 'approve'
        ? '可填写本次审核说明。'
        : action === 'edit'
          ? '请填写修订后的诊断总结。规则证据和 Level 不会被修改。'
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
    await dashboardStore.reviewWorkflow(
      sessionStore.accessToken,
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
    )
    ElMessage.success(
      action === 'approve' ? '诊断已批准' : action === 'edit' ? '诊断已修订并批准' : '诊断已驳回',
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
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
  window.addEventListener('scroll', handleWindowScroll, { passive: true })
})
onBeforeUnmount(() => {
  window.clearInterval(refreshTimer)
  window.removeEventListener('scroll', handleWindowScroll)
  if (navigationFrame !== undefined) window.cancelAnimationFrame(navigationFrame)
})
</script>

<template>
  <main class="teacher-app" :class="{ 'sidebar-is-collapsed': sidebarCollapsed }">
    <header class="teacher-topbar">
      <div class="teacher-brand">
        <Cpu />
        <div><strong>芯鉴知微</strong><small>嵌入式实验智能分析平台</small></div>
        <b>教师端</b>
      </div>
      <div class="teacher-breadcrumb"><HomeFilled /><span>/</span><b>班级实验总览</b></div>
      <label class="teacher-search"
        ><input v-model="searchQuery" placeholder="搜索设备或错误代码…" /><Search
      /></label>
      <button type="button" class="teacher-icon-button" aria-label="通知"><Bell /></button>
      <div class="teacher-user">
        <span><UserFilled /></span>
        <div>
          <strong>{{ sessionStore.session?.display_name || '教师账号' }}</strong>
          <small>Bearer 账号会话</small>
        </div>
      </div>
      <button type="button" class="teacher-icon-button" aria-label="退出教师端" @click="logout">
        <SwitchButton />
      </button>
    </header>

    <aside class="teacher-sidebar">
      <nav aria-label="教师端导航">
        <button
          v-for="item in navItems"
          :key="item.target"
          type="button"
          :class="{ active: activeNavTarget === item.target }"
          :title="`${item.label}：${item.description}`"
          :aria-current="activeNavTarget === item.target ? 'location' : undefined"
          @click="navigateTo(item.target)"
        >
          <component :is="item.icon" />
          <span class="teacher-nav-copy"
            ><b>{{ item.label }}</b
            ><small>{{ item.description }}</small></span
          >
        </button>
      </nav>
      <div class="teacher-system-status">
        <CircleCheckFilled />
        <div><b>接口状态正常</b><small>每 30 秒刷新</small></div>
      </div>
      <button
        type="button"
        class="teacher-collapse"
        :aria-label="sidebarCollapsed ? '展开教师菜单' : '收起教师菜单'"
        @click="sidebarCollapsed = !sidebarCollapsed"
      >
        <Fold v-if="!sidebarCollapsed" /><MenuIcon v-else /><span>{{
          sidebarCollapsed ? '展开菜单' : '收起菜单'
        }}</span>
      </button>
    </aside>

    <section id="teacher-overview" class="teacher-content">
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
        <template #extra><el-button type="primary" @click="refresh">重新加载</el-button></template>
      </el-result>
      <template v-else-if="dashboard">
        <header class="teacher-hero">
          <div>
            <p>TEACHER OPERATIONS</p>
            <h1>班级实验总览</h1>
            <span>聚合设备状态、异常证据与待处理教学介入。</span>
          </div>
          <dl>
            <div>
              <dt>数据来源</dt>
              <dd>实时接口</dd>
            </div>
            <div>
              <dt>刷新频率</dt>
              <dd>30 秒</dd>
            </div>
            <div>
              <dt>当前状态</dt>
              <dd>持续监测</dd>
            </div>
          </dl>
        </header>
        <div class="teacher-notice" :class="{ warning: hasTestData }">
          <Warning /><span>{{ dashboard.data_notice }}</span
          ><button type="button" @click="refresh"><Refresh />刷新</button>
        </div>
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
            <TeacherDeviceChart :data="dashboard.device_status" />
          </article>
          <article class="teacher-panel">
            <header>
              <h2>高频错误排行</h2>
              <small>各设备最新诊断</small>
            </header>
            <TeacherErrorRankingChart :data="dashboard.error_ranking" />
          </article>
          <article id="class-progress" class="teacher-panel teacher-placeholder">
            <header>
              <h2>班级实验进度</h2>
              <small>真实接口</small>
            </header>
            <DataAnalysis /><b>班级与任务尚未配置</b>
            <p>{{ dashboard.class_progress.notice }}</p>
          </article>
          <article class="teacher-panel">
            <header>
              <h2>错误趋势图</h2>
              <small>近 7 天</small>
            </header>
            <TeacherErrorTrendChart :data="dashboard.error_trend" />
          </article>
        </section>

        <section id="anomaly-workbench" class="teacher-detail-grid">
          <article id="anomaly-list" class="teacher-panel anomaly-table-panel">
            <header>
              <h2>
                设备异常列表 <i>{{ filteredAnomalies.length }}</i>
              </h2>
              <small>
                {{
                  filteredAnomalies.some((item) => item.student_identity_configured)
                    ? '学生归属来自设备绑定'
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
                    @click="selectDevice(item.device_id)"
                  >
                    <td>
                      <b>{{ item.device_name || item.device_id }}</b
                      ><small>{{ item.device_id }}</small>
                    </td>
                    <td>
                      <code>{{ item.latest_error_code }}</code>
                    </td>
                    <td><span class="status-badge danger">待核查</span></td>
                    <td>
                      <span
                        class="status-badge"
                        :class="item.is_test_data ? 'warning' : 'success'"
                        >{{ item.is_test_data ? '测试/模拟' : '未标记测试' }}</span
                      >
                    </td>
                    <td>{{ item.latest_summary }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <el-empty v-else description="当前没有规则命中的异常设备" :image-size="58" />
          </article>

          <article id="device-log-detail" class="teacher-panel teacher-log-panel">
            <header>
              <h2>单个设备日志详情</h2>
              <small>{{ selectedDevice || '未选择设备' }}</small>
            </header>
            <div v-if="selectedLogs.length" class="teacher-log-list">
              <div v-for="log in selectedLogs" :key="log.id">
                <time>{{
                  new Date(log.occurred_at).toLocaleTimeString('zh-CN', { hour12: false })
                }}</time
                ><span :class="`log-${log.level.toLowerCase()}`">{{
                  log.level.toUpperCase()
                }}</span>
                <p>
                  <b v-if="log.event_code">{{ log.event_code }} · </b>{{ log.message }}
                </p>
              </div>
            </div>
            <el-empty v-else description="该设备暂无日志" :image-size="58" />
          </article>

          <div class="teacher-side-stack">
            <article class="teacher-panel intervention-panel">
              <header>
                <h2>需要教师介入的设备</h2>
                <i>{{ dashboard.interventions.length }}</i>
              </header>
              <div v-if="dashboard.interventions.length" class="teacher-action-list">
                <div
                  v-for="item in dashboard.interventions"
                  :key="item.diagnosis_result_id"
                  class="teacher-action-item"
                  @click="selectDevice(item.device_id)"
                >
                  <span
                    ><b>{{ item.device_id }}</b
                    ><small>{{ item.tree_title }}</small>
                    <small class="intervention-source">
                      {{
                        item.source === 'student_request'
                          ? '学生主动求助'
                          : item.source === 'automatic_guidance'
                            ? '系统建议介入'
                            : '人工创建'
                      }}
                    </small></span
                  >
                  <div class="intervention-action-copy">
                    <em :class="`intervention-${item.status}`">{{
                      interventionStatusLabels[item.status]
                    }}</em>
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
                            ? '解决'
                            : '关闭'
                      }}
                    </el-button>
                  </div>
                </div>
              </div>
              <el-empty v-else description="暂无 Level 4 介入记录" :image-size="48" />
            </article>
            <article class="teacher-panel intervention-panel">
              <header>
                <h2>AI 诊断审核队列</h2>
                <i>{{ dashboardStore.workflowQueue.length }}</i>
              </header>
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
                  ><small>触发 RAG</small><b>{{ workflowMetrics.needs_rag_count ?? 0 }}</b></span
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
                  <small>Token</small>
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
              <div v-if="dashboardStore.workflowQueue.length" class="teacher-action-list">
                <article
                  v-for="item in dashboardStore.workflowQueue"
                  :key="item.id"
                  class="teacher-workflow-card"
                >
                  <header>
                    <button type="button" @click="toggleWorkflow(item.id)">
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
                        @click.stop="handleWorkflowReview(item.id, 'approve')"
                        >批准</el-button
                      >
                      <el-button
                        size="small"
                        type="primary"
                        :loading="dashboardStore.workflowReviewingId === item.id"
                        @click.stop="handleWorkflowReview(item.id, 'edit')"
                        >修订</el-button
                      >
                      <el-button
                        size="small"
                        type="danger"
                        :loading="dashboardStore.workflowReviewingId === item.id"
                        @click.stop="handleWorkflowReview(item.id, 'reject')"
                        >驳回</el-button
                      >
                    </div>
                  </header>
                  <WorkflowEvidenceSummary v-if="expandedWorkflowId === item.id" :workflow="item" />
                </article>
              </div>
              <el-empty v-else description="暂无等待审核的 AI 诊断" :image-size="48" />
            </article>
            <article class="teacher-panel workflow-history-panel">
              <header>
                <h2>近期诊断审核历史</h2>
                <i>{{ dashboardStore.workflowHistory.length }}</i>
              </header>
              <div v-if="dashboardStore.workflowHistory.length" class="workflow-history-list">
                <article v-for="item in dashboardStore.workflowHistory" :key="item.id">
                  <button type="button" @click="toggleWorkflow(item.id)">
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
              <el-empty v-else description="暂无诊断审核历史" :image-size="48" />
            </article>
            <article id="knowledge-review" class="teacher-panel knowledge-panel">
              <header>
                <h2>知识案例审核入口</h2>
                <small>Phase 8 框架</small>
              </header>
              <Management />
              <div>
                <b>{{ dashboard.knowledge_cases.configured ? '知识库可检索' : '等待授权资料' }}</b>
                <p>{{ dashboard.knowledge_cases.notice }}</p>
                <p>
                  来源 {{ dashboard.knowledge_cases.source_count ?? 0 }} · 文档
                  {{ dashboard.knowledge_cases.document_count ?? 0 }} · 待审核
                  {{ dashboard.knowledge_cases.pending_review_count ?? 0 }} · 向量
                  {{ dashboard.knowledge_cases.embedding_count ?? 0 }}
                </p>
              </div>
              <span class="knowledge-status-chip">审核 API 已就绪</span>
            </article>
          </div>
        </section>
        <footer class="teacher-footer">
          <span>图表支持自适应布局</span><span>数据来源：实时接口</span><span>刷新间隔：30s</span
          ><time>{{ new Date(dashboard.generated_at).toLocaleString('zh-CN') }}</time>
        </footer>
      </template>
    </section>
  </main>
</template>
