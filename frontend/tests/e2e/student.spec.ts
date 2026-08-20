import { expect, type Page, test } from '@playwright/test'

const device = {
  device_id: 'phase6-browser-test',
  display_name: 'Phase 6 browser test',
  status: 'online',
  last_seen_at: '2026-07-20T09:00:00Z',
  firmware_version: 'test-only',
  is_test_fixture: true,
}

function dashboard(overrides: Record<string, unknown> = {}) {
  const diagnosis = overrides.diagnosis as
    { matches?: Array<{ summary?: string; error_type?: string }> } | null | undefined
  const primaryMatch = diagnosis?.matches?.[0]
  return {
    generated_at: '2026-07-20T09:00:00Z',
    task: { configured: false, title: null, template_id: null, notice: '尚未配置真实实验任务。' },
    device,
    logs: [],
    readings: [],
    diagnosis: null,
    guidance: [],
    feedback: null,
    intervention: null,
    ai_status: {
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
    },
    ai_explanation: null,
    device_state_explanation: {
      status_title: primaryMatch?.summary || '设备状态正常',
      status_summary: primaryMatch?.summary || '当前未匹配故障规则',
      meaning: primaryMatch ? '设备记录中出现了需要排查的异常。' : '当前没有观测到已知故障。',
      next_step: primaryMatch ? '请按排查建议继续检查。' : '可继续当前实验。',
      source: 'rule',
      technical_details: {
        device: {
          status: device.status,
          last_seen_at: device.last_seen_at,
          firmware_version: device.firmware_version,
        },
        error_code: primaryMatch?.error_type || null,
        error_codes: primaryMatch?.error_type ? [primaryMatch.error_type] : [],
        logs: [],
        sensor_readings: [],
        rule_hits: [],
        fault_tree_evidence: [],
      },
    },
    episode: null,
    ...overrides,
  }
}

async function mockStudentApi(page: Page, payload: ReturnType<typeof dashboard>): Promise<void> {
  await page.route('**/api/v1/diagnosis-workflows/devices/*/latest', async (route) => {
    await route.fulfill({ json: null })
  })
  await page.route('**/api/v1/student/**', async (route) => {
    const url = route.request().url()
    if (url.endsWith('/session')) {
      await route.fulfill({
        json: {
          device_id: device.device_id,
          display_name: device.display_name,
          auth_mode: 'device_credential_placeholder',
          student_user_id: 'browser-student',
          experiment_session_id: 'browser-experiment-session',
          experiment_assignment_id: 'browser-experiment-assignment',
          notice: '测试会话',
        },
      })
      return
    }
    if (url.endsWith('/dashboard')) {
      await route.fulfill({ json: payload })
      return
    }
    const feedback = {
      id: 'feedback-test',
      action: 'request_teacher_help',
      note: null,
      is_test_data: true,
      created_at: '2026-07-20T09:01:00Z',
    }
    Object.assign(payload, {
      feedback,
      intervention: {
        id: 'intervention-test',
        status: 'open',
        version_no: 1,
        assigned_teacher_user_id: null,
        resolution_summary: null,
        updated_at: '2026-07-20T09:01:00Z',
      },
    })
    await route.fulfill({
      status: 201,
      json: feedback,
    })
  })
}

async function mockStudentWorkflow(page: Page, workflow: Record<string, unknown>): Promise<void> {
  await page.route('**/api/v1/diagnosis-workflows/devices/*/latest', async (route) => {
    await route.fulfill({ json: workflow })
  })
}

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('设备 ID').fill(device.device_id)
  await page.getByPlaceholder('设备令牌').fill('browser-test-token-not-a-secret')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/student$/)
}

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

test('handles login, no-data state and session refresh', async ({ page }) => {
  const errors = collectErrors(page)
  await mockStudentApi(page, dashboard())
  await login(page)
  await expect(page.getByText('设备尚未上传日志')).toBeVisible()
  await expect(page.getByText('设备尚未上传传感器读数')).toBeVisible()
  await expect(page.getByText('当前未匹配故障规则')).toBeVisible()
  await page.reload()
  await expect(page.getByText('学生实验工作台')).toBeVisible()
  expect(errors).toEqual([])
})

test('shows a normal deterministic diagnosis with its limitation', async ({ page }) => {
  await mockStudentApi(
    page,
    dashboard({
      diagnosis: {
        id: 'normal-diagnosis',
        evaluated_at: '2026-07-20T09:00:00Z',
        matches: [],
        evidence: [],
        is_test_data: true,
      },
    }),
  )
  await login(page)
  await expect(page.getByText('当前未匹配故障规则')).toBeVisible()
  await expect(page.getByText(/不代表真实设备诊断结果/)).toBeVisible()
})

test('shows abnormal evidence and submits teacher-help feedback', async ({ page }) => {
  const errors = collectErrors(page)
  await mockStudentApi(
    page,
    dashboard({
      logs: [
        {
          id: 'log-1',
          level: 'error',
          message: '测试读取失败',
          event_code: 'SENSOR_READ_FAILED',
          occurred_at: '2026-07-20T09:00:00Z',
          is_test_data: true,
        },
      ],
      readings: [
        {
          id: 'reading-1',
          sensor_type: 'generic-test-sensor',
          metric_key: 'metric_a',
          value: 42,
          unit: 'test-unit',
          observed_at: '2026-07-20T09:00:00Z',
          is_test_data: true,
        },
      ],
      diagnosis: {
        id: 'abnormal-diagnosis',
        evaluated_at: '2026-07-20T09:00:00Z',
        is_test_data: true,
        evidence: [],
        matches: [
          {
            rule_id: 'example-rule',
            error_type: 'sensor_read_failure',
            priority: 10,
            summary: '读取失败示例命中',
            evidence: [{ fact: 'event_count', observed_value: 1, details: [] }],
          },
        ],
      },
      guidance: [
        {
          id: 'guidance-1',
          tree_id: 'example-tree',
          tree_title: '示例故障树',
          tree_status: 'placeholder',
          hint_level: 1,
          failure_count: 1,
          teacher_intervention_required: false,
          is_test_data: true,
          ranked_causes: [
            {
              cause_id: 'connection',
              title: '连接异常',
              score: 0.2,
              confidence: 'low',
              evidence: [],
            },
          ],
          hints: [{ cause_id: 'connection', level: 1, text: '检查通用连接状态。' }],
        },
      ],
    }),
  )
  await login(page)
  await expect(page.getByRole('heading', { name: '读取失败示例命中' })).toBeVisible()
  await expect(page.getByText('连接异常')).toBeVisible()
  await page.getByRole('button', { name: '请求教师协助' }).click()
  await expect(page.getByText('已记录：请求教师协助')).toBeVisible()
  await expect(page.getByText('求助已提交，等待教师认领')).toBeVisible()
  expect(errors).toEqual([])
})

test('shows workflow provenance, missing evidence and teacher review history', async ({ page }) => {
  const payload = dashboard({
    diagnosis: {
      id: 'workflow-diagnosis',
      evaluated_at: '2026-07-20T09:00:00Z',
      is_test_data: true,
      evidence: [],
      matches: [
        {
          rule_id: 'rule-workflow',
          error_type: 'sensor_read_failure',
          priority: 10,
          summary: '读取失败',
          evidence: [{ fact: 'event_count', observed_value: 2, details: [] }],
        },
      ],
    },
  })
  await mockStudentApi(page, payload)
  await mockStudentWorkflow(page, {
    id: 'workflow-browser',
    diagnosis_result_id: 'workflow-diagnosis',
    device_id: device.device_id,
    graph_thread_id: 'diagnosis:workflow-browser',
    graph_version: 'langgraph-v1',
    status: 'completed',
    current_node: 'persist_result',
    evidence_score: 0.6,
    guidance_level: 3,
    needs_rag: true,
    needs_teacher: true,
    rule_engine_version: 'rules-v3',
    fault_tree_version: 'tree-v2',
    embedding_version: 'embedding-v1',
    model_id: 'model-v1',
    node_trace: ['collect_context', 'run_rules', 'retrieve_knowledge', 'persist_result'],
    final_result: {
      summary: '建议检查连接',
      limitations: ['缺少供电电压读数'],
      rule_hits: [
        {
          rule_id: 'rule-workflow',
          error_type: 'sensor_read_failure',
          summary: '读取失败',
          evidence: [{ fact: 'event_count', observed_value: 2 }],
        },
      ],
      candidate_causes: [
        { cause_id: 'connection', name: '连接异常', score: 0.75, evidence_refs: ['log:1'] },
      ],
      knowledge_references: [
        {
          chunk_id: 'chunk-1',
          source_id: 'manual-sensor',
          title: '传感器手册',
          score: 0.83,
          metadata: { source_version: '2026.1', review_status: 'approved' },
        },
      ],
    },
    error_messages: [],
    review_request: null,
    reviews: [
      {
        id: 'review-1',
        reviewer_user_id: 'teacher-1',
        action: 'approve',
        comment: '证据可用',
        edited_result: null,
        created_at: '2026-07-20T09:10:00Z',
      },
    ],
    is_test_data: true,
    created_at: '2026-07-20T09:00:00Z',
    updated_at: '2026-07-20T09:10:00Z',
    completed_at: '2026-07-20T09:10:00Z',
  })

  await login(page)
  await expect(page.getByText('辅助诊断进度')).toBeVisible()
  await expect(page.getByText('当前判断')).toBeVisible()
  await expect(page.getByText('设备运行记录、可能原因分析、1 份已审核操作资料')).toBeVisible()
  await expect(page.getByText('manual-sensor / chunk-1')).toHaveCount(0)
  await expect(page.getByText('RRF 0.8300')).toHaveCount(0)
  await expect(page.getByText('缺少供电电压读数')).toBeVisible()
  await expect(page.getByText('审核详情仅教师可见')).toBeVisible()
  await expect(page.getByText('证据可用')).toHaveCount(0)
  await expect(page.getByText('teacher-1')).toHaveCount(0)
  await expect(page.getByText('collect_context')).toHaveCount(0)
})
