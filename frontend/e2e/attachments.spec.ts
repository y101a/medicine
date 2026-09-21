import { expect, test, type Page } from '@playwright/test'
import { installApiStubs, settle, waitForRendered, type StubTable } from './support'

/**
 * 病历文档附件的界面验收。
 *
 * 与语音输入不同，这里**不需要假设备**：文件是真实字节，用 `setInputFiles` 直接喂进去，
 * 所以这条链路能真正走完「选文件 → 说明确认 → 上传解析 → 卡片 → 发送带 id」。
 * 边界：解析结果来自桩接口，真实 PDF/DOCX/PPTX 的版式与识别质量仍要人眼看。
 */

const ATTACHMENT = {
  id: 'att-1',
  displayName: '血常规报告.pdf',
  kind: 'pdf',
  byteSize: 20480,
  pageCount: 2,
  charCount: 860,
  preview: '白细胞计数 6.2',
  status: 'ready',
  createdAt: '2026-09-21T02:00:00Z',
}

const CONSULTATION = {
  id: 'c-e2e',
  title: '当前咨询',
  messageCount: 0,
  createdAt: '2026-09-21T02:00:00Z',
  updatedAt: '2026-09-21T02:00:00Z',
}

const STUBS: StubTable = {
  'POST /consultations': { status: 201, body: CONSULTATION },
  'POST /consultations/*/attachments': { status: 201, body: ATTACHMENT },
  'GET /consultations/*/attachments': { body: { items: [] } },
}

async function openComposer(page: Page) {
  await page.goto('/app/chat')
  await settle(page)
  await waitForRendered(page, '.composer')
  // 语音一次性提示是模态之外的横幅，会挡住下方点击。
  const tip = page.locator('.voice-tip')
  if (await tip.isVisible()) await tip.locator('.el-alert__close-btn').click()
}

function pickFile(page: Page) {
  // 输入区现在有两个文件入口（图片 / 文档），这里按 accept 精确定位文档那个。
  return page.locator('input[type="file"][accept*=".pdf"]').setInputFiles({
    name: '血常规报告.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n% e2e 用的最小结构，仅前端验收\n'),
  })
}

test.describe('病历文档附件', () => {
  test('回形针按钮位于麦克风左侧', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    await openComposer(page)

    const attach = page.locator('button[aria-label="添加病历文档"]')
    const mic = page.locator('button[aria-label="语音输入"]')
    await expect(attach).toBeVisible()
    const attachBox = await attach.boundingBox()
    const micBox = await mic.boundingBox()
    expect(attachBox, '回形针应可测量').not.toBeNull()
    expect(micBox, '麦克风应可测量').not.toBeNull()
    expect(
      attachBox!.x + attachBox!.width,
      `回形针右边界 ${Math.round(attachBox!.x + attachBox!.width)}px 应不晚于麦克风左边界 ${Math.round(micBox!.x)}px`,
    ).toBeLessThanOrEqual(micBox!.x)
  })

  test('首次上传先说明文档去向，取消则不上传', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    let uploads = 0
    await page.route('**/api/v1/consultations/*/attachments', async (route) => {
      if (route.request().method() === 'POST') uploads += 1
      await route.fallback()
    })
    await openComposer(page)

    await pickFile(page)
    const box = page.locator('.el-message-box')
    await expect(box, '首次上传必须说明文字会随问题外发').toBeVisible({ timeout: 15_000 })
    await expect(box).toContainText('随问题一起交给模型')
    await expect(box).toContainText('他人的病历')
    await box.getByRole('button', { name: '取消' }).click()
    await expect(box).toBeHidden()
    expect(uploads, '取消说明后不得上传').toBe(0)
    await expect(page.locator('.attachment-item'), '取消后不应出现文件卡片').toHaveCount(0)
  })

  test('上传成功后出现文件卡片，且不会自动发送', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    let sent = 0
    await page.route('**/api/v1/consultations/*/messages', async (route) => {
      if (route.request().method() === 'POST') sent += 1
      await route.fallback()
    })
    await openComposer(page)

    await pickFile(page)
    await page.locator('.el-message-box').getByRole('button', { name: '我知道了，继续上传' }).click()

    const card = page.locator('.attachment-item')
    await expect(card, '解析成功后应显示文件卡片').toContainText('血常规报告.pdf', { timeout: 15_000 })
    await expect(card).toContainText('860 字')
    await expect(page.locator('#symptom-input'), '输入框不应被文档文字灌入').toHaveValue('')
    expect(sent, '解析完成不得自动发送').toBe(0)
  })

  test('点发送时把附件 id 一起提交', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    const bodies: string[] = []
    await page.route('**/api/v1/consultations/*/messages', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.fallback()
        return
      }
      bodies.push(route.request().postData() || '')
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'm-e2e',
          role: 'user',
          content: '帮我解释这份报告',
          sequence: 1,
          medicalContent: true,
          answerFormat: 'plain',
          citations: [],
          attachments: [ATTACHMENT],
          createdAt: '2026-09-21T02:05:00Z',
        }),
      })
    })
    await openComposer(page)

    await pickFile(page)
    await page.locator('.el-message-box').getByRole('button', { name: '我知道了，继续上传' }).click()
    await expect(page.locator('.attachment-item')).toContainText('血常规报告.pdf', { timeout: 15_000 })

    await page.locator('#symptom-input').fill('帮我解释这份报告')
    await page.locator('button[aria-label="发送消息"]').click()
    await expect.poll(() => bodies.length, { timeout: 15_000 }).toBe(1)
    expect(bodies[0], '附件 id 必须随消息一起提交').toContain('"attachmentIds":["att-1"]')
  })
})