import { test, expect } from '@playwright/test'

test('offline student login and teacher actions persist without business requests', async ({
  page,
}) => {
  const requests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/')) requests.push(request.url())
  })
  await page.goto('/#/login')
  await page.getByRole('button', { name: '以演示学生身份进入' }).click()
  await expect(page).toHaveURL(/#\/student$/)
  await expect(page.getByRole('status').filter({ hasText: '离线演示' })).toBeVisible()
  await expect(page.getByRole('button', { name: '用最新数据重新检查' })).toBeDisabled()
  await page.goto('/#/teacher')
  await page.getByRole('button', { name: /review-sht31-01.*查看详情/ }).click()
  await page.getByRole('button', { name: '认领', exact: true }).click()
  await expect(page.getByRole('button', { name: '处理完成', exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: /review-sht31-01.*查看详情/ }).click()
  await expect(page.getByRole('button', { name: '处理完成', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: /资料与审核/ }).click()
  await page.getByRole('button', { name: '批准', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '批准', exact: true }).click()
  await expect(page.getByText('暂无等待审核的诊断。')).toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: /资料与审核/ }).click()
  await expect(page.getByText('暂无等待审核的诊断。')).toBeVisible()
  expect(requests).toEqual([])
})
