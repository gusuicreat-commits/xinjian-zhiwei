import { mount } from '@vue/test-utils'

import type {
  AIStatus,
  DeviceStateExplanation,
  StudentDiagnosis,
  StudentGuidance,
} from '@/types/student'
import type { DiagnosisWorkflowRecord } from '@/types/workflow'

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

const deviceStateExplanation: DeviceStateExplanation = {
  status_title: '温度传感器读取异常',
  status_summary: '开发板仍在线，但温度传感器暂时无法正常读取。',
  meaning: '问题更可能发生在传感器通信环节，而不是整个开发板掉线。',
  next_step: '请先检查传感器接线及对应配置。',
  source: 'rule',
  technical_details: {
    device: { status: 'online', last_seen_at: '2026-07-20T08:00:00Z', firmware_version: '1.0' },
    error_code: 'SENSOR_READ_FAILED',
    error_codes: ['SENSOR_READ_FAILED'],
    retry_count: 3,
    logs: [
      {
        id: 'log-1',
        level: 'error',
        message: 'I2C ACK FAILED',
        event_code: 'SENSOR_READ_FAILED',
        occurred_at: '2026-07-20T08:00:00Z',
      },
    ],
    sensor_readings: [
      {
        id: 'reading-1',
        sensor_type: 'temperature',
        metric_key: 'temperature',
        value: 20,
        unit: '°C',
        observed_at: '2026-07-20T07:59:00Z',
      },
    ],
    rule_hits: diagnosis.matches,
    fault_tree_evidence: [
      {
        tree_id: guidance.tree_id,
        tree_title: guidance.tree_title,
        tree_status: guidance.tree_status,
        hint_level: guidance.hint_level,
        failure_count: guidance.failure_count,
        ranked_causes: guidance.ranked_causes,
      },
    ],
  },
}

const workflow: DiagnosisWorkflowRecord = {
  id: 'workflow-test',
  diagnosis_result_id: 'diagnosis-test',
  device_id: 'device-test',
  graph_thread_id: 'diagnosis:workflow-test',
  graph_version: 'langgraph-v2',
  status: 'waiting_teacher',
  current_node: 'teacher_review',
  evidence_score: 0.61,
  guidance_level: 4,
  needs_rag: true,
  needs_teacher: true,
  rule_engine_version: 'rules-v3',
  fault_tree_version: 'tree-v2',
  embedding_version: 'embedding-v1',
  model_id: 'model-v1',
  node_trace: [
    'context_builder',
    'rule_engine',
    'fault_tree_analyzer',
    'knowledge_context',
    'ai_reasoning',
    'knowledge_validation',
    'ai_explanation',
    'feedback_handler',
    'escalation_handler',
    'teacher_review',
  ],
  final_result: null,
  error_messages: [],
  review_request: {
    rule_hits: [
      {
        rule_id: 'example-rule',
        error_type: 'sensor_read_failure',
        summary: '传感器读取失败',
        evidence: [{ fact: 'event_count', observed_value: 2 }],
      },
    ],
    candidates: [
      {
        cause_id: 'connection',
        name: '连接异常',
        score: 0.75,
        evidence_refs: ['log:log-1'],
      },
    ],
    retrieved_chunks: [
      {
        chunk_id: 'chunk-1',
        source_id: 'manual-sensor',
        title: '传感器手册',
        score: 0.83,
        metadata: { source_version: '2026.1', review_status: 'approved' },
      },
    ],
    ai_result: { summary: '建议检查连接', limitations: ['缺少供电电压读数'] },
  },
  reviews: [
    {
      id: 'review-1',
      reviewer_user_id: 'teacher-1',
      action: 'edit',
      comment: '已补充排查顺序',
      edited_result: { summary: '先检查连接' },
      created_at: '2026-07-20T08:10:00Z',
    },
  ],
  is_test_data: true,
  created_at: '2026-07-20T08:00:00Z',
  updated_at: '2026-07-20T08:10:00Z',
  completed_at: null,
}

function mountPanel(overrides: Record<string, unknown> = {}) {
  return mount(DiagnosisPanel, {
    props: {
      diagnosis: null,
      guidance: [],
      feedback: null,
      intervention: null,
      feedbackLoading: false,
      aiStatus,
      aiExplanation: null,
      aiLoading: false,
      workflow: null,
      workflowLoading: false,
      hasExperimentSession: true,
      deviceStateExplanation,
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
    expect(mountPanel().text()).toContain('温度传感器读取异常')
  })

  it('distinguishes a normal rule result from hardware certification', () => {
    const wrapper = mountPanel({
      diagnosis: { ...diagnosis, matches: [] },
      deviceStateExplanation: {
        ...deviceStateExplanation,
        status_title: '设备当前在线',
        status_summary: '当前没有命中已配置的异常规则。',
        meaning: '不代表已完成真实硬件健康认证。',
      },
    })
    expect(wrapper.text()).toContain('当前没有命中已配置的异常规则')
  })

  it('renders evidence, ranked causes and emits feedback', async () => {
    const wrapper = mountPanel({ diagnosis, guidance: [guidance] })
    expect(wrapper.text()).toContain('规则解释')
    expect(wrapper.text()).toContain('确定性结果')
    expect(wrapper.text()).toContain('AI 增强未启用')
    expect(wrapper.text()).toContain('当前建议由确定性规则')
    expect(wrapper.text()).toContain('检测到传感器读取失败事件')
    expect(wrapper.text()).toContain('连接异常')
    expect(wrapper.text()).toContain('检查通用连接状态')
    expect(wrapper.text()).toContain('这意味着什么')
    expect(wrapper.text()).toContain('建议先做什么')
    expect(wrapper.text()).toContain('查看技术详情')
    expect(wrapper.text()).toContain('SENSOR_READ_FAILED')
    expect(wrapper.text()).toContain('I2C ACK FAILED')
    expect(wrapper.text()).toContain('连续重试')

    await wrapper.findAll('button').at(-1)?.trigger('click')
    expect(wrapper.emitted('feedback')).toEqual([['request_teacher_help']])
  })

  it('shows the public teacher resolution returned by the workflow', () => {
    const wrapper = mountPanel({
      diagnosis,
      guidance: [guidance],
      intervention: {
        id: 'case-test',
        status: 'resolved',
        version_no: 3,
        assigned_teacher_user_id: 'teacher-test',
        resolution_summary: '已指导重新连接传感器并确认读数恢复。',
        updated_at: '2026-07-20T08:10:00Z',
      },
    })
    expect(wrapper.text()).toContain('教师已标记为解决')
  })

  it('shows only student-facing workflow progress and guidance', () => {
    const wrapper = mountPanel({ diagnosis, guidance: [guidance], workflow })
    const workflowPanel = wrapper.findAll('.ai-explanation-panel')[1]

    expect(workflowPanel.text()).toContain('辅助诊断进度')
    expect(workflowPanel.text()).toContain('结果已提交教师确认')
    expect(workflowPanel.text()).toContain('当前判断')
    expect(workflowPanel.text()).toContain('建议检查连接')
    expect(workflowPanel.text()).toContain('设备运行记录、可能原因分析、1 份已审核操作资料')
    expect(workflowPanel.text()).toContain('缺少供电电压读数')
    expect(workflowPanel.text()).toContain('修订并批准')
    expect(workflowPanel.text()).toContain('审核详情仅教师可见')
    expect(workflowPanel.text()).not.toContain('LangGraph')
    expect(workflowPanel.text()).not.toContain('rules-v3')
    expect(workflowPanel.text()).not.toContain('context_builder')
    expect(workflowPanel.text()).not.toContain('manual-sensor')
    expect(workflowPanel.text()).not.toContain('RRF')
    expect(wrapper.text()).not.toContain('teacher-1')
    expect(wrapper.text()).not.toContain('已补充排查顺序')
    expect(wrapper.text()).not.toContain('先检查连接')
  })

  it('does not expose unapproved retrieval details to students', () => {
    const wrapper = mountPanel({
      diagnosis,
      guidance: [guidance],
      workflow: {
        ...workflow,
        review_request: {
          ...workflow.review_request,
          retrieved_chunks: [
            {
              chunk_id: 'chunk-pending',
              source_id: 'draft-manual',
              title: '待审核手册',
              score: 0.03125,
              metadata: { source_version: 'draft', review_status: 'pending' },
            },
          ],
        },
      },
    })

    const workflowPanel = wrapper.findAll('.ai-explanation-panel')[1]
    expect(workflowPanel.text()).not.toContain('待审核手册')
    expect(workflowPanel.text()).not.toContain('draft-manual')
    expect(workflowPanel.text()).not.toContain('RRF')
    expect(workflowPanel.text()).not.toContain('已审核操作资料')
  })

  it('accepts a student-safe workflow with private review payloads omitted', () => {
    const wrapper = mountPanel({
      diagnosis,
      guidance: [guidance],
      workflow: {
        ...workflow,
        status: 'completed',
        review_request: undefined,
        reviews: undefined,
        node_metrics: undefined,
        retrieval_audit: undefined,
        final_result: {
          summary: '公开诊断结论',
          limitations: ['公开限制'],
          rule_hits: workflow.review_request?.rule_hits,
          candidate_causes: workflow.review_request?.candidates,
          knowledge_references: workflow.review_request?.retrieved_chunks,
        },
      },
    })

    expect(wrapper.text()).toContain('公开诊断结论')
    expect(wrapper.text()).toContain('公开限制')
    expect(wrapper.text()).not.toContain('教师审核历史')
  })

  it.each([
    ['created', '流程已创建'],
    ['collecting', '正在采集诊断上下文'],
    ['deterministic_analysis', '正在执行确定性诊断'],
    ['retrieving', '正在检索已审核知识'],
    ['ai_analysis', '正在生成辅助解释'],
    ['waiting_teacher', '等待教师审核'],
    ['completed', '流程完成'],
    ['rejected', '教师已驳回'],
    ['failed', '流程失败，确定性规则结果仍可用'],
  ] as const)('maps the %s workflow state for students', (status, label) => {
    const wrapper = mountPanel({
      diagnosis,
      guidance: [guidance],
      workflow: { ...workflow, status },
    })

    expect(wrapper.text()).toContain(label)
  })
})

it('lets a valid new session start its first workflow without a previous diagnosis', async () => {
  const wrapper = mountPanel({ diagnosis: null, workflow: null, hasExperimentSession: true })
  const button = wrapper.findAll('button').find((item) => item.text() === '启动辅助诊断')!
  expect(button.exists()).toBe(true)
  expect(button.attributes('disabled')).toBeUndefined()
  await button.trigger('click')
  expect(wrapper.emitted('requestWorkflow')).toEqual([[]])
})

it('explains and disables starting a workflow without an experiment session', async () => {
  const wrapper = mountPanel({ diagnosis: null, workflow: null, hasExperimentSession: false })
  const button = wrapper.findAll('button').find((item) => item.text() === '启动辅助诊断')!
  expect(button.attributes('disabled')).toBeDefined()
  expect(wrapper.text()).toContain('请先连接有效的实验会话')
  await button.trigger('click')
  expect(wrapper.emitted('requestWorkflow')).toBeUndefined()
})
