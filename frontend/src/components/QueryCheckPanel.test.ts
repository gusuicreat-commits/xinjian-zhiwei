import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  answerStudentQuery,
  findStudentQuery,
  readStudentQuery,
  startStudentQuery,
  type QueryTask,
} from '@/api/student'
import QueryCheckPanel from './QueryCheckPanel.vue'

vi.mock('@/api/student', () => ({
  answerStudentQuery: vi.fn(),
  findStudentQuery: vi.fn(),
  readStudentQuery: vi.fn(),
  startStudentQuery: vi.fn(),
}))
const credentials = { deviceId: 'device', deviceToken: 'test', experimentSessionId: 'session' }
function result(overrides: Partial<QueryTask> = {}): QueryTask {
  return {
    id: 'task',
    contract_version: 'dht11-query-v1',
    status: 'waiting_answer',
    terminal_reason: null,
    requirements: {
      firmware_gpio_vs_requirement: { status: 'satisfied', judgement: 'match', gap: null },
      wiring_observation: {
        status: 'waiting_answer',
        judgement: 'unknown',
        gap: 'observation_unknown',
      },
      approved_reference: {
        status: 'checked_empty',
        judgement: 'checked_empty',
        gap: 'no_approved_case',
      },
    },
    question: {
      question_id: 'synthetic.dht11.wiring_observation',
      version: 'v1',
      requirement: 'wiring_observation',
      synthetic: true,
      options: ['matches_table', 'differs', 'unclear'],
    },
    query_count: 4,
    question_count: 1,
    is_test_data: true,
    root_cause_status: 'unconfirmed',
    physical_verification: 'not_asserted',
    ...overrides,
  }
}
function error(status?: number) {
  return { isAxiosError: true, response: status ? { status } : undefined }
}
function setup() {
  return mount(QueryCheckPanel, {
    props: { diagnosisId: 'diagnosis', credentials },
    global: { plugins: [ElementPlus] },
  })
}
async function click(wrapper: ReturnType<typeof setup>, label: string) {
  const button = wrapper.findAll('button').find((button) => button.text() === label)
  expect(button, label).toBeDefined()
  await button!.trigger('click')
  await flushPromises()
}
async function answer(wrapper: ReturnType<typeof setup>) {
  await wrapper.find('input[value="matches_table"]').setValue()
  await click(wrapper, '提交答复')
}
beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  vi.mocked(findStudentQuery).mockResolvedValue(null)
  vi.mocked(startStudentQuery).mockResolvedValue(result())
  vi.mocked(readStudentQuery).mockResolvedValue(
    result({ status: 'finish_unknown', question: null }),
  )
})
describe('资料核对', () => {
  it('loads only an existing task and starts only on an explicit click', async () => {
    const wrapper = setup()
    await flushPromises()
    expect(findStudentQuery).toHaveBeenCalledTimes(1)
    expect(startStudentQuery).not.toHaveBeenCalled()
    await wrapper.setProps({ refreshKey: 'new-read' })
    await flushPromises()
    expect(startStudentQuery).not.toHaveBeenCalled()
    await click(wrapper, '核对资料')
    expect(startStudentQuery).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('测试用题目，正式题目待教师确认')
    expect(wrapper.findAll('input[type=radio]')).toHaveLength(3)
    expect(
      wrapper
        .findAll('.el-alert')
        .map((alert) => alert.text())
        .join(' '),
    ).toContain('测试数据')
  })
  it.each(['match', 'mismatch', 'unknown'])(
    'shows %s without claiming wiring or root cause',
    async (judgement) => {
      const task = result()
      task.requirements.firmware_gpio_vs_requirement = {
        status: 'unknown',
        judgement,
        gap: judgement === 'unknown' ? 'not_reported' : null,
      }
      vi.mocked(findStudentQuery).mockResolvedValue(task)
      const wrapper = setup()
      await flushPromises()
      const text = wrapper.find('dl').text()
      expect(text).toContain(
        {
          match: '程序自报 GPIO 与实验要求一致',
          mismatch: '程序自报 GPIO 与实验要求不一致',
          unknown: '目前无法判断',
        }[judgement],
      )
      expect(
        wrapper
          .findAll('p')
          .map((p) => p.text())
          .join(' '),
      ).toContain('这是程序里设置的引脚，不代表实际接线已核对')
      expect(
        wrapper
          .findAll('p')
          .map((p) => p.text())
          .join(' '),
      ).toContain('未确认故障原因')
    },
  )
  it('shows stale prominently and exposes unknown code originals without guessing', async () => {
    vi.mocked(findStudentQuery).mockResolvedValue(
      result({ status: 'stale', terminal_reason: 'new_reason', question: null }),
    )
    const wrapper = setup()
    await flushPromises()
    expect(
      wrapper
        .findAll('.el-alert')
        .map((alert) => alert.text())
        .join(' '),
    ).toContain('资料已变化，本次核对结果不可再用')
    expect(
      wrapper
        .findAll('p')
        .map((p) => p.text())
        .join(' '),
    ).toContain('暂缺解释')
    expect(wrapper.find('details').text()).toContain('new_reason')
    expect(wrapper.find('fieldset').exists()).toBe(false)
  })
  it('does not offer answers to unknown question IDs', async () => {
    const task = result()
    task.question!.question_id = 'future.question'
    vi.mocked(findStudentQuery).mockResolvedValue(task)
    const wrapper = setup()
    await flushPromises()
    expect(wrapper.find('fieldset').exists()).toBe(false)
    expect(wrapper.text()).toContain('题目暂缺解释')
  })
  it.each([503, undefined])(
    'retains the original answer after %s and retries only on click, also across reload',
    async (status) => {
      vi.mocked(findStudentQuery).mockResolvedValue(result())
      vi.mocked(answerStudentQuery)
        .mockRejectedValueOnce(error(status))
        .mockResolvedValue({ id: 'receipt', request_id: 'original', value: 'matches_table' })
      let wrapper = setup()
      await flushPromises()
      await answer(wrapper)
      const first = vi.mocked(answerStudentQuery).mock.calls[0]![2]
      expect(first.request_id).toMatch(/^[0-9a-f-]{36}$/i)
      expect(answerStudentQuery).toHaveBeenCalledTimes(1)
      expect(wrapper.find('fieldset').attributes('disabled')).toBeDefined()
      wrapper.unmount()
      wrapper = setup()
      await flushPromises()
      expect(answerStudentQuery).toHaveBeenCalledTimes(1)
      await click(wrapper, '重试原答复')
      expect(vi.mocked(answerStudentQuery).mock.calls[1]![2]).toEqual(first)
      expect(readStudentQuery).toHaveBeenCalledTimes(1)
      expect(wrapper.text()).toContain('本次核对已结束，仍有资料缺口')
      expect(wrapper.find('.pending-answer').exists()).toBe(false)
    },
  )
  it('rereads on 409 and never resubmits automatically', async () => {
    vi.mocked(findStudentQuery).mockResolvedValue(result())
    vi.mocked(answerStudentQuery).mockRejectedValue(error(409))
    const wrapper = setup()
    await flushPromises()
    await answer(wrapper)
    expect(readStudentQuery).toHaveBeenCalledTimes(1)
    expect(answerStudentQuery).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('请求发生冲突')
    expect(wrapper.find('.pending-answer').exists()).toBe(false)
  })
  it.each([401, 403])('clears protected content on %s', async (status) => {
    vi.mocked(findStudentQuery).mockResolvedValue(result())
    vi.mocked(answerStudentQuery).mockRejectedValue(error(status))
    const wrapper = setup()
    await flushPromises()
    await answer(wrapper)
    expect(wrapper.find('dl').exists()).toBe(false)
    expect(wrapper.find('details').exists()).toBe(false)
    expect(wrapper.find('.pending-answer').exists()).toBe(false)
    expect(sessionStorage.length).toBe(0)
    if (status === 401) expect(wrapper.emitted('login')).toHaveLength(1)
    else expect(wrapper.text()).toContain('当前无权')
  })
  it('shows a failed GET as an error and disables new commands', async () => {
    vi.mocked(findStudentQuery).mockRejectedValue(error(503))
    const wrapper = setup()
    await flushPromises()
    expect(wrapper.text()).toContain('读取失败')
    expect(wrapper.text()).not.toContain('尚未发起')
    expect(wrapper.findAll('button').some((b) => b.text() === '核对资料')).toBe(false)
  })
  it.each(['read', 'start', 'answer'])(
    'isolates late %s success after session switch',
    async (kind) => {
      let resolve!: (value: QueryTask) => void
      const late = new Promise<QueryTask>((done) => {
        resolve = done
      })
      if (kind === 'read') vi.mocked(findStudentQuery).mockReturnValueOnce(late)
      else if (kind === 'start') vi.mocked(startStudentQuery).mockReturnValueOnce(late)
      else {
        vi.mocked(findStudentQuery).mockResolvedValueOnce(result())
        vi.mocked(answerStudentQuery).mockReturnValueOnce(late as never)
      }
      const wrapper = setup()
      await flushPromises()
      if (kind === 'start') {
        await click(wrapper, '核对资料')
      }
      if (kind === 'answer') {
        await answer(wrapper)
      }
      await wrapper.setProps({ credentials: { ...credentials, experimentSessionId: 'other' } })
      await flushPromises()
      resolve(result())
      await flushPromises()
      expect(wrapper.find('dl').exists()).toBe(false)
      expect(readStudentQuery).not.toHaveBeenCalled()
    },
  )
  it('ignores late failure and disables controls throughout a submission', async () => {
    let reject!: (value: unknown) => void
    vi.mocked(findStudentQuery).mockResolvedValueOnce(result())
    vi.mocked(answerStudentQuery).mockReturnValueOnce(
      new Promise((_, fail) => {
        reject = fail
      }),
    )
    const wrapper = setup()
    await flushPromises()
    await answer(wrapper)
    expect(wrapper.find('fieldset').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ credentials: { ...credentials, accessToken: 'new-login' } })
    await flushPromises()
    reject(error(403))
    await flushPromises()
    expect(wrapper.text()).not.toContain('当前无权')
    expect(wrapper.text()).toContain('尚未发起')
  })
})

it('does not confuse a saved answer with its failed GET or resubmit it', async () => {
  vi.mocked(findStudentQuery).mockResolvedValue(result())
  vi.mocked(answerStudentQuery).mockResolvedValue({
    id: 'receipt',
    request_id: 'id',
    value: 'matches_table',
  })
  vi.mocked(readStudentQuery).mockRejectedValue(error(503))
  const wrapper = setup()
  await flushPromises()
  await answer(wrapper)
  expect(wrapper.text()).toContain('读取失败')
  expect(wrapper.find('fieldset').exists()).toBe(false)
  expect(wrapper.find('.pending-answer').exists()).toBe(false)
  await click(wrapper, '重新读取状态')
  expect(answerStudentQuery).toHaveBeenCalledTimes(1)
})
it('isolates a late post-answer GET when diagnosis changes', async () => {
  let resolve!: (value: QueryTask) => void
  vi.mocked(findStudentQuery).mockResolvedValueOnce(result())
  vi.mocked(answerStudentQuery).mockResolvedValue({
    id: 'receipt',
    request_id: 'id',
    value: 'matches_table',
  })
  vi.mocked(readStudentQuery).mockReturnValueOnce(
    new Promise((done) => {
      resolve = done
    }),
  )
  const wrapper = setup()
  await flushPromises()
  await answer(wrapper)
  await wrapper.setProps({ diagnosisId: 'another-diagnosis' })
  await flushPromises()
  resolve(result({ status: 'completed_satisfied', question: null }))
  await flushPromises()
  expect(wrapper.find('dl').exists()).toBe(false)
})
it('retries a temporary start failure only on explicit click', async () => {
  vi.mocked(startStudentQuery).mockRejectedValueOnce(error(503)).mockResolvedValue(result())
  const wrapper = setup()
  await flushPromises()
  await click(wrapper, '核对资料')
  expect(startStudentQuery).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('核对暂时不可用')
  await click(wrapper, '重试核对')
  expect(startStudentQuery).toHaveBeenCalledTimes(2)
  expect(wrapper.find('dl').exists()).toBe(true)
})
it('clears content when the conflict reread is forbidden', async () => {
  vi.mocked(findStudentQuery).mockResolvedValue(result())
  vi.mocked(answerStudentQuery).mockRejectedValue(error(409))
  vi.mocked(readStudentQuery).mockRejectedValue(error(403))
  const wrapper = setup()
  await flushPromises()
  await answer(wrapper)
  expect(wrapper.find('dl').exists()).toBe(false)
  expect(wrapper.text()).toContain('当前无权')
})
