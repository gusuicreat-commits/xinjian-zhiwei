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
        ElSelect: {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: `<select :value="modelValue" @change="$emit('update:modelValue', $event.target.value)"><slot/></select>`,
        },
        ElOption: {
          props: ['value', 'label'],
          template: '<option :value="value">{{ label }}</option>',
        },
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
    expect(wrapper.text()).toContain('接下来：')
    expect(wrapper.text()).toContain('查看技术详情')
    expect(wrapper.text()).toContain('SENSOR_READ_FAILED')
    expect(wrapper.text()).toContain('I2C ACK FAILED')
    expect(wrapper.text()).toContain('连续重试')

    await wrapper
      .findAll('button')
      .find((button) => button.text() === '请求教师协助')!
      .trigger('click')
    expect(wrapper.emitted('feedback')).toEqual([['request_teacher_help', null]])
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
    expect(wrapper.text()).toContain('教师已完成工单处理（不代表硬件复测通过）')
  })

  it('shows only student-facing workflow progress and guidance', () => {
    const wrapper = mountPanel({ diagnosis, guidance: [guidance], workflow })
    const workflowPanel = wrapper.findAll('.ai-explanation-panel')[1]

    expect(workflowPanel.text()).toContain('辅助诊断进度')
    expect(workflowPanel.text()).toContain('结果已提交教师确认')
    expect(workflowPanel.text()).toContain('本工作流记录的判断')
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
  const button = wrapper.findAll('button').find((item) => item.text() === '检查当前数据')!
  expect(button.exists()).toBe(true)
  expect(button.attributes('disabled')).toBeUndefined()
  await button.trigger('click')
  expect(wrapper.emitted('requestWorkflow')).toEqual([[]])
})

it('explains and disables starting a workflow without an experiment session', async () => {
  const wrapper = mountPanel({ diagnosis: null, workflow: null, hasExperimentSession: false })
  const button = wrapper.findAll('button').find((item) => item.text() === '检查当前数据')!
  expect(button.attributes('disabled')).toBeDefined()
  expect(wrapper.text()).toContain('请先连接有效的实验会话')
  await button.trigger('click')
  expect(wrapper.emitted('requestWorkflow')).toBeUndefined()
})

it('keeps same-error component guidance separate until a problem is selected', async () => {
  const wrapper = mountPanel({
    diagnosis,
    issues: ['a', 'b'].map((id) => ({
      id,
      error_type: 'read_failed',
      status: 'open',
      failure_count: 1,
      resolution_source: null,
      scope: { kind: 'component', keys: [id] },
    })),
    guidance: ['a', 'b'].map((id) => ({
      ...guidance,
      id,
      episode_id: id,
      hints: [
        {
          cause_id: id,
          level: 1,
          text: `只检查部件${id}`,
          teaching: {
            contract_version: 'teaching-reference-v1',
            status: 'available',
            experiment_version_id: 'v',
            package_version: '2.0.3',
            package_hash: 'h',
            is_test_data: true,
            steps: [],
            concepts: [{ concept_id: id, description: `部件${id}专属知识`, references: [] }],
          },
        },
      ],
    })),
  })
  expect(wrapper.text()).not.toContain('只检查部件a')
  expect(wrapper.text()).not.toContain('只检查部件b')
  await wrapper.find('select').setValue('a')
  expect(wrapper.text()).toContain('只检查部件a')
  expect(wrapper.text()).not.toContain('只检查部件b')
  expect(wrapper.text()).toContain('部件a专属知识')
  expect(wrapper.text()).not.toContain('部件b专属知识')
  const button = wrapper.findAll('button').find((item) => item.text() === '仍未解决')!
  await button.trigger('click')
  expect(wrapper.emitted('feedback')?.[0]).toEqual(['unresolved', 'a'])
})

it('shows one check entry and explains first check versus continuing old guidance', () => {
  const wrapper = mountPanel()
  const focus = wrapper.get('[aria-label="现在该做什么"]')
  expect(focus.text()).toContain('先检查已上传的数据')
  expect(focus.text()).toContain('刷新页面不会启动诊断')
  expect(
    wrapper.findAll('button').filter((button) => button.text() === '检查当前数据'),
  ).toHaveLength(1)
})
it('uses only selected issue guidance and does not recommend a different component action', async () => {
  const wrapper = mountPanel({
    diagnosis,
    issues: ['a', 'b'].map((id) => ({
      id,
      error_type: 'sensor_read_failure',
      scope: { kind: 'component', keys: [id] },
      status: 'open',
    })),
    guidance: ['a', 'b'].map((id) => ({
      ...guidance,
      id,
      episode_id: id,
      hints: [{ cause_id: id, level: 1, text: '检查组件' + id }],
    })),
  })
  const focus = wrapper.get('[aria-label="现在该做什么"]')
  expect(focus.text()).toContain('请先选择')
  expect(focus.text()).not.toContain('检查组件a')
  await wrapper.get('select').setValue('b')
  expect(focus.find('h2').text()).toBe('b · 暂未提供通俗说明')
  expect(wrapper.get('.guidance-work').text()).toContain('检查组件b')
  expect(wrapper.get('.guidance-work').text()).not.toContain('检查组件a')
})
it('read-only data cannot submit checks, AI requests or feedback', () => {
  const wrapper = mountPanel({ diagnosis, guidance: [guidance], readOnly: true })
  expect(wrapper.get('[aria-label="现在该做什么"]').text()).toContain('暂不能提交操作')
  for (const button of wrapper.findAll('button'))
    expect(button.attributes('disabled')).toBeDefined()
})

it('keeps every currently allowed step adjacent to feedback, with supporting records initially collapsed', () => {
  const wrapper = mountPanel({
    diagnosis,
    guidance: [
      {
        ...guidance,
        hints: [
          { cause_id: 'one', level: 1, text: '第一条允许的检查' },
          { cause_id: 'two', level: 2, text: '第二条允许的检查' },
          { cause_id: 'three', level: 2, text: '第三条允许的检查' },
        ],
      },
    ],
  })
  const task = wrapper.get('[aria-label="当前问题的排查与反馈"]')
  expect(task.findAll('.hint-action').map((item) => item.text())).toEqual([
    '第一条允许的检查',
    '第二条允许的检查',
    '第三条允许的检查',
  ])
  expect(task.get('.feedback-actions').exists()).toBe(true)
  expect(wrapper.get('.diagnosis-records').attributes('open')).toBeUndefined()
  expect(wrapper.get('.reference-work').isVisible()).toBe(false)
  expect(wrapper.get('.causes-panel').text()).toContain('不是发生概率')
})

it('does not present overall actions or another component summary as the selected issue guidance', async () => {
  const wrapper = mountPanel({
    diagnosis: {
      ...diagnosis,
      matches: [{ ...diagnosis.matches[0], summary: '仅组件a的现象说明' }],
      explanation: { summary: '整次说明', steps: ['只在整体旧解释中的动作'], limitations: [] },
    },
    issues: ['a', 'b'].map((id) => ({
      id,
      error_type: 'sensor_read_failure',
      scope: { kind: 'component', keys: [id] },
      status: 'open',
    })),
    guidance: [
      { ...guidance, episode_id: 'a', hints: [{ cause_id: 'a', level: 1, text: '组件a的操作' }] },
    ],
    deviceStateExplanation: { ...deviceStateExplanation, next_step: '只属于整体状态的操作' },
  })
  expect(wrapper.get('.guidance-work').text()).not.toContain('组件a的操作')
  expect(wrapper.get('[aria-label="现在该做什么"]').text()).not.toContain('只属于整体状态的操作')
  expect(
    wrapper
      .findAll('button')
      .filter((button) => ['问题已解决', '仍未解决', '请求教师协助'].includes(button.text()))
      .every((button) => button.attributes('disabled') !== undefined),
  ).toBe(true)
  await wrapper.get('select').setValue('b')
  const focus = wrapper.get('[aria-label="现在该做什么"]')
  expect(focus.get('h2').text()).toBe('b · 暂未提供通俗说明')
  expect(focus.text()).not.toContain('仅组件a的现象说明')
  expect(focus.text()).not.toContain('只属于整体状态的操作')
  expect(wrapper.get('.guidance-work').text()).not.toContain('组件a的操作')
  expect(wrapper.text()).not.toContain('只在整体旧解释中的动作')
  expect(wrapper.get('.diagnosis-records').text()).toContain('属于整次诊断')
})

it('preserves selected issue and expanded records across work and reference views without issuing requests', async () => {
  const wrapper = mountPanel({
    diagnosis,
    issues: ['a', 'b'].map((id) => ({
      id,
      error_type: 'read_failed',
      status: 'open',
      scope: { kind: 'component', keys: [id] },
    })),
    guidance: ['a', 'b'].map((id) => ({
      ...guidance,
      id,
      episode_id: id,
      hints: [
        {
          cause_id: id,
          level: 1,
          text: `只检查${id}`,
          teaching: {
            contract_version: 'teaching-reference-v1',
            status: 'available',
            package_version: '2.0.3',
            is_test_data: true,
            steps: [],
            concepts: [{ concept_id: id, description: `仅${id}的知识`, references: [] }],
          },
        },
      ],
    })),
  })
  await wrapper.get('select').setValue('b')
  const records = wrapper.get('.diagnosis-records')
  records.element.setAttribute('open', '')
  await wrapper.setProps({ view: 'reference' })
  expect(wrapper.get('.work-view').isVisible()).toBe(false)
  expect(wrapper.get('.reference-work').isVisible()).toBe(true)
  expect(wrapper.get('.reference-work').text()).toContain('仅b的知识')
  expect(wrapper.get('.reference-work').text()).not.toContain('仅a的知识')
  wrapper.get('.reference-work .teaching-reference').element.setAttribute('open', '')
  await wrapper.setProps({ view: 'work' })
  expect(wrapper.get('.diagnosis-records').element).toBe(records.element)
  expect(wrapper.get('.diagnosis-records').attributes('open')).toBe('')
  expect(wrapper.get('select').element.value).toBe('b')
  await wrapper
    .findAll('button')
    .find((button) => button.text() === '仍未解决')!
    .trigger('click')
  expect(wrapper.emitted('feedback')).toEqual([['unresolved', 'b']])
  await wrapper.setProps({ view: 'reference' })
  expect(wrapper.get('.reference-work .teaching-reference').attributes('open')).toBe('')
  expect(wrapper.emitted('requestWorkflow')).toBeUndefined()
  expect(wrapper.emitted('requestAi')).toBeUndefined()
})

it('keeps saved AI provenance separate from current disabled configuration and exposes limitations outside details', () => {
  const wrapper = mountPanel({
    diagnosis,
    guidance: [guidance],
    aiStatus,
    aiExplanation: {
      diagnosis_result_id: diagnosis.id,
      status: 'succeeded',
      notice: '已保存的解释',
      explanation: {
        summary: '已有 AI 解释',
        steps: ['合法原步骤'],
        limitations: ['尚未核验供电'],
      },
    },
  })
  expect(wrapper.text()).toContain('已保存 AI 解释')
  expect(wrapper.text()).toContain('当前 AI 增强未启用')
  const limits = wrapper.get('[aria-label="诊断限制"]')
  expect(limits.text()).toContain('尚未核验供电')
  expect(limits.element.closest('details')).toBeNull()
  expect(
    wrapper
      .findAll('button')
      .find((button) => button.text() === 'AI 增强未启用')!
      .attributes('disabled'),
  ).toBeDefined()
})

it.each([false, true])(
  'keeps unknown and unverified requests visible (structured=%s)',
  (structured) => {
    const wrapper = mountPanel({
      diagnosis: { ...diagnosis, explanation: { limitations: ['规则限制一', '规则限制二'] } },
      workflow: {
        ...workflow,
        final_result: {
          summary: '工作流说明',
          limitations: ['工作流限制一', '工作流限制二'],
          ai_reasoning: {
            status: 'unknown',
            conflict: true,
            ...(structured
              ? {
                  verification_requests: [
                    {
                      text: '独立电压测量',
                      source: 'model' as const,
                      status: 'unverified' as const,
                    },
                  ],
                }
              : { missing_evidence: ['独立电压测量'] }),
          },
        },
      },
    })
    const focus = wrapper.get('[aria-label="现在该做什么"]')
    for (const value of [
      '规则限制一',
      '规则限制二',
      '工作流限制一',
      '工作流限制二',
      '仍为未知',
      '证据存在冲突',
      '独立电压测量',
    ])
      expect(focus.text()).toContain(value)
    expect(focus.text()).toContain('建议核验（尚未确认）：独立电压测量')
    expect(focus.text()).not.toContain('尚缺：')
    expect(focus.element.closest('details')).toBeNull()
  },
)

it('does not show a feedback record for another selected problem', async () => {
  const wrapper = mountPanel({
    diagnosis,
    issues: ['a', 'b'].map((id) => ({
      id,
      error_type: 'read_failed',
      status: 'open',
      scope: { keys: [id] },
    })),
    feedback: { episode_id: 'a', action: 'resolved' },
  })
  await wrapper.get('select').setValue('b')
  expect(wrapper.find('.feedback-record').exists()).toBe(false)
  await wrapper.get('select').setValue('a')
  expect(wrapper.get('.feedback-record').text()).toContain('问题已解决')
})

it('keeps original-request confirmation separate from new feedback while a check is pending', async () => {
  const wrapper = mountPanel({ diagnosis, guidance: [guidance], checkPending: true })
  expect(wrapper.get('[aria-label="现在该做什么"]').text()).toContain('沿用原请求')
  const feedbackButton = wrapper.findAll('button').find((button) => button.text() === '仍未解决')!
  expect(feedbackButton.attributes('disabled')).toBeDefined()
  await feedbackButton.trigger('click')
  expect(wrapper.emitted('feedback')).toBeUndefined()
  await wrapper
    .findAll('button')
    .find((button) => button.text() === '确认上次检查结果')!
    .trigger('click')
  expect(wrapper.emitted('requestWorkflow')).toEqual([[]])
})

it('keeps unlinked teaching references as an empty state without generating material', () => {
  const wrapper = mountPanel({ view: 'reference', diagnosis, guidance: [] })
  expect(wrapper.get('.reference-work').text()).toContain('当前没有明确关联的教学资料')
  expect(wrapper.find('.teaching-reference').exists()).toBe(false)
  expect(wrapper.emitted('requestAi')).toBeUndefined()
})

it('deduplicates identical limitation text while retaining every actual source', () => {
  const wrapper = mountPanel({
    diagnosis: { ...diagnosis, explanation: { limitations: ['同一条限制'] } },
    workflow: { ...workflow, final_result: { limitations: ['同一条限制'] } },
    aiExplanation: {
      diagnosis_result_id: diagnosis.id,
      status: 'succeeded',
      explanation: { summary: '已存解释', steps: [], limitations: ['同一条限制'] },
    },
  })
  const list = wrapper.get('[aria-label="诊断限制"]')
  expect(list.findAll('li')).toHaveLength(1)
  expect(list.text()).toContain('规则诊断、已保存 AI 解释、本工作流')
  expect(list.text()).toContain('同一条限制')
})

it('keeps each associated teaching reference expandable next to its current step', async () => {
  const wrapper = mountPanel({
    diagnosis,
    guidance: [
      {
        ...guidance,
        hints: [
          {
            cause_id: 'connection',
            level: 2,
            text: '检查当前连接状态',
            teaching: {
              contract_version: 'teaching-reference-v1',
              status: 'available',
              package_version: '2.0.3',
              is_test_data: true,
              steps: [
                {
                  step_id: 'step-1',
                  title: '接线检查',
                  expected_state: '取得新的独立读数',
                  prerequisite_step_ids: [],
                },
              ],
              concepts: [
                { concept_id: 'concept-1', description: '仅此步骤的参考说明', references: [] },
              ],
            },
          },
        ],
      },
    ],
  })
  const step = wrapper.get('.guidance-work .guidance-hint')
  expect(step.get('.hint-action').text()).toBe('检查当前连接状态')
  const reference = step.get('.teaching-reference')
  expect(step.isVisible()).toBe(true)
  expect(reference.get('summary').text()).toBe('为什么这样检查 · 实验参考')
  expect(reference.get('summary').element.parentElement).toBe(reference.element)
  expect(reference.attributes('open')).toBeUndefined()
  expect(reference.text()).toContain('仅此步骤的参考说明')
  expect(reference.text()).toContain('测试资料，待硬件与教师确认')
  expect(reference.text()).toContain('预期观察（不是实测结果）')
  reference.element.setAttribute('open', '')
  await wrapper.setProps({ view: 'reference' })
  await wrapper.setProps({ view: 'work' })
  expect(wrapper.get('.guidance-work .teaching-reference').element).toBe(reference.element)
  expect(wrapper.get('.guidance-work .teaching-reference').attributes('open')).toBe('')
  expect(wrapper.emitted('requestAi')).toBeUndefined()
  expect(wrapper.emitted('requestWorkflow')).toBeUndefined()
})

it('shows the saved AI source beside the main summary even with no limitations and AI currently disabled', () => {
  const wrapper = mountPanel({
    diagnosis,
    aiStatus,
    deviceStateExplanation: {
      ...deviceStateExplanation,
      source: 'ai',
      status_summary: '本次已保存的综合说明',
    },
  })
  const main = wrapper.get('[aria-label="现在该做什么"]')
  expect(main.get('.primary-summary').text()).toBe('本次已保存的综合说明')
  expect(main.get('.summary-source').text()).toContain('已保存的 AI 综合解释')
  expect(main.get('.summary-source').element.closest('details')).toBeNull()
  expect(wrapper.find('[aria-label="诊断限制"]').exists()).toBe(false)
  expect(wrapper.get('.ai-availability').text()).toContain('当前 AI 增强未启用')
})
