import { expect, test } from '@playwright/test'

test('keeps Phase 7 teacher metrics, charts and intervention content with AI disabled', async ({
  page,
}) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => consoleErrors.push(error.message))

  await page.route('**/api/v1/teacher/**', async (route) => {
    if (route.request().url().endsWith('/session')) {
      await route.fulfill({
        json: {
          auth_mode: 'review_token_placeholder',
          notice: 'Phase 9 browser acceptance',
        },
      })
      return
    }
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
        error_ranking: [
          { error_code: 'SENSOR_READ_FAILED', count: 5, test_data_only: true },
        ],
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
          source_count: 1,
          document_count: 4,
          pending_review_count: 0,
          approved_chunk_count: 4,
          embedding_count: 4,
          embedding_provider_configured: false,
          notice: '仅为 Phase 9 合成测试知识。',
        },
      },
    })
  })

  await page.goto('/teacher/login')
  await page.getByPlaceholder('审阅访问令牌').fill('browser-test-token-not-a-secret')
  await page.getByRole('button', { name: '进入教师端' }).click()
  await expect(page).toHaveURL(/\/teacher$/)
  await expect(page.getByText('在线设备数')).toBeVisible()
  await expect(page.getByText('高频错误排行')).toBeVisible()
  await expect(page.getByText('错误趋势图')).toBeVisible()
  await expect(page.getByText('需要教师介入的设备')).toBeVisible()
  await expect(page.getByText('SENSOR_READ_FAILED').first()).toBeVisible()
  await expect(page.getByText('知识案例审核入口')).toBeVisible()
  expect(consoleErrors).toEqual([])
})
