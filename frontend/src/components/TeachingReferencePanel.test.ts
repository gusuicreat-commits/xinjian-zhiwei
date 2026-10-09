import { mount } from '@vue/test-utils'
import type { TeachingReference } from '@/types/student'
import TeachingReferencePanel from './TeachingReferencePanel.vue'

const material: TeachingReference = {
  contract_version: 'teaching-reference-v1',
  status: 'available',
  experiment_version_id: 'version-a',
  package_version: '2.0.3',
  package_hash: 'hash-a',
  is_test_data: true,
  concepts: [{ concept_id: 'a', description: 'GPIO4 只是待确认示例。', references: [] }],
  steps: [
    {
      step_id: 'connect',
      title: '核对接线',
      expected_state: '连接正确',
      prerequisite_step_ids: [],
    },
  ],
}

it('shows reference and expected observation without claiming completion or confirmation', () => {
  const wrapper = mount(TeachingReferencePanel, { props: { material } })
  expect(wrapper.text()).toContain('待硬件与教师确认')
  expect(wrapper.text()).toContain('不是实测结果')
  expect(wrapper.text()).toContain('不代表已经执行')
  expect(wrapper.text()).toContain('版本 2.0.3')
  expect(wrapper.text()).toContain('GPIO4 只是待确认示例')
  expect(wrapper.findAll('button')).toHaveLength(0)
})

it('handles legacy, missing and unavailable material without guessing', async () => {
  const wrapper = mount(TeachingReferencePanel)
  expect(wrapper.text()).toContain('此历史指导未记录')
  await wrapper.setProps({ material: { ...material, status: 'missing' } })
  expect(wrapper.text()).toContain('暂无明确关联')
  expect(wrapper.text()).not.toContain('GPIO4')
  await wrapper.setProps({ material: { ...material, status: 'unavailable' } })
  expect(wrapper.text()).toContain('基础诊断仍可查看')
})

it('renders source prose as text, never executable HTML', () => {
  const wrapper = mount(TeachingReferencePanel, {
    props: {
      material: {
        ...material,
        concepts: [
          { concept_id: 'x', description: '<img src=x onerror=alert(1)>', references: [] },
        ],
      },
    },
  })
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.text()).toContain('<img')
})
