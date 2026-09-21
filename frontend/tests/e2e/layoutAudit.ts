import { expect, type Page } from '@playwright/test'

export async function auditLayout(page: Page, name: string) {
  if (process.env.UI_LAYOUT_AUDIT !== '1') return
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const tabs =
    name === 'student'
      ? ['当前实验', '数据记录', '实验参考']
      : name === 'teacher'
        ? ['课堂处置', '课堂概览', '资料与审核']
        : []
  const directory = process.env.UI_LAYOUT_OUTPUT_DIR ?? '../output/audits/ui-borders'
  for (const width of [1195, 768, 390]) {
    await page.setViewportSize({ width, height: 850 })
    for (const [index, label] of (tabs.length ? tabs : ['']).entries()) {
      if (label) await page.getByRole('tab', { name: label, exact: true }).click()
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width)
      // Canvas transitions are not disabled by CSS reduced-motion or screenshot animations.
      if (await page.locator('canvas:visible, .sensor-chart:visible').count())
        await page.waitForTimeout(1200)
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }))
      if (name === 'teacher' && width <= 820) {
        // Keep an unmodified viewport image to verify the real fixed navigation.
        await page.screenshot({
          path: `${directory}/${name}-${index + 1}-${width}-viewport.png`,
          animations: 'disabled',
        })
      }
      await page.screenshot({
        path: `${directory}/${name}${label ? `-${index + 1}` : ''}-${width}.png`,
        fullPage: true,
        animations: 'disabled',
        // Only for the exported full-page image: place fixed mobile navigation at the end,
        // so it does not cover the middle of the long image. Product CSS stays unchanged.
        ...(name === 'teacher' && width <= 820
          ? {
              style:
                '.teacher-app { position: relative !important; } .teacher-sidebar { position: absolute !important; top: auto !important; bottom: 0 !important; }',
            }
          : {}),
      })
    }
  }
}
