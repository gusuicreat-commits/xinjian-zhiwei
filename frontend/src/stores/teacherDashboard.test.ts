import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getTeacherDashboard } from '@/api/teacher'
import type { TeacherDashboard } from '@/types/teacher'

import { useTeacherDashboardStore } from './teacherDashboard'

vi.mock('@/api/teacher', () => ({ getTeacherDashboard: vi.fn() }))

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
  })

  it('stores the real aggregate response without filling missing completion data', async () => {
    vi.mocked(getTeacherDashboard).mockResolvedValue(dashboard)
    const store = useTeacherDashboardStore()

    await store.load({ reviewToken: 'explicit-test-token' })

    expect(store.state).toBe('ready')
    expect(store.dashboard?.metrics.experiment_completion_rate).toBeNull()
    expect(store.dashboard?.class_progress.configured).toBe(false)
  })

  it('keeps a recoverable error state when the aggregate request fails', async () => {
    vi.mocked(getTeacherDashboard).mockRejectedValue(new Error('offline'))
    const store = useTeacherDashboardStore()

    await store.load({ reviewToken: 'explicit-test-token' })

    expect(store.state).toBe('error')
    expect(store.errorMessage).toContain('数据加载失败')
  })
})
