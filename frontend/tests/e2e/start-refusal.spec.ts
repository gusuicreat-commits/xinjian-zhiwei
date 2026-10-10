import { expect, test } from '@playwright/test'

test('a forbidden task can be replaced after permissions refresh', async ({ page }) => {
  const starts: Array<{ device_id: string; request_id: string }> = []
  const tasks = ['a', 'b'].map((id) => ({
    id: `task-${id}`,
    title: `合成任务 ${id.toUpperCase()}`,
    is_test_data: true,
    devices: [{ id: `device-${id}`, name: `合成设备 ${id.toUpperCase()}` }],
  }))
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/auth/session')
      return route.fulfill({
        json: {
          access_token: 'synthetic-only',
          user_id: 'audit-student',
          roles: ['student'],
          permissions: ['assignment.read'],
          expires_at: '2099-01-01T00:00:00Z',
        },
      })
    if (path === '/api/v1/student/assignments') {
      return route.fulfill({ json: starts.length ? tasks.slice(1) : tasks })
    }
    if (path === '/api/v1/student/experiment-sessions') {
      if (route.request().method() === 'GET') return route.fulfill({ json: [] })
      starts.push(route.request().postDataJSON())
      if (starts.length === 1)
        return route.fulfill({ status: 403, json: { detail: 'scope revoked' } })
      return route.fulfill({
        status: 201,
        json: {
          id: 'session-b',
          device_id: 'device-b',
          display_name: '合成设备 B',
          assignment_title: '合成任务 B',
          experiment_assignment_id: 'task-b',
          is_test_data: true,
          version_no: 1,
          status: 'active',
        },
      })
    }
    if (path === '/api/v1/student/session')
      return route.fulfill({
        json: {
          device_id: 'device-b',
          display_name: '合成设备 B',
          auth_mode: 'student_account',
          student_user_id: 'audit-student',
          experiment_session_id: 'session-b',
          experiment_assignment_id: 'task-b',
          notice: 'synthetic',
        },
      })
    // Dashboard is outside this regression; verify the login/session handoff below.
    return route.fulfill({ status: 503, json: { detail: 'synthetic unavailable dashboard' } })
  })
  await page.goto('/login')
  await page.getByRole('textbox', { name: '学生账号', exact: true }).fill('synthetic-student')
  await page.getByLabel('学生密码', { exact: true }).fill('synthetic-only')
  await page.getByRole('button', { name: '验证学生账号', exact: true }).click()
  await page.getByText('选择实验任务', { exact: true }).click()
  await page.getByRole('option', { name: '合成任务 A（测试）', exact: true }).click()
  await page.getByText('选择设备', { exact: true }).click()
  await page.getByRole('option', { name: '合成设备 A', exact: true }).click()
  await page.getByRole('button', { name: '开始所选实验', exact: true }).click()
  await expect(
    page.getByText('当前任务或设备权限已变化，请重新选择可用任务。', { exact: true }),
  ).toBeVisible()
  expect(
    await page.evaluate(() => sessionStorage.getItem('xinjian-start-session:audit-student')),
  ).toBeNull()
  await page.locator('.el-select').first().click()
  await expect(page.getByRole('option', { name: '合成任务 A（测试）', exact: true })).toHaveCount(0)
  await page.getByRole('option', { name: '合成任务 B（测试）', exact: true }).click()
  await page.getByText('选择设备', { exact: true }).click()
  await page.getByRole('option', { name: '合成设备 B', exact: true }).click()
  await page.getByRole('button', { name: '开始所选实验', exact: true }).click()
  await expect(page).toHaveURL(/\/student$/)
  expect(starts).toHaveLength(2)
  expect(starts[1]!.device_id).toBe('device-b')
  expect(starts[0]!.request_id).not.toBe(starts[1]!.request_id)
  expect(
    await page.evaluate(() => sessionStorage.getItem('xinjian-start-session:audit-student')),
  ).toBeNull()
  expect(
    await page.evaluate(
      () =>
        JSON.parse(sessionStorage.getItem('xinjian-student-device-session')!).experimentSessionId,
    ),
  ).toBe('session-b')
})
