import { expect, test } from '@playwright/test'
import { auditLayout } from './layoutAudit'

for (const route of ['/login', '/teacher/login', '/readiness']) {
  test(`public page remains usable: ${route}`, async ({ page }) => {
    await page.route('**/api/v1/readiness/status', (request) =>
      request.fulfill({
        json: {
          overall: 'test_only',
          version: 'UI audit fixture',
          software_ready: true,
          demo_ready: true,
          hardware_ready: false,
          knowledge_ready: false,
          organization_ready: false,
          production_ready: false,
          items: ['硬件', '课程资料', '教师确认', '运行环境'].map((label, index) => ({
            key: `fixture-${index}`,
            label,
            status: 'blocked',
            evidence: '明确标记的模拟数据；本页不代表实际验收。',
            required_input: '待人工提供真实验证记录。',
          })),
        },
      }),
    )
    await page.goto(route)
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
    if (route === '/readiness')
      await expect(page.getByText('版本 UI audit fixture', { exact: false })).toBeVisible()
    await auditLayout(page, route.slice(1).replace('/', '-'))
  })
}
