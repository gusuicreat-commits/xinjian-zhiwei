import { mount } from '@vue/test-utils'
import type { MemoryContext } from '@/types/memory'
import MemorySummary from './MemorySummary.vue'
const memory: MemoryContext = {
  contract_version: 'memory-v1',
  available: true,
  facts: [
    {
      kind: 'configuration',
      subject: 'data',
      value: { pins: { data: 4 } },
      source: { kind: 'package', id: 'pkg', version: '1', hash: 'hash' },
      physical_verification: 'not_asserted',
      is_test_data: true,
    },
  ],
  experiences: [],
  working: {
    workflow_id: 'w',
    session_id: 's',
    diagnosis_result_id: 'd',
    package_version_id: 'pkg',
    revision: 1,
    active: true,
    status: 'waiting_feedback',
    evidence_ids: ['e'],
    evidence_truncated: true,
    feedback: [],
    feedback_truncated: false,
    next_step: 'feedback_handler',
    is_test_data: true,
  },
}
it('separates configuration, experience and task evidence without claiming physical truth', () => {
  const wrapper = mount(MemorySummary, { props: { memory } })
  expect(wrapper.text()).toContain('配置不等于实际接线或实测结果')
  expect(wrapper.text()).toContain('参考案例不代表本次根因已确认')
  expect(wrapper.text()).toContain('1 条证据引用')
  expect(wrapper.text()).toContain('有限摘要')
  expect(wrapper.text()).toContain('测试数据')
})
it('marks stopped memory and closed working context explicitly', () => {
  const wrapper = mount(MemorySummary, {
    props: {
      memory: {
        ...memory,
        available: false,
        facts: [],
        working: { ...memory.working, active: false },
      },
    },
  })
  expect(wrapper.find('[role="alert"]').text()).toContain('旧建议不能继续使用')
  expect(wrapper.text()).toContain('已停止活动')
})
