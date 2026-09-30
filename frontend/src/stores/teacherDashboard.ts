import { defineStore } from 'pinia'
import { useTeacherSessionStore } from './teacherSession'
import { ref, watch } from 'vue'

import {
  actOnTeacherIntervention,
  getDiagnosisWorkflowMetrics,
  getPendingDiagnosisWorkflows,
  getRecentDiagnosisWorkflows,
  getTeacherDashboard,
  reviewDiagnosisWorkflow,
} from '@/api/teacher'
import {
  classifyRequestFailure,
  failureMessage,
  withCappedRetry,
  type RequestFailureKind,
} from '@/api/resilience'
import {
  REVIEW_MODE,
  reviewTeacherDashboard,
  reviewTeacherWorkflowHistory,
  reviewTeacherWorkflowMetrics,
  reviewTeacherWorkflowQueue,
} from '@/review/fixtures'
import { readReviewState, saveReviewState } from '@/review/state'
import type {
  DiagnosisWorkflowMetrics,
  TeacherDashboard,
  TeacherDiagnosisWorkflow,
} from '@/types/teacher'

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function nullableFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function normalizeWorkflowMetrics(
  metrics: Partial<DiagnosisWorkflowMetrics>,
): DiagnosisWorkflowMetrics {
  const total = finiteNumber(metrics.total)
  const completed = finiteNumber(metrics.completed)
  const waitingTeacher = finiteNumber(metrics.waiting_teacher)
  const rejected = finiteNumber(metrics.rejected)
  const failed = finiteNumber(metrics.failed)
  const derivedInProgress = Math.max(0, total - completed - waitingTeacher - rejected - failed)
  return {
    total,
    completed,
    waiting_teacher: waitingTeacher,
    rejected,
    failed,
    in_progress: Math.max(0, finiteNumber(metrics.in_progress, derivedInProgress)),
    reviewed: finiteNumber(metrics.reviewed),
    edit_rate: finiteNumber(metrics.edit_rate),
    reject_rate: finiteNumber(metrics.reject_rate),
    needs_rag_count: finiteNumber(metrics.needs_rag_count),
    resume_count: finiteNumber(metrics.resume_count),
    average_node_duration_ms: nullableFiniteNumber(metrics.average_node_duration_ms),
    ai_call_count: finiteNumber(metrics.ai_call_count),
    ai_input_tokens: finiteNumber(metrics.ai_input_tokens),
    ai_output_tokens: finiteNumber(metrics.ai_output_tokens),
    ai_estimated_cost: finiteNumber(metrics.ai_estimated_cost),
    student_feedback_count: finiteNumber(metrics.student_feedback_count),
    student_resolved_count: finiteNumber(metrics.student_resolved_count),
    student_resolution_rate: nullableFiniteNumber(metrics.student_resolution_rate),
  }
}

export const useTeacherDashboardStore = defineStore('teacher-dashboard', () => {
  const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const dashboard = ref<TeacherDashboard | null>(null)
  const errorMessage = ref('')
  const failureKind = ref<RequestFailureKind | null>(null)
  const actionLoadingCaseId = ref<string | null>(null)
  const workflowQueue = ref<TeacherDiagnosisWorkflow[]>([])
  const workflowHistory = ref<TeacherDiagnosisWorkflow[]>([])
  const workflowMetrics = ref<DiagnosisWorkflowMetrics | null>(null)
  const workflowReviewingId = ref<string | null>(null)

  type SectionState = {
    state: 'idle' | 'loading' | 'ready' | 'error'
    failureKind: RequestFailureKind | null
  }
  const emptySections = () => ({
    queue: { state: 'idle', failureKind: null } as SectionState,
    history: { state: 'idle', failureKind: null } as SectionState,
    metrics: { state: 'idle', failureKind: null } as SectionState,
  })
  const workflowSections = ref(emptySections())
  let owner: string | null = null
  let epoch = 0
  let generation = 0

  if (REVIEW_MODE) {
    watch(
      dashboard,
      (value) => {
        if (value) saveReviewState('teacher-dashboard', value)
      },
      { deep: true },
    )
    watch(
      workflowQueue,
      (value) => {
        if (owner) saveReviewState('teacher-queue', value)
      },
      { deep: true },
    )
    watch(
      workflowHistory,
      (value) => {
        if (owner) saveReviewState('teacher-history', value)
      },
      { deep: true },
    )
    watch(
      workflowMetrics,
      (value) => {
        if (value) saveReviewState('teacher-metrics', value)
      },
      { deep: true },
    )
  }

  function handleFailure(
    error: unknown,
    accessToken: string,
    affected: 'view' | 'queue' | 'history' | 'metrics' = 'view',
  ): void {
    if (owner !== accessToken) return
    const kind = classifyRequestFailure(error)
    if (kind === 'unauthorized') {
      const auth = useTeacherSessionStore()
      if (auth.accessToken === accessToken) auth.logout()
      else clear()
    } else if (kind === 'forbidden' && affected === 'view') {
      // The action response does not identify a safe remaining class scope.
      // Hide this protected view, retain the account, and invalidate in-flight reads.
      clear()
      owner = accessToken
    }
    if (affected === 'view' || kind === 'unauthorized') {
      state.value = 'error'
      failureKind.value = kind
      if (['unauthorized', 'forbidden', 'conflict'].includes(kind)) dashboard.value = null
      errorMessage.value = failureMessage(kind)
    } else {
      if (['forbidden', 'conflict'].includes(kind)) {
        if (affected === 'queue') workflowQueue.value = []
        if (affected === 'history') workflowHistory.value = []
        if (affected === 'metrics') workflowMetrics.value = null
      }
      workflowSections.value[affected] = { state: 'error', failureKind: kind }
    }
  }

  async function load(accessToken: string): Promise<void> {
    if (owner !== accessToken) {
      clear()
      owner = accessToken
    }
    const request = ++generation
    const scope = epoch
    const current = () => scope === epoch && request === generation && owner === accessToken
    state.value = dashboard.value ? 'ready' : 'loading'
    errorMessage.value = ''
    if (REVIEW_MODE) {
      dashboard.value ??= readReviewState('teacher-dashboard', reviewTeacherDashboard)
      if (workflowSections.value.queue.state === 'idle') {
        workflowQueue.value = readReviewState('teacher-queue', reviewTeacherWorkflowQueue)
        workflowHistory.value = readReviewState('teacher-history', reviewTeacherWorkflowHistory)
        workflowMetrics.value = readReviewState('teacher-metrics', reviewTeacherWorkflowMetrics)
      }
      for (const section of Object.values(workflowSections.value)) section.state = 'ready'
      state.value = 'ready'
      failureKind.value = null
      return
    }
    async function section<T>(
      key: 'queue' | 'history' | 'metrics',
      fetch: () => Promise<T>,
      save: (value: T) => void,
      discard: () => void,
    ) {
      workflowSections.value[key] = { state: 'loading', failureKind: null }
      try {
        const value = await withCappedRetry(fetch)
        if (!current()) return
        save(value)
        workflowSections.value[key] = { state: 'ready', failureKind: null }
      } catch (error) {
        if (!current()) return
        const kind = classifyRequestFailure(error)
        if (['unauthorized', 'forbidden', 'conflict'].includes(kind)) discard()
        handleFailure(error, accessToken, key)
      }
    }
    await Promise.all([
      (async () => {
        try {
          const value = await withCappedRetry(() => getTeacherDashboard(accessToken))
          if (!current()) return
          dashboard.value = value
          state.value = 'ready'
          failureKind.value = null
        } catch (error) {
          if (!current()) return
          handleFailure(error, accessToken)
        }
      })(),
      section(
        'queue',
        () => getPendingDiagnosisWorkflows(accessToken),
        (value) => {
          workflowQueue.value = value
        },
        () => {
          workflowQueue.value = []
        },
      ),
      section(
        'history',
        () => getRecentDiagnosisWorkflows(accessToken),
        (value) => {
          workflowHistory.value = value
        },
        () => {
          workflowHistory.value = []
        },
      ),
      section(
        'metrics',
        () => getDiagnosisWorkflowMetrics(accessToken),
        (value) => {
          workflowMetrics.value = normalizeWorkflowMetrics(value)
        },
        () => {
          workflowMetrics.value = null
        },
      ),
    ])
  }

  async function reviewWorkflow(
    accessToken: string,
    workflowId: string,
    payload: {
      action: 'approve' | 'edit' | 'reject'
      comment?: string
      edited_result?: {
        summary: string
        possible_causes?: string[]
        steps?: string[]
        limitations?: string[]
      }
    },
  ): Promise<boolean> {
    if (owner !== accessToken) return false
    const scope = epoch
    if (REVIEW_MODE) {
      const item = workflowQueue.value.find((row) => row.id === workflowId)
      if (!item) throw new Error('演示审核记录已变化')
      const now = new Date().toISOString()
      item.status = payload.action === 'reject' ? 'rejected' : 'completed'
      item.updated_at = now
      item.completed_at = now
      item.reviews = [
        ...(item.reviews ?? []),
        {
          id: `review-${now}`,
          reviewer_user_id: 'review-teacher-01',
          action: payload.action,
          comment: payload.comment ?? null,
          edited_result: null,
          created_at: now,
        },
      ]
      if (payload.edited_result)
        item.final_result = {
          ...(item.review_request?.deterministic_result ?? {}),
          ...payload.edited_result,
        } as NonNullable<typeof item.final_result>
      workflowHistory.value = [
        item,
        ...workflowHistory.value.filter((row) => row.id !== workflowId),
      ]
      workflowQueue.value = workflowQueue.value.filter((row) => row.id !== workflowId)
      if (workflowMetrics.value) {
        workflowMetrics.value.waiting_teacher = workflowQueue.value.length
        workflowMetrics.value.reviewed += 1
        if (payload.action === 'reject') workflowMetrics.value.rejected += 1
        else workflowMetrics.value.completed += 1
      }
      return true
    }
    workflowReviewingId.value = workflowId
    try {
      await reviewDiagnosisWorkflow(accessToken, workflowId, payload)
      if (scope !== epoch || owner !== accessToken) return false
      await load(accessToken)
      return scope === epoch && owner === accessToken
    } catch (error) {
      if (scope !== epoch || owner !== accessToken) return false
      handleFailure(error, accessToken)
      throw error
    } finally {
      if (scope === epoch && workflowReviewingId.value === workflowId)
        workflowReviewingId.value = null
    }
  }

  async function act(
    accessToken: string,
    caseId: string,
    payload: {
      action: 'claim' | 'resolve' | 'close'
      expected_version: number
      note?: string
      is_private: boolean
    },
  ): Promise<boolean> {
    if (owner !== accessToken) return false
    const scope = epoch
    if (REVIEW_MODE) {
      const item = dashboard.value?.interventions.find((row) => row.case_id === caseId)
      if (!item || item.version_no !== payload.expected_version)
        throw new Error('演示工单已变化，请刷新')
      const allowed =
        payload.action === 'claim'
          ? item.status === 'open'
          : payload.action === 'resolve'
            ? item.status === 'claimed'
            : ['resolved', 'unconfirmed'].includes(item.status)
      if (!allowed) throw new Error('当前状态不支持此操作')
      item.status =
        payload.action === 'claim'
          ? 'claimed'
          : payload.action === 'resolve'
            ? 'resolved'
            : 'closed'
      item.version_no += 1
      if (payload.action === 'claim') item.assigned_teacher_user_id = 'review-teacher-01'
      if (payload.action === 'resolve') item.resolution_summary = payload.note ?? null
      return true
    }
    actionLoadingCaseId.value = caseId
    try {
      await actOnTeacherIntervention(accessToken, caseId, payload)
      if (scope !== epoch || owner !== accessToken) return false
      await load(accessToken)
      return scope === epoch && owner === accessToken
    } catch (error) {
      if (scope !== epoch || owner !== accessToken) return false
      handleFailure(error, accessToken)
      throw error
    } finally {
      if (scope === epoch && actionLoadingCaseId.value === caseId) actionLoadingCaseId.value = null
    }
  }

  function clear(): void {
    epoch += 1
    generation += 1
    owner = null
    actionLoadingCaseId.value = null
    workflowReviewingId.value = null
    workflowSections.value = emptySections()
    state.value = 'idle'
    dashboard.value = null
    errorMessage.value = ''
    failureKind.value = null
    workflowQueue.value = []
    workflowHistory.value = []
    workflowMetrics.value = null
  }

  return {
    state,
    dashboard,
    errorMessage,
    failureKind,
    actionLoadingCaseId,
    workflowQueue,
    workflowHistory,
    workflowMetrics,
    workflowReviewingId,
    workflowSections,
    load,
    act,
    reviewWorkflow,
    clear,
    handleFailure,
  }
})
