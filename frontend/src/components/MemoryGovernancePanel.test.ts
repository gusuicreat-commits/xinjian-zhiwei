import { flushPromises, mount } from '@vue/test-utils'
import { vi } from 'vitest'
import MemoryGovernancePanel from './MemoryGovernancePanel.vue'
import * as api from '@/api/memory'
vi.mock('@/api/memory', () => ({
  memoryEvents: vi.fn(),
  memoryImpacts: vi.fn(),
  saveMemoryReview: vi.fn(),
  previewMemoryCleanup: vi.fn(),
  executeMemoryCleanup: vi.fn(),
  memoryImpactHistory: vi.fn(),
}))
const event = {
  id: 'event-one',
  source: { kind: 'case' as const, id: 'case-one', version: '1', hash: 'a' },
  reason: '已撤回',
  cache_cleanup_status: 'pending',
}
function button(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll('button').find((b) => b.text() === text)!
}
beforeEach(() => vi.clearAllMocks())
it('loads only on request and clears late results when the account changes', async () => {
  let resolve!: (value: { items: (typeof event)[]; next_cursor: null }) => void
  vi.mocked(api.memoryEvents).mockReturnValue(
    new Promise((r) => {
      resolve = r
    }),
  )
  const wrapper = mount(MemoryGovernancePanel, {
    props: { accessToken: 'old', administrator: false },
  })
  expect(api.memoryEvents).not.toHaveBeenCalled()
  await button(wrapper, '读取停用记录').trigger('click')
  await wrapper.setProps({ accessToken: 'new' })
  resolve({ items: [event], next_cursor: null })
  await flushPromises()
  expect(wrapper.text()).not.toContain('case-one')
  expect(wrapper.text()).not.toContain('过期缓存清理')
})
it('records a versioned review without changing the historical diagnosis', async () => {
  vi.mocked(api.memoryEvents).mockResolvedValue({ items: [event], next_cursor: null })
  const item = {
    diagnosis_result_id: 'diagnosis-one',
    basis: ['matched'],
    is_test_data: true,
    review: null,
  }
  vi.mocked(api.memoryImpacts).mockResolvedValue({ items: [item], next_cursor: null })
  vi.mocked(api.saveMemoryReview).mockResolvedValue({
    id: 'review-one',
    version: 1,
    decision: 'verify_again',
    note: '需要独立测量',
  })
  const wrapper = mount(MemoryGovernancePanel, {
    props: { accessToken: 'teacher', administrator: false },
  })
  await button(wrapper, '读取停用记录').trigger('click')
  await flushPromises()
  await button(wrapper, '查看案例 1 的影响').trigger('click')
  await flushPromises()
  await wrapper.find('textarea').setValue('需要独立测量')
  await button(wrapper, '保存复核').trigger('click')
  await flushPromises()
  expect(api.saveMemoryReview).toHaveBeenCalledWith(
    'teacher',
    'event-one',
    item,
    'verify_again',
    '需要独立测量',
  )
  expect(wrapper.text()).toContain('已有复核结果')
})
it('previews a fixed cache plan before allowing its explicit execution', async () => {
  const plan = {
    id: 'plan-one',
    status: 'planned',
    plan_hash: 'fixed-hash',
    targets: [{ id: 'cache-one', fingerprint: 'fp', expires_at: 'past' }],
    blocked_stores: [],
    result: {},
  }
  vi.mocked(api.previewMemoryCleanup).mockResolvedValue(plan)
  vi.mocked(api.executeMemoryCleanup).mockResolvedValue({ ...plan, status: 'completed' })
  const wrapper = mount(MemoryGovernancePanel, {
    props: { accessToken: 'admin', administrator: true },
  })
  expect(wrapper.text()).not.toContain('执行这份缓存清理计划')
  await button(wrapper, '预览清理计划').trigger('click')
  await flushPromises()
  expect(api.executeMemoryCleanup).not.toHaveBeenCalled()
  await button(wrapper, '执行这份缓存清理计划').trigger('click')
  await flushPromises()
  expect(api.executeMemoryCleanup).toHaveBeenCalledWith('admin', plan)
  expect(wrapper.text()).toContain('不代表所有副本已删除')
})
it('does not show a failed load as an empty success', async () => {
  vi.mocked(api.memoryEvents).mockRejectedValue(new Error('403'))
  const wrapper = mount(MemoryGovernancePanel, {
    props: { accessToken: 'teacher', administrator: false },
  })
  await button(wrapper, '读取停用记录').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  expect(wrapper.text()).not.toContain('当前范围没有已追踪')
})

it('clears previously visible records when the server revokes authorization', async () => {
  vi.mocked(api.memoryEvents).mockResolvedValueOnce({ items: [event], next_cursor: null })
  const wrapper = mount(MemoryGovernancePanel, {
    props: { accessToken: 'teacher', administrator: false },
  })
  await button(wrapper, '读取停用记录').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('case-one')
  vi.mocked(api.memoryEvents).mockRejectedValueOnce({
    isAxiosError: true,
    response: { status: 403 },
  })
  await button(wrapper, '读取停用记录').trigger('click')
  await flushPromises()
  expect(wrapper.text()).not.toContain('case-one')
  expect(wrapper.find('[role="alert"]').exists()).toBe(true)
})
