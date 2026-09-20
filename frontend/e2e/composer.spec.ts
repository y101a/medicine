import { expect, test } from '@playwright/test'
import { installApiStubs, settle, waitForRendered } from './support'

/**
 * 语音输入引导（路线 A：不碰音频）。
 *
 * 用户用自己设备上的输入法（如豆包输入法）语音输入，音频不经过本项目，
 * 所以这里验收的不是语音识别，而是「有没有把这条路告诉用户」和输入护栏：
 * 一次性安全提示、关闭后不再打扰、接近字数上限时提醒分次发送。
 */

test.describe('输入区语音引导', () => {
  test('聊天页说明可用输入法语音输入，并给出一次性安全提示', async ({ page }) => {
    await installApiStubs(page)
    await page.goto('/app/chat')
    await settle(page)
    await waitForRendered(page, '.composer')

    await expect(page.locator('.composer-meta'), '输入区应说明可用输入法语音输入')
      .toContainText('可用输入法语音输入（如豆包输入法）')

    const tip = page.locator('.voice-tip')
    await expect(tip, '首次进入应提示语音输入的注意事项').toBeVisible({ timeout: 15_000 })
    await expect(tip, '提示应写明不要提供身份信息')
      .toContainText('请不要在对话中提供姓名、身份证号、住院号或手机号')
  })

  test('关闭一次性提示后刷新不再出现', async ({ page }) => {
    await installApiStubs(page)
    await page.goto('/app/chat')
    await settle(page)

    const tip = page.locator('.voice-tip')
    await expect(tip).toBeVisible({ timeout: 15_000 })
    await tip.locator('.el-alert__close-btn').click()
    await expect(tip, '关闭后本次会话内应消失').toBeHidden()

    await page.reload()
    await settle(page)
    await waitForRendered(page, '.composer')
    await expect(page.locator('.voice-tip'), '已看过提示的浏览器不应再次提示').toHaveCount(0)
  })

  test('接近字数上限时提醒可分多次发送', async ({ page }) => {
    await installApiStubs(page)
    await page.goto('/app/chat')
    await settle(page)
    await waitForRendered(page, '.composer')

    const tip = page.locator('.voice-tip')
    if (await tip.isVisible()) await tip.locator('.el-alert__close-btn').click()

    const hint = page.locator('.limit-hint')
    await expect(hint, '未接近上限时不应提示').toHaveCount(0)

    await page.locator('#symptom-input').fill('症'.repeat(1800))
    await expect(hint, '语音输入容易逼近上限，应提醒分次发送')
      .toContainText('已接近 2000 字上限，可分多次发送')
  })
})