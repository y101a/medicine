import { expect, test } from '@playwright/test'
import { installApiStubs, settle } from './support'

/**
 * 首次登录的采集弹窗。
 *
 * 报告里说这个弹窗「排版有问题」，但 jsdom 测不到排版。这里量真实坐标：
 * 弹窗必须完整落在视口内，三个按钮都必须可见可点，并且点「跳过」要真的生效。
 */

const DIALOG_TEXT = '关于健康记录'
const BUTTONS = ['跳过', '关闭采集', '保存']

test.describe('首次采集弹窗', () => {
  test('窄屏 375px：弹窗不溢出视口，三个按钮可见可点', async ({ page }) => {
    await installApiStubs(page, { noticeSeen: false })
    await page.setViewportSize({ width: 375, height: 720 })
    await page.goto('/app')
    await settle(page)

    const dialog = page.locator('.el-dialog', { hasText: DIALOG_TEXT })
    await expect(dialog, '首次进入应该弹出采集说明').toBeVisible()

    const box = await dialog.boundingBox()
    expect(box, `${DIALOG_TEXT} 弹窗应该有布局盒`).not.toBeNull()
    const left = Math.round(box!.x)
    const right = Math.round(box!.x + box!.width)
    const width = Math.round(box!.width)

    // 关键回归：这里曾经是固定 560px，在 375px 视口下右边界会到 560。
    expect(
      left,
      `弹窗左边界 ${left}px 为负，说明被视口裁掉`,
    ).toBeGreaterThanOrEqual(-1)
    expect(
      right,
      `弹窗右边界 ${right}px 超出 375px 视口（弹窗宽 ${width}px）`,
    ).toBeLessThanOrEqual(376)
    console.log(`[e2e] 采集弹窗坐标：left=${left} right=${right} width=${width}`)

    for (const label of BUTTONS) {
      const button = dialog.getByRole('button', { name: label })
      await expect(button, `「${label}」按钮应该可见`).toBeVisible()
      await expect(button, `「${label}」按钮应该可点`).toBeEnabled()
    }
  })

  test('点「跳过」会关闭弹窗并只提交 noticeSeen', async ({ page }) => {
    await installApiStubs(page, { noticeSeen: false })
    await page.setViewportSize({ width: 375, height: 720 })

    const settingsPatches: unknown[] = []
    page.on('request', (request) => {
      if (request.method() === 'PATCH' && request.url().includes('/health-records/settings')) {
        settingsPatches.push(request.postDataJSON())
      }
    })

    await page.goto('/app')
    await settle(page)

    const dialog = page.locator('.el-dialog', { hasText: DIALOG_TEXT })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: '跳过' }).click()

    await expect(dialog, '点「跳过」后弹窗应该关闭').toBeHidden()
    expect(
      settingsPatches,
      '「跳过」只应确认已读通知，不应改动采集开关',
    ).toEqual([{ noticeSeen: true }])
  })
})