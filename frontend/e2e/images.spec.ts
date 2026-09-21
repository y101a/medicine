import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { installApiStubs, settle, waitForRendered, type StubTable } from './support'

/**
 * 图片上传与识别的界面验收。
 *
 * 图片用 `setInputFiles` 喂**真实可解码的字节**（仓库里现成的 PNG），所以本地压缩/摆正那一步
 * 会真的跑起来；识别结果来自桩接口。可见类别、同意门槛、限额、仅图片发送、历史墓碑都在这里验。
 *
 * 边界：本地压缩质量、真实视觉模型输出、鉴权取字节的真实响应都要人眼看
 * （见 `BROWSER_ACCEPTANCE.md`）。
 */

const IMAGE = {
  id: 'img-1',
  displayName: '血常规.jpg',
  kind: 'image',
  imageCategory: 'report',
  mimeType: 'image/webp',
  byteSize: 234567,
  width: 1600,
  height: 1200,
  charCount: 860,
  preview: '白细胞计数 6.2',
  status: 'ready',
  imageAvailable: true,
  imageExpiresAt: '2026-12-20T10:00:00Z',
  createdAt: '2026-09-21T02:00:00Z',
}

const CONSULTATION = {
  id: 'c-e2e',
  title: '当前咨询',
  messageCount: 1,
  createdAt: '2026-09-21T02:00:00Z',
  updatedAt: '2026-09-21T02:00:00Z',
}

const STUBS: StubTable = {
  'POST /consultations': { status: 201, body: CONSULTATION },
  'POST /consultations/*/images': { status: 201, body: IMAGE },
  'GET /consultations/*/attachments': { body: { items: [] } },
}

/** 仓库里现成的真实 PNG：必须能被浏览器解码，不然本地预处理会直接判 `decode_failed`。 */
const PNG_BYTES = readFileSync(new URL('../src/assets/medical-ai-avatar.png', import.meta.url))

async function openComposer(page: Page) {
  await page.goto('/app/chat')
  await settle(page)
  await waitForRendered(page, '.composer')
  const tip = page.locator('.voice-tip')
  if (await tip.isVisible()) await tip.locator('.el-alert__close-btn').click()
}

function pickImage(page: Page, name = '血常规.jpg') {
  return page.locator('input[type="file"][accept*="image/jpeg"]').setInputFiles({
    name,
    mimeType: 'image/png',
    buffer: PNG_BYTES,
  })
}

function dialog(page: Page) {
  return page.locator('.image-upload')
}

/** 走完「选类别 →（必要时）同意 → 上传并识别」。 */
async function confirmUpload(page: Page, category = '报告 / 检查单', agree = true) {
  await expect(dialog(page), '选图后必须弹出类别与说明弹窗').toBeVisible({ timeout: 15_000 })
  await dialog(page).locator('.el-radio-button', { hasText: category }).click()
  if (agree) await dialog(page).locator('.el-checkbox').click()
  await dialog(page).getByRole('button', { name: '上传并识别' }).click()
}

test.describe('图片上传与识别', () => {
  test('图片按钮位于回形针左侧', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    await openComposer(page)

    const picture = page.locator('button[aria-label="添加图片"]')
    const attach = page.locator('button[aria-label="添加病历文档"]')
    await expect(picture).toBeVisible()
    const pictureBox = await picture.boundingBox()
    const attachBox = await attach.boundingBox()
    expect(pictureBox, '图片按钮应可测量').not.toBeNull()
    expect(attachBox, '回形针应可测量').not.toBeNull()
    expect(
      pictureBox!.x + pictureBox!.width,
      `图片按钮右边界 ${Math.round(pictureBox!.x + pictureBox!.width)}px 应不晚于回形针左边界 ${Math.round(attachBox!.x)}px`,
    ).toBeLessThanOrEqual(attachBox!.x)
  })

  test('必须先选类别并同意说明；取消则不上传也不建会话', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    let uploads = 0
    let consultations = 0
    await page.route('**/api/v1/consultations/*/images', async (route) => {
      uploads += 1
      await route.fallback()
    })
    await page.route('**/api/v1/consultations', async (route) => {
      if (route.request().method() === 'POST') consultations += 1
      await route.fallback()
    })
    await openComposer(page)

    await pickImage(page)
    await expect(dialog(page)).toBeVisible({ timeout: 15_000 })
    await expect(dialog(page), '首次上传必须讲清照片会发给谁').toContainText('阿里云视觉模型')
    await expect(dialog(page), '必须提示画面上的身份信息无法自动去除').toContainText('建议先遮挡')

    const confirm = dialog(page).getByRole('button', { name: '上传并识别' })
    await expect(confirm, '未选类别时不可上传').toBeDisabled()
    await dialog(page).locator('.el-radio-button', { hasText: 'X 光 / CT / MRI 片子' }).click()
    await expect(dialog(page), '片子类必须写明不判读病灶').toContainText('不判断病灶')
    await expect(confirm, '未同意说明时不可上传').toBeDisabled()

    await dialog(page).locator('.el-checkbox').click()
    await expect(confirm).toBeEnabled()
    await dialog(page).getByRole('button', { name: '取消' }).click()
    await expect(dialog(page)).toBeHidden()
    expect(uploads, '取消后不得上传图片').toBe(0)
    expect(consultations, '取消后不得建会话').toBe(0)
    await expect(page.locator('.attachment-item'), '取消后不应出现卡片').toHaveCount(0)
  })

  test('上传成功后出现带缩略图的卡片，且不会自动发送', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    let sent = 0
    await page.route('**/api/v1/consultations/*/messages', async (route) => {
      if (route.request().method() === 'POST') sent += 1
      await route.fallback()
    })
    await openComposer(page)

    await pickImage(page)
    await confirmUpload(page)

    const card = page.locator('.attachment-item')
    await expect(card, '识别成功后应显示图片卡片').toContainText('血常规', { timeout: 20_000 })
    await expect(card.locator('img.attachment-thumb'), '本地缩略图应来自压缩后的图片').toBeVisible()
    await expect(page.locator('#symptom-input'), '识别结果不应灌进输入框').toHaveValue('')
    expect(sent, '上传识别完成不得自动发送').toBe(0)
  })

  test('仅图片也能发送，并带上图片版的默认提问', async ({ page }) => {
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
          content: '图片提问',
          sequence: 1,
          answerFormat: 'plain',
          citations: [],
          attachments: [IMAGE],
          createdAt: '2026-09-21T02:05:00Z',
        }),
      })
    })
    await openComposer(page)

    await pickImage(page)
    await confirmUpload(page)
    await expect(page.locator('.attachment-item')).toContainText('血常规', { timeout: 20_000 })

    await page.locator('button[aria-label="发送消息"]').click()
    await expect.poll(() => bodies.length, { timeout: 15_000 }).toBe(1)
    expect(bodies[0], '图片 id 必须随消息提交').toContain('"attachmentIds":["img-1"]')
    expect(bodies[0], '没有文字时用图片版默认提问，不能写成解读病历文档').toContain('不要判读影像')
    expect(bodies[0]).not.toContain('解读上传的病历文档')
  })

  test('历史消息里的图片走鉴权接口取字节，到期则显示固定墓碑', async ({ page }) => {
    await installApiStubs(page, {
      extra: {
        ...STUBS,
        'GET /consultations/*': { body: { ...CONSULTATION } },
        'GET /consultations/*/messages': {
          body: {
            items: [
              {
                id: 'm1',
                role: 'user',
                content: '帮我看下这两张',
                sequence: 1,
                attachments: [
                  { id: 'img-1', displayName: '血常规.jpg', kind: 'image', status: 'ready', imageAvailable: true },
                  { id: 'img-2', displayName: '旧片子.jpg', kind: 'image', status: 'ready', imageAvailable: false },
                ],
                createdAt: '2026-09-21T02:00:00Z',
              },
            ],
            hasMore: false,
          },
        },
      },
    })
    let contentRequests = 0
    await page.route('**/api/v1/attachments/*/content', async (route) => {
      contentRequests += 1
      await route.fulfill({ status: 200, contentType: 'image/webp', body: PNG_BYTES })
    })

    await page.goto('/app/consultations/c-e2e')
    await settle(page)
    await waitForRendered(page, '.messages')

    await expect(page.locator('img.attachment-thumb').first(), '在保留期内的图片要显示缩略图')
      .toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.user-attachments')).toContainText('图片原件已按保留策略清理')
    await expect(page.locator('.user-attachments')).toContainText('旧片子.jpg')
    expect(contentRequests, '到期的图片不该再请求字节').toBe(1)
  })
})