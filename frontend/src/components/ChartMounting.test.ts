import { mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref, type Component } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SensorTrendChart from './SensorTrendChart.vue'
import TeacherDeviceChart from './TeacherDeviceChart.vue'
import TeacherErrorRankingChart from './TeacherErrorRankingChart.vue'
import TeacherErrorTrendChart from './TeacherErrorTrendChart.vue'

const chartMocks = vi.hoisted(() => ({
  init: vi.fn(),
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
}))
vi.mock('echarts/core', () => ({ init: chartMocks.init, use: vi.fn() }))

const examples: Array<[string, Component, Record<string, unknown>]> = [
  [
    'student readings',
    SensorTrendChart,
    {
      readings: [
        {
          id: 'reading',
          sensor_type: 'dht11',
          metric_key: 'temperature',
          value: 23.5,
          unit: '°C',
          observed_at: '2026-07-20T08:58:00Z',
        },
      ],
    },
  ],
  ['teacher devices', TeacherDeviceChart, { data: [{ status: 'online', count: 1 }] }],
  [
    'teacher error ranking',
    TeacherErrorRankingChart,
    { data: [{ error_code: 'read_failed', count: 1 }] },
  ],
  ['teacher error trend', TeacherErrorTrendChart, { data: [{ day: '2026-07-20', count: 1 }] }],
]

beforeEach(() => {
  vi.clearAllMocks()
  chartMocks.init.mockImplementation(() => ({
    setOption: chartMocks.setOption,
    resize: chartMocks.resize,
    dispose: chartMocks.dispose,
  }))
})

describe.each(examples)('%s chart lifecycle', (_name, chartComponent, chartProps) => {
  it('initializes after the parent becomes visible on the first tab switch', async () => {
    const parentDisplayAtInit: string[] = []
    chartMocks.init.mockImplementation((element: HTMLElement) => {
      parentDisplayAtInit.push((element.closest('.tab-content') as HTMLElement).style.display)
      return {
        setOption: chartMocks.setOption,
        resize: chartMocks.resize,
        dispose: chartMocks.dispose,
      }
    })
    const Harness = defineComponent({
      components: { ChartUnderTest: chartComponent },
      setup: () => ({ open: ref(false), chartProps }),
      template:
        '<button @click="open = true">Open tab</button><section v-show="open" class="tab-content"><ChartUnderTest v-if="open" v-bind="chartProps" /></section>',
    })
    const wrapper = mount(Harness, { global: { stubs: { ElEmpty: true } } })
    expect(chartMocks.init).not.toHaveBeenCalled()
    await wrapper.get('button').trigger('click')
    await nextTick()
    expect(parentDisplayAtInit).toEqual([''])
    expect(chartMocks.setOption).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('does not initialize or leak a resize handler if unmounted before the pending tick', async () => {
    const add = vi.spyOn(window, 'addEventListener')
    const remove = vi.spyOn(window, 'removeEventListener')
    const wrapper = mount(chartComponent, {
      props: chartProps,
      global: { stubs: { ElEmpty: true } },
    })
    wrapper.unmount()
    await nextTick()
    expect(chartMocks.init).not.toHaveBeenCalled()
    const handler = add.mock.calls.find(([type]) => type === 'resize')?.[1]
    expect(handler).toBeDefined()
    expect(remove).toHaveBeenCalledWith('resize', handler)
    add.mockRestore()
    remove.mockRestore()
  })

  it('disposes the initialized chart and stops resize callbacks when unmounted', async () => {
    const wrapper = mount(chartComponent, {
      props: chartProps,
      global: { stubs: { ElEmpty: true } },
    })
    await nextTick()
    expect(chartMocks.init).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new Event('resize'))
    expect(chartMocks.resize).toHaveBeenCalledTimes(1)
    wrapper.unmount()
    expect(chartMocks.dispose).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new Event('resize'))
    expect(chartMocks.resize).toHaveBeenCalledTimes(1)
  })
})
