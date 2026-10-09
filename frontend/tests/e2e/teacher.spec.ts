import { auditLayout } from './layoutAudit'
import { expect, test, type Page } from '@playwright/test'

async function mockTeacherWorkspace(page: Page, extraPermissions: string[] = []) {
  await page.route('**/api/v1/auth/session', async (route) => {
    await route.fulfill({
      json: {
        access_token: 'browser-test-bearer-token',
        token_type: 'bearer',
        expires_at: '2099-07-25T08:00:00Z',
        user_id: 'browser-test-teacher',
        username: 'browser-teacher',
        display_name: '浏览器测试教师',
        roles: ['teacher'],
        permissions: ['dashboard.read', 'class.read', ...extraPermissions],
        is_test_data: true,
      },
    })
  })

  await page.route('**/api/v1/teacher/dashboard', async (route) => {
    await route.fulfill({
      json: {
        generated_at: '2026-07-25T08:00:00Z',
        data_notice: '以下均为明确标记的测试数据。',
        metrics: {
          online_devices: 1,
          offline_devices: 1,
          never_seen_devices: 0,
          abnormal_devices: 1,
          experiment_completion_rate: null,
        },
        device_status: [
          { status: 'online', count: 1 },
          { status: 'offline', count: 1 },
          { status: 'abnormal', count: 1 },
        ],
        error_ranking: [{ error_code: 'SENSOR_READ_FAILED', count: 5, test_data_only: true }],
        error_trend: [
          { day: '2026-07-24', count: 2 },
          { day: '2026-07-25', count: 5 },
        ],
        class_progress: { configured: false, notice: '正式班级任务尚未配置。' },
        anomalies: [
          {
            device_id: 'phase9-browser-device',
            device_name: 'Phase 9 浏览器测试设备',
            device_status: 'online',
            latest_error_code: 'SENSOR_READ_FAILED',
            latest_summary: '确定性规则测试异常',
            evaluated_at: '2026-07-25T08:00:00Z',
            is_test_data: true,
            student_identity_configured: false,
          },
        ],
        recent_logs: [
          {
            id: 'teacher-log-1',
            device_id: 'phase9-browser-device',
            level: 'error',
            message: 'Phase 9 browser test log',
            event_code: 'SENSOR_READ_FAILED',
            occurred_at: '2026-07-25T08:00:00Z',
            is_test_data: true,
          },
        ],
        interventions: [
          {
            case_id: 'phase9-case',
            source: 'student_request',
            status: 'open',
            version_no: 1,
            assigned_teacher_user_id: null,
            resolution_summary: null,
            device_id: 'phase9-browser-device',
            diagnosis_result_id: 'phase9-diagnosis',
            tree_title: '测试故障树',
            failure_count: 5,
            anomaly_duration_seconds: 600,
            created_at: '2026-07-25T08:00:00Z',
            is_test_data: true,
            student_identity_configured: false,
          },
        ],
        knowledge_cases: {
          configured: true,
          framework_ready: true,
          case_count: 5,
          approved_case_count: 4,
          notice: '仅为 Phase 9 合成测试知识。',
        },
      },
    })
  })

  await page.route('**/api/v1/diagnosis-workflows/review-queue/pending', async (route) => {
    await route.fulfill({
      json: [
        {
          id: 'workflow-pending',
          diagnosis_result_id: 'phase9-diagnosis',
          device_id: 'phase9-browser-device',
          graph_thread_id: 'diagnosis:workflow-pending',
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
            'ai_reasoning',
            'knowledge_context',
            'knowledge_validation',
            'teacher_review',
          ],
          node_metrics: [{ node: 'rule_engine', duration_ms: 2.5, status: 'succeeded' }],
          final_result: null,
          error_messages: [],
          review_request: {
            rule_hits: [
              {
                rule_id: 'rule-workflow',
                error_type: 'SENSOR_READ_FAILED',
                summary: '读取失败',
                evidence: [{ fact: 'event_count', observed_value: 5 }],
              },
            ],
            candidates: [
              { cause_id: 'connection', name: '连接异常', score: 0.75, evidence_refs: ['log:1'] },
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
            ai_result: { summary: '建议检查连接', limitations: ['缺少电压读数'] },
          },
          reviews: [],
          is_test_data: true,
          created_at: '2026-07-25T08:00:00Z',
          updated_at: '2026-07-25T08:00:00Z',
          completed_at: null,
        },
      ],
    })
  })

  await page.route('**/api/v1/diagnosis-workflows/review-queue/recent', async (route) => {
    await route.fulfill({ json: [] })
  })

  await page.route('**/api/v1/diagnosis-workflows/metrics/summary', async (route) => {
    await route.fulfill({
      json: {
        total: 4,
        completed: 1,
        waiting_teacher: 1,
        rejected: 1,
        failed: 0,
        reviewed: 2,
        edit_rate: 0.5,
        reject_rate: 0.5,
        needs_rag_count: 2,
        resume_count: 2,
        average_node_duration_ms: 12.5,
      },
    })
  })
}

test('organizes teacher tasks without losing evidence or writing on navigation', async ({
  page,
}) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => consoleErrors.push(error.message))

  await mockTeacherWorkspace(page)

  await page.setViewportSize({ width: 1195, height: 850 })
  await page.goto('/teacher/login')
  await page.getByPlaceholder('教师用户名').fill('browser-teacher')
  await page.getByPlaceholder('密码').fill('browser-test-password')
  await page.getByRole('button', { name: '进入教师端' }).click()
  await expect(page).toHaveURL(/\/teacher$/)
  const writes: string[] = []
  page.on('request', (request) => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) writes.push(request.url())
  })
  await expect(page.getByRole('tab', { name: '课堂处置', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(page.getByRole('heading', { name: '学生求助与教学介入' })).toBeVisible()
  await expect(page.getByText('学生主动求助')).toBeVisible()
  await expect(page.getByText('传感器读取失败', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('在线设备数')).toBeHidden()
  await expect(page.getByRole('heading', { name: '诊断解释审核' })).toBeHidden()
  await expect(page.getByText('管理实验会话与设备交接')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '认领', exact: true })).toBeHidden()
  await page.getByRole('button', { name: /phase9-browser-device.*查看详情/ }).click()
  await expect(page.getByRole('button', { name: '认领', exact: true })).toBeVisible()
  await expect(page.getByText('当前记录未提供学生明确执行过的步骤')).toBeVisible()
  await page.getByRole('textbox', { name: '搜索异常设备或错误代码' }).fill('SENSOR_READ_FAILED')
  await page.getByRole('button', { name: 'Phase 9 浏览器测试设备', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Phase 9 浏览器测试设备', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('tab', { name: '课堂概览', exact: true }).click()
  await expect(page.getByText('在线设备数')).toBeVisible()
  await expect(page.getByText('高频错误排行')).toBeVisible()
  await expect(page.getByText('错误趋势图')).toBeVisible()
  for (const name of ['设备状态图', '高频错误横向柱状图', '七日错误趋势图']) {
    const canvas = page.getByRole('img', { name, exact: true }).locator('canvas').first()
    await expect(canvas).toBeVisible()
    expect((await canvas.boundingBox())!.width).toBeGreaterThan(100)
  }

  await expect(page.getByRole('heading', { name: '学生求助与教学介入' })).toBeHidden()
  await page.getByRole('tab', { name: '资料与审核', exact: true }).click()
  await expect(page.getByText('知识案例与审核状态')).toBeVisible()
  await expect(page.getByText('修订率')).toBeHidden()
  await page.getByText('系统详情与诊断统计', { exact: true }).click()
  await expect(page.getByText('修订率')).toBeVisible()
  await expect(page.getByText('12.5ms')).toBeVisible()
  await expect(page.getByLabel('诊断工作流指标')).toContainText('运行中/其他1')
  await expect(page.getByLabel('诊断工作流指标')).toContainText('估算成本（元）0.0000')
  await expect(page.getByLabel('诊断工作流指标')).toContainText('有反馈诊断0')
  await expect(page.getByLabel('诊断工作流指标')).toContainText('按每个诊断最新反馈计算解决率—')
  await page.getByRole('button', { name: /phase9-browser-device.*查看诊断依据/ }).click()
  await expect(page.getByText('设备表现')).toBeVisible()
  await expect(page.getByRole('heading', { name: '可能原因' })).toBeVisible()
  await expect(page.getByText('传感器手册')).toBeVisible()
  await expect(page.getByText('manual-sensor / chunk-1')).toHaveCount(0)
  await expect(page.getByText('RRF 0.8300')).toHaveCount(0)
  await expect(page.getByText('缺少电压读数')).toBeVisible()
  await page.getByRole('tab', { name: '资料与审核', exact: true }).focus()
  await page.keyboard.press('Home')
  await expect(page.getByRole('tab', { name: '课堂处置', exact: true })).toBeFocused()
  await expect(page.getByRole('textbox', { name: '搜索异常设备或错误代码' })).toHaveValue(
    'SENSOR_READ_FAILED',
  )
  await expect(page.getByRole('button', { name: '认领', exact: true })).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Phase 9 浏览器测试设备', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('tab', { name: '课堂处置', exact: true }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('tab', { name: '课堂概览', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await page.keyboard.press('End')
  await expect(page.getByRole('tab', { name: '资料与审核', exact: true })).toBeFocused()
  await expect(page.getByText('传感器手册')).toBeVisible()
  expect(writes).toEqual([])
  // Capture the default information hierarchy after validating the expanded details.
  await page.getByRole('button', { name: /phase9-browser-device.*收起诊断依据/ }).click()
  await page.getByText('系统详情与诊断统计', { exact: true }).click()
  await page.getByRole('tab', { name: '课堂处置', exact: true }).click()
  await page.getByRole('button', { name: /phase9-browser-device.*收起详情/ }).click()
  await page.getByRole('textbox', { name: '搜索异常设备或错误代码' }).fill('')
  await auditLayout(page, 'teacher')
  expect(consoleErrors).toEqual([])
})

test('keeps authorized pending handoffs visible across tasks and reload without resubmission', async ({
  page,
}) => {
  await mockTeacherWorkspace(page, ['assignment.manage'])
  const session = {
    id: 'pending-session',
    device_id: 'handoff-device',
    display_name: '交接测试设备',
    student_name: '测试学生',
    class_name: '测试班级',
    assignment_title: '测试任务',
    started_at: '2026-07-25T08:00:00Z',
    status: 'ended',
    version_no: 1,
    is_test_data: true,
  }
  await page.route('**/api/v1/teacher/experiment-sessions', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/v1/teacher/experiment-sessions/pending-session', (route) =>
    route.fulfill({ json: session }),
  )
  await page.goto('/teacher/login')
  await page.getByPlaceholder('教师用户名').fill('browser-teacher')
  await page.getByPlaceholder('密码').fill('browser-test-password')
  await page.getByRole('button', { name: '进入教师端' }).click()
  await expect(page).toHaveURL(/\/teacher$/)
  await page.evaluate((record) => {
    sessionStorage.setItem(
      'xinjian-session-release:browser-test-teacher',
      JSON.stringify([
        {
          session: record,
          payload: {
            request_id: 'original-handoff-request',
            expected_version: 1,
            reason: '测试交接原请求',
          },
        },
      ]),
    )
  }, session)
  const writes: string[] = []
  page.on('request', (request) => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) writes.push(request.url())
  })
  await page.reload()
  const notice = page.getByRole('status', { name: '设备交接恢复提示' })
  await expect(notice).toContainText('有 1 项设备交接操作待确认')
  await expect(page.getByRole('button', { name: '继续确认原操作', exact: true })).toBeVisible()
  for (const tab of ['课堂概览', '资料与审核']) {
    await page.getByRole('tab', { name: tab, exact: true }).click()
    await expect(notice).toContainText('有 1 项设备交接操作待确认')
    await expect(page.getByRole('button', { name: '继续确认原操作', exact: true })).toBeHidden()
  }
  await notice.getByRole('button', { name: '查看待确认的设备交接' }).click()
  await expect(page.getByRole('tab', { name: '课堂处置', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(page.getByRole('button', { name: '继续确认原操作', exact: true })).toBeVisible()
  expect(writes).toEqual([])

  // Revoked access must not turn stored private records into a visible reminder or table.
  await page.route('**/api/v1/teacher/experiment-sessions/pending-session', (route) =>
    route.fulfill({ status: 403, json: {} }),
  )
  await page.reload()
  await expect(page.getByRole('button', { name: '刷新占用列表' })).toBeHidden()
  await expect(notice).toBeHidden()
  await page.getByText('管理实验会话与设备交接', { exact: true }).click()
  await expect(page.getByText('当前没有实验占用', { exact: true })).toBeVisible()
  await expect(page.getByText('测试学生', { exact: true })).toHaveCount(0)
  expect(writes).toEqual([])
})

test('a rejected teacher action removes stale protected data from the page', async ({ page }) => {
  await mockTeacherWorkspace(page)
  let writes = 0
  await page.route('**/api/v1/teacher-workflow/interventions/*/actions', (route) => {
    writes += 1
    return route.fulfill({ status: 403, json: { detail: 'permission changed' } })
  })
  await page.goto('/teacher/login')
  await page.getByPlaceholder('教师用户名').fill('browser-teacher')
  await page.getByPlaceholder('密码').fill('browser-test-password')
  await page.getByRole('button', { name: '进入教师端' }).click()
  await page.getByRole('button', { name: 'Phase 9 浏览器测试设备', exact: true }).click()
  await page.getByRole('button', { name: /phase9-browser-device.*查看详情/ }).click()
  await page.getByRole('button', { name: '认领', exact: true }).click()
  await expect(
    page
      .locator('#app')
      .getByText('数据加载失败：实验会话或访问权限已变化，请重新登录。', { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Phase 9 浏览器测试设备', exact: true }),
  ).toHaveCount(0)
  expect(writes).toBe(1)
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem('xinjian-intervention:browser-test-teacher:phase9-case'),
    ),
  ).toBeNull()
})
