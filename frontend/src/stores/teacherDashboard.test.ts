import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getDiagnosisWorkflowMetrics,
  getPendingDiagnosisWorkflows,
  getRecentDiagnosisWorkflows,
  getTeacherDashboard,
} from '@/api/teacher'
import type { TeacherDashboard } from '@/types/teacher'

import { useTeacherDashboardStore } from './teacherDashboard'

vi.mock('@/api/teacher', () => ({
  getTeacherDashboard: vi.fn(),
  getPendingDiagnosisWorkflows: vi.fn(),
  getRecentDiagnosisWorkflows: vi.fn(),
  getDiagnosisWorkflowMetrics: vi.fn(),
  reviewDiagnosisWorkflow: vi.fn(),
  actOnTeacherIntervention: vi.fn(),
}))

const dashboard: TeacherDashboard = {
  generated_at: '2026-07-20T08:00:00Z',
  data_notice: '仅使用实际数据库记录',
  metrics: {
    online_devices: 1,
    offline_devices: 0,
    never_seen_devices: 0,
    abnormal_devices: 1,
    experiment_completion_rate: null,
  },
  device_status: [{ status: 'abnormal', count: 1 }],
  error_ranking: [{ error_code: 'TEST_EVENT', count: 1, test_data_only: true }],
  error_trend: [{ day: '2026-07-20', count: 1 }],
  class_progress: { configured: false, notice: '未配置' },
  anomalies: [],
  recent_logs: [],
  interventions: [],
  knowledge_cases: { configured: false, notice: '未配置' },
}

describe('teacher dashboard store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(getTeacherDashboard).mockReset()
    vi.mocked(getPendingDiagnosisWorkflows).mockReset()
    vi.mocked(getRecentDiagnosisWorkflows).mockReset()
    vi.mocked(getDiagnosisWorkflowMetrics).mockReset()
    vi.mocked(getPendingDiagnosisWorkflows).mockResolvedValue([])
    vi.mocked(getRecentDiagnosisWorkflows).mockResolvedValue([])
    vi.mocked(getDiagnosisWorkflowMetrics).mockResolvedValue({
      total: 1,
      completed: 0,
      waiting_teacher: 1,
      rejected: 0,
      failed: 0,
      in_progress: 0,
      reviewed: 0,
      edit_rate: 0,
      reject_rate: 0,
      needs_rag_count: 1,
      resume_count: 0,
      average_node_duration_ms: 12.5,
      ai_call_count: 0,
      ai_input_tokens: 0,
      ai_output_tokens: 0,
      ai_estimated_cost: 0,
      student_feedback_count: 0,
      student_resolved_count: 0,
      student_resolution_rate: null,
    })
  })

  it('stores the real aggregate response without filling missing completion data', async () => {
    vi.mocked(getTeacherDashboard).mockResolvedValue(dashboard)
    const store = useTeacherDashboardStore()

    await store.load('explicit-test-bearer-token')

    expect(store.state).toBe('ready')
    expect(store.dashboard?.metrics.experiment_completion_rate).toBeNull()
    expect(store.dashboard?.class_progress.configured).toBe(false)
    expect(store.workflowMetrics?.average_node_duration_ms).toBe(12.5)
  })

  it('keeps a recoverable error state when the aggregate request fails', async () => {
    vi.mocked(getTeacherDashboard).mockRejectedValue(new Error('offline'))
    const store = useTeacherDashboardStore()

    await store.load('explicit-test-bearer-token')

    expect(store.state).toBe('error')
    expect(store.errorMessage).toContain('数据加载失败')
  })

  it('keeps the legacy dashboard ready when optional workflow observability is unavailable', async () => {
    vi.mocked(getTeacherDashboard).mockResolvedValue(dashboard)
    vi.mocked(getPendingDiagnosisWorkflows).mockResolvedValue([
      {
        id: 'pending-workflow',
      } as never,
    ])
    vi.mocked(getRecentDiagnosisWorkflows).mockRejectedValue(new Error('staggered rollout'))
    const store = useTeacherDashboardStore()

    await store.load('explicit-test-bearer-token')

    expect(store.state).toBe('ready')
    expect(store.workflowQueue).toHaveLength(1)
    expect(store.workflowHistory).toEqual([])
    expect(store.workflowMetrics?.total).toBe(1)
  })

  it('defaults newly added workflow metrics during a staggered API rollout', async () => {
    vi.mocked(getTeacherDashboard).mockResolvedValue(dashboard)
    vi.mocked(getDiagnosisWorkflowMetrics).mockResolvedValue({
      total: 7,
      completed: 2,
      waiting_teacher: 1,
      rejected: 1,
      failed: 0,
      reviewed: 3,
      edit_rate: 0.25,
      reject_rate: 0.25,
      needs_rag_count: 4,
      resume_count: 1,
      average_node_duration_ms: Number.NaN,
    } as never)
    const store = useTeacherDashboardStore()

    await store.load('explicit-test-bearer-token')

    expect(store.workflowMetrics).toMatchObject({
      total: 7,
      ai_call_count: 0,
      ai_input_tokens: 0,
      ai_output_tokens: 0,
      ai_estimated_cost: 0,
      student_feedback_count: 0,
      student_resolved_count: 0,
      student_resolution_rate: null,
      average_node_duration_ms: null,
      in_progress: 3,
    })
  })
})
