import { defineStore } from 'pinia'
import { ref } from 'vue'

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

  async function load(accessToken: string): Promise<void> {
    state.value = dashboard.value ? 'ready' : 'loading'
    errorMessage.value = ''
    if (REVIEW_MODE) {
      dashboard.value = structuredClone(reviewTeacherDashboard)
      workflowQueue.value = structuredClone(reviewTeacherWorkflowQueue)
      workflowHistory.value = structuredClone(reviewTeacherWorkflowHistory)
      workflowMetrics.value = structuredClone(reviewTeacherWorkflowMetrics)
      state.value = 'ready'
      failureKind.value = null
      return
    }
    try {
      dashboard.value = await withCappedRetry(() => getTeacherDashboard(accessToken))
      const [queue, history, metrics] = await Promise.allSettled([
        getPendingDiagnosisWorkflows(accessToken),
        getRecentDiagnosisWorkflows(accessToken),
        getDiagnosisWorkflowMetrics(accessToken),
      ])
      // Each additive surface degrades independently during a staggered backend rollout.
      workflowQueue.value = queue.status === 'fulfilled' ? queue.value : []
      workflowHistory.value = history.status === 'fulfilled' ? history.value : []
      workflowMetrics.value =
        metrics.status === 'fulfilled' ? normalizeWorkflowMetrics(metrics.value) : null
      state.value = 'ready'
      failureKind.value = null
    } catch (error) {
      state.value = 'error'
      failureKind.value = classifyRequestFailure(error)
      errorMessage.value = failureMessage(failureKind.value)
    }
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
  ): Promise<void> {
    if (REVIEW_MODE) {
      workflowQueue.value = workflowQueue.value.filter((item) => item.id !== workflowId)
      return
    }
    workflowReviewingId.value = workflowId
    try {
      await reviewDiagnosisWorkflow(accessToken, workflowId, payload)
      await load(accessToken)
    } finally {
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
  ): Promise<void> {
    if (REVIEW_MODE) return
    actionLoadingCaseId.value = caseId
    try {
      await actOnTeacherIntervention(accessToken, caseId, payload)
      await load(accessToken)
    } finally {
      actionLoadingCaseId.value = null
    }
  }

  function clear(): void {
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
    load,
    act,
    reviewWorkflow,
    clear,
  }
})
