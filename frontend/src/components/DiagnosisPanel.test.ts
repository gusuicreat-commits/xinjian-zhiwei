import { mount } from '@vue/test-utils'

import type { AIStatus, StudentDiagnosis, StudentGuidance } from '@/types/student'

import DiagnosisPanel from './DiagnosisPanel.vue'

const diagnosis: StudentDiagnosis = {
  id: 'diagnosis-test',
  evaluated_at: '2026-07-20T08:00:00Z',
  is_test_data: true,
  evidence: [],
  matches: [
    {
      rule_id: 'example-rule',
      error_type: 'sensor_read_failure',
      priority: 10,
      summary: '检测到传感器读取失败事件',
      evidence: [{ fact: 'event_count', observed_value: 2, details: [] }],
    },
  ],
}

const guidance: StudentGuidance = {
  id: 'guidance-test',
  tree_id: 'example-tree',
  tree_title: '传感器读取故障示例树',
  tree_status: 'example',
  hint_level: 2,
  failure_count: 1,
  teacher_intervention_required: false,
  is_test_data: true,
  ranked_causes: [
    {
      cause_id: 'connection',
      title: '连接异常',
      score: 0.75,
      confidence: 'medium',
      evidence: [],
    },
  ],
  hints: [{ cause_id: 'connection', level: 2, text: '检查通用连接状态。' }],
}

const aiStatus: AIStatus = {
  framework_ready: true,
  provider_configured: false,
  embedding_client_configured: false,
  require_knowledge: true,
  provider: 'deepseek',
  model: 'deepseek-v4-flash',
  transport: 'openai-compatible',
  prompt_version: 'phase9.5-v1',
  notice: 'AI Provider 未配置，系统保持确定性规则诊断模式。',
  ai_enabled: false,
  local_configured: false,
  cloud_configured: false,
  thinking_enabled: false,
  production_route: 'cache → deepseek → deterministic_fallback',
}

function mountPanel(overrides: Record<string, unknown> = {}) {
  return mount(DiagnosisPanel, {
    props: {
      diagnosis: null,
      guidance: [],
      feedback: null,
      feedbackLoading: false,
      aiStatus,
      aiExplanation: null,
      aiLoading: false,
      ...overrides,
    },
    global: {
      stubs: {
        ElCard: { template: '<section><slot name="header"/><slot/></section>' },
        ElEmpty: { props: ['description'], template: '<div>{{ description }}</div>' },
        ElResult: {
          props: ['title', 'subTitle'],
          template: '<div>{{ title }} {{ subTitle }}<slot/></div>',
        },
        ElAlert: { props: ['title'], template: '<div>{{ title }}<slot/></div>' },
        ElTag: { template: '<span><slot/></span>' },
        ElButton: {
          inheritAttrs: false,
          template: '<button v-bind="$attrs"><slot/></button>',
        },
      },
    },
  })
}

describe('DiagnosisPanel', () => {
  it('shows the no-diagnosis state', () => {
    expect(mountPanel().text()).toContain('尚无诊断记录')
  })

  it('distinguishes a normal rule result from hardware certification', () => {
    const wrapper = mountPanel({ diagnosis: { ...diagnosis, matches: [] } })
    expect(wrapper.text()).toContain('当前未匹配故障规则')
    expect(wrapper.text()).toContain('不代表已完成真实硬件健康认证')
  })

  it('renders evidence, ranked causes and emits feedback', async () => {
    const wrapper = mountPanel({ diagnosis, guidance: [guidance] })
    expect(wrapper.text()).toContain('确定性示例规则')
    expect(wrapper.text()).toContain('确定性结果')
    expect(wrapper.text()).toContain('AI 增强未启用')
    expect(wrapper.text()).toContain('当前建议由确定性规则')
    expect(wrapper.text()).toContain('检测到传感器读取失败事件')
    expect(wrapper.text()).toContain('连接异常')
    expect(wrapper.text()).toContain('检查通用连接状态')

    await wrapper.findAll('button').at(-1)?.trigger('click')
    expect(wrapper.emitted('feedback')).toEqual([['request_teacher_help']])
  })
})
