import { expect, test } from '@playwright/test'

test('shows a healthy Phase 1 application shell', async ({ page }, testInfo) => {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  const failedResponses: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(`${message.text()} (${message.location().url})`)
    }
  })
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('response', (response) => {
    if (response.status() >= 400) failedResponses.push(`${response.status()} ${response.url()}`)
  })

  await page.goto('/')

  await expect(page.getByRole('heading', { name: '芯鉴知微' })).toBeVisible()
  await expect(page.getByText('Phase 1 · 基础运行链路')).toBeVisible()
  await expect(page.getByText('服务正常')).toBeVisible()
  await expect(page.getByText('芯鉴知微 API')).toBeVisible()
  await expect(page.locator('.vite-error-overlay')).toHaveCount(0)

  await page.screenshot({ path: testInfo.outputPath('phase1-home.png'), fullPage: true })

  expect(consoleErrors).toEqual([])
  expect(pageErrors).toEqual([])
  expect(failedResponses).toEqual([])
})
