import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import DiagnosisCheckPanel from './DiagnosisCheckPanel.vue'
it('distinguishes reported handling from actual verification and explains old-snapshot feedback', () => {
  const wrapper = mount(DiagnosisCheckPanel, {
    props: {
      check: {
        request_id: 'id',
        status: 'completed',
        checked_at: '2026-09-20T12:00:00Z',
        data_change: 'monitoring_only',
        issues: [
          {
            episode_id: 'old',
            error_type: '读取失败',
            observation: 'not_detected_unverified',
            handling_status: 'resolved',
          },
        ],
      },
    },
  })
  expect(wrapper.text()).toContain('恢复尚未确认')
  expect(wrapper.text()).toContain('没有新增相关采样')
  expect(wrapper.text()).toContain('“仍未解决”继续使用原诊断数据')
})
it('shows a safe historical empty state without inventing a comparison', () => {
  expect(mount(DiagnosisCheckPanel).text()).toContain('历史数据不会自动补算')
})
