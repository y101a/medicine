import { expect, test, type Page } from '@playwright/test'
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

test.describe('应用内语音输入', () => {
  const VOICE_STUB = {
    'POST /voice/transcribe': { body: { text: '最近三天咳嗽，晚上更明显', durationMs: 3200 } },
  }

  /** 关掉一次性提示，避免它挡住后面的点击。 */
  async function dismissTip(page: Page) {
    const tip = page.locator('.voice-tip')
    if (await tip.isVisible()) await tip.locator('.el-alert__close-btn').click()
  }

  test('麦克风按钮位于发送键左侧', async ({ page }) => {
    await installApiStubs(page)
    await page.goto('/app/chat')
    await settle(page)
    await waitForRendered(page, '.composer')
    await dismissTip(page)

    const mic = page.locator('button[aria-label="语音输入"]')
    const send = page.locator('button[aria-label="发送消息"]')
    await expect(mic).toBeVisible()
    const micBox = await mic.boundingBox()
    const sendBox = await send.boundingBox()
    expect(micBox, '麦克风按钮应可测量').not.toBeNull()
    expect(sendBox, '发送键应可测量').not.toBeNull()
    expect(
      micBox!.x + micBox!.width,
      `麦克风右边界 ${Math.round(micBox!.x + micBox!.width)}px 应不晚于发送键左边界 ${Math.round(sendBox!.x)}px`,
    ).toBeLessThanOrEqual(sendBox!.x)
  })

  test('首次录音必须先同意音频外发，取消后不进入录音', async ({ page }) => {
    await installApiStubs(page, { extra: VOICE_STUB })
    await page.goto('/app/chat')
    await settle(page)
    await waitForRendered(page, '.composer')
    await dismissTip(page)

    await page.locator('button[aria-label="语音输入"]').click()
    const box = page.locator('.el-message-box')
    await expect(box, '首次录音必须明确告知音频会外发给语音识别服务').toBeVisible({ timeout: 15_000 })
    await expect(box).toContainText('语音识别服务')
    await expect(box).toContainText('身份证号')
    await box.getByRole('button', { name: '取消' }).click()
    await expect(box).toBeHidden()
    await expect(page.locator('.voice-status'), '取消授权后不应开始录音').toHaveCount(0)
  })

  test('录音—停止—转写—核对：文字进输入框且不自动发送', async ({ page }) => {
    let created = 0
    await installApiStubs(page, { extra: VOICE_STUB })
    // 统计有没有偷偷新建咨询：转写必须停在「用户核对」这一步。
    await page.route('**/api/v1/consultations', async (route) => {
      if (route.request().method() === 'POST') created += 1
      await route.fallback()
    })
    await page.goto('/app/chat')
    await settle(page)
    await waitForRendered(page, '.composer')
    await dismissTip(page)

    await page.locator('button[aria-label="语音输入"]').click()
    await page.locator('.el-message-box').getByRole('button', { name: '开始录音' }).click()
    await expect(page.locator('.voice-status'), '同意后应进入录音中状态').toContainText('录音中')

    // 假麦克风会持续产生测试音，等它攒出一点音频再停。
    await settle(page, 900)
    await page.locator('button[aria-label="停止录音并转写"]').click()

    await expect(page.locator('#symptom-input'), '转写文字应追加到输入框')
      .toHaveValue('最近三天咳嗽，晚上更明显', { timeout: 15_000 })
    expect(created, '转写完成后不得自动发送或新建咨询').toBe(0)
    await expect(page.locator('button[aria-label="语音输入"]'), '应回到待录音状态')
      .toBeVisible()
  })
})