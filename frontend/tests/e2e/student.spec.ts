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
  return {
    generated_at: '2026-07-20T09:00:00Z',
    task: { configured: false, title: null, template_id: null, notice: '尚未配置真实实验任务。' },
    device,
    logs: [],
    readings: [],
    diagnosis: null,
    guidance: [],
    feedback: null,
    ...overrides,
  }
}

async function mockStudentApi(page: Page, payload: ReturnType<typeof dashboard>): Promise<void> {
  await page.route('**/api/v1/student/**', async (route) => {
    const url = route.request().url()
    if (url.endsWith('/session')) {
      await route.fulfill({
        json: {
          device_id: device.device_id,
          display_name: device.display_name,
          auth_mode: 'device_credential_placeholder',
          notice: '测试会话',
        },
      })
      return
    }
    if (url.endsWith('/dashboard')) {
      await route.fulfill({ json: payload })
      return
    }
    await route.fulfill({
      status: 201,
      json: {
        id: 'feedback-test',
        action: 'request_teacher_help',
        note: null,
        is_test_data: true,
        created_at: '2026-07-20T09:01:00Z',
      },
    })
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
  await expect(page.getByText('尚无诊断记录')).toBeVisible()
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
  await expect(page.getByText(/不代表已完成真实硬件健康认证/)).toBeVisible()
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
  await expect(page.getByText('读取失败示例命中')).toBeVisible()
  await expect(page.getByText('连接异常')).toBeVisible()
  await page.getByRole('button', { name: '请求教师协助' }).click()
  await expect(page.getByText('已记录：请求教师协助')).toBeVisible()
  expect(errors).toEqual([])
})
