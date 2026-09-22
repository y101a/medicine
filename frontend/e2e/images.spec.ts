import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { installApiStubs, settle, waitForRendered, type StubTable } from './support'

/**
 * 图片上传与识别的界面验收（契约 `backend/docs/MEDICAL_IMAGES.md` 第 10 节）。
 *
 * 2026-09-22 起输入区只有一个附件按钮，**单击就直接打开本机文件选择器**（不再有「上传文档 / 上传图片」菜单）；
 * 图片也不再由用户选类别，
 * 类别由服务端固定视觉模型自动判断。这里走的是**真实用户路径**：**单击附件按钮 → 系统文件选择器 → 本地压缩
 * → 上传**（按类型自动分流，没有中间菜单），所以这条链路本身也在验收范围内。
 *
 * 图片用 `setInputFiles` 喂**真实可解码的字节**（仓库里现成的 PNG），本地压缩/摆正那一步会真的跑；
 * 识别结果与类别来自桩接口。
 *
 * 边界：本地压缩质量、真实视觉模型的分类准确率、鉴权取字节的真实响应都要人眼看
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

const DOCUMENT = {
  id: 'doc-1',
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
  messageCount: 1,
  createdAt: '2026-09-21T02:00:00Z',
  updatedAt: '2026-09-21T02:00:00Z',
}

const STUBS: StubTable = {
  'POST /consultations': { status: 201, body: CONSULTATION },
  'POST /consultations/*/images': { status: 201, body: IMAGE },
  // 同一个附件按钮也能传文档，所以这条链路也要有桩（图片满额时用它验收「不误伤文档入口」）。
  'POST /consultations/*/attachments': { status: 201, body: DOCUMENT },
  'GET /consultations/*/attachments': { body: { items: [] } },
}

/** 仓库里现成的真实 PNG：必须能被浏览器解码，不然本地预处理会直接判 `decode_failed`。 */
const PNG_BYTES = readFileSync(new URL('../src/assets/medical-ai-avatar.png', import.meta.url))
// 文档路径只需要扩展名/MIME 走对分支，字节不必是真 PDF（服务端全部由桩接管）。
const PDF_BYTES = Buffer.from('%PDF-1.4\n% e2e 用的最小结构，仅前端验收\n')

async function openComposer(page: Page) {
  await page.goto('/app/chat')
  await settle(page)
  await waitForRendered(page, '.composer')
  const tip = page.locator('.voice-tip')
  if (await tip.isVisible()) await tip.locator('.el-alert__close-btn').click()
}

function attachButton(page: Page) {
  return page.locator('button[aria-label="添加附件"]')
}

/** 单击附件按钮就直接弹系统文件选择器——不再有「上传文档 / 上传图片」菜单。 */
async function pickFiles(page: Page, files: { name: string; mimeType: string; buffer: Buffer }[]) {
  const chooser = page.waitForEvent('filechooser')
  await attachButton(page).click()
  await (await chooser).setFiles(files)
}

function pickImage(page: Page, name = '血常规.jpg') {
  return pickFiles(page, [{ name, mimeType: 'image/png', buffer: PNG_BYTES }])
}

/** 图片满额后仍要能继续传文档：同一个按钮，先过首次的文档说明。 */
async function pickPdf(page: Page, name = '血常规报告.pdf') {
  await pickFiles(page, [{ name, mimeType: 'application/pdf', buffer: PDF_BYTES }])
  const box = page.locator('.el-message-box')
  await expect(box, '首次传文档必须先过一次性说明').toBeVisible({ timeout: 15_000 })
  await box.getByRole('button', { name: '我知道了，继续上传' }).click()
}

function dialog(page: Page) {
  return page.locator('.image-upload')
}

/** 首次选图后的隐私确认：勾选 → 上传。没有类别选择这一步。 */
async function confirmDialog(page: Page, agree = true) {
  await expect(dialog(page), '首次选图必须弹出隐私确认').toBeVisible({ timeout: 15_000 })
  if (agree) await dialog(page).locator('.el-checkbox').click()
  await dialog(page).getByRole('button', { name: '同意并上传' }).click()
}

test.describe('图片上传与识别', () => {
  test('附件按钮在麦克风左侧，单击直接打开本机文件选择器（没有菜单）', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    await openComposer(page)

    const attach = attachButton(page)
    const mic = page.locator('button[aria-label="语音输入"]')
    await expect(attach).toBeVisible()
    await expect(page.locator('button[aria-label="添加图片"]'), '不应再有独立图片按钮').toHaveCount(0)

    const attachBox = await attach.boundingBox()
    const micBox = await mic.boundingBox()
    expect(attachBox, '附件按钮应可测量').not.toBeNull()
    expect(micBox, '麦克风应可测量').not.toBeNull()
    expect(
      attachBox!.x + attachBox!.width,
      `附件按钮右边界 ${Math.round(attachBox!.x + attachBox!.width)}px 应不晚于麦克风左边界 ${Math.round(micBox!.x)}px`,
    ).toBeLessThanOrEqual(micBox!.x)

    // 单击即进系统文件选择器；中途不该冒出「上传文档 / 上传图片」菜单
    const chooser = page.waitForEvent('filechooser')
    await attach.click()
    await expect(page.getByText('上传文档', { exact: true }), '不该再有上传菜单').toHaveCount(0)
    await expect(page.getByText('上传图片', { exact: true }), '不该再有上传菜单').toHaveCount(0)
    await (await chooser).setFiles([])
  })

  test('首次上传先确认隐私说明（无类别选项），取消则不上传也不建会话', async ({ page }) => {
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
    await expect(dialog(page).locator('.el-radio-group'), '不应再让用户选类别').toHaveCount(0)

    const confirm = dialog(page).getByRole('button', { name: '同意并上传' })
    await expect(confirm, '未同意说明时不可上传').toBeDisabled()
    await dialog(page).locator('.el-checkbox').click()
    await expect(confirm).toBeEnabled()
    await dialog(page).getByRole('button', { name: '取消' }).click()
    await expect(dialog(page)).toBeHidden()
    expect(uploads, '取消后不得上传图片').toBe(0)
    expect(consultations, '取消后不得建会话').toBe(0)
    await expect(page.locator('.attachment-item'), '取消后不应出现卡片').toHaveCount(0)
  })

  test('上传请求里不再有 imageCategory，但仍带同意标记与说明版本', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    const bodies: string[] = []
    await page.route('**/api/v1/consultations/*/images', async (route) => {
      bodies.push(route.request().postData() || '')
      await route.fallback()
    })
    await openComposer(page)

    await pickImage(page)
    await confirmDialog(page)
    await expect(page.locator('.attachment-item')).toContainText('血常规', { timeout: 20_000 })

    expect(bodies, '应恰好上传一次').toHaveLength(1)
    expect(bodies[0], '契约第 10.2 节：multipart 里不再有 imageCategory').not.toContain('imageCategory')
    expect(bodies[0], '同意标记与说明版本仍要带').toContain('noticeVersion')
  })

  test('上传成功后显示缩略图与自动分类的类别，且不会自动发送', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    let sent = 0
    await page.route('**/api/v1/consultations/*/messages', async (route) => {
      if (route.request().method() === 'POST') sent += 1
      await route.fallback()
    })
    await openComposer(page)

    await pickImage(page)
    await confirmDialog(page)

    const card = page.locator('.attachment-item')
    await expect(card, '识别成功后应显示图片卡片').toContainText('血常规', { timeout: 20_000 })
    await expect(card.locator('img.attachment-thumb'), '本地缩略图应来自压缩后的图片').toBeVisible()
    await expect(card, '类别来自服务端自动分类，要如实展示').toContainText('报告 / 检查单')
    await expect(page.locator('.image-boundaries'), '要说明这类图片的能力边界').toContainText('以纸质报告为准')
    await expect(page.locator('#symptom-input'), '识别结果不应灌进输入框').toHaveValue('')
    expect(sent, '上传识别完成不得自动发送').toBe(0)
  })

  test('图片满 3 张后仍能继续传文档；第 4 张图片被拦下并说明', async ({ page }) => {
    await installApiStubs(page, { extra: STUBS })
    await openComposer(page)

    // 第一张走隐私确认，之后本机已同意，直接上传（顺带验收「之后不再弹窗」）。
    await pickImage(page, 'a.jpg')
    await confirmDialog(page)
    await expect(page.locator('.attachment-item')).toHaveCount(1, { timeout: 20_000 })
    for (const name of ['b.jpg', 'c.jpg']) {
      await pickImage(page, name)
      await expect(page.locator('.attachment-item')).toHaveCount(
        name === 'b.jpg' ? 2 : 3,
        { timeout: 20_000 },
      )
    }
    await expect(dialog(page), '已同意过的用户不该再弹窗').toBeHidden()

    // 第 4 张图片：菜单没了，不能再靠禁用入口，改为「拦下 + 说清楚」
    await pickImage(page, 'd.jpg')
    await expect(page.locator('.attachment-item'), '超出的图片不该进待发送列表').toHaveCount(3)
    await expect(page.locator('.attachment-notice')).toContainText('一次最多带上 3 张图片')

    // 图片满额不误伤文档入口：同一个按钮照样能传 PDF
    await pickPdf(page)
    await expect(page.locator('.attachment-item')).toHaveCount(4, { timeout: 20_000 })
  })

  test('被判为无关或看不清的图片不出现卡片，只给一句短提示', async ({ page }) => {
    await installApiStubs(page, {
      extra: {
        ...STUBS,
        'POST /consultations/*/images': {
          status: 422,
          body: { code: 'IMAGE_UNRELATED', message: '未识别为医疗健康相关图片，请换一张' },
        },
      },
    })
    await openComposer(page)

    await pickImage(page, '风景.jpg')
    await confirmDialog(page)

    const notice = page.locator('.attachment-notice')
    await expect(notice, '应给出可关闭的短提示').toContainText('未识别为医疗健康相关', { timeout: 20_000 })
    await expect(page.locator('.attachment-item'), '被拒的图片不得进入待发送卡片').toHaveCount(0)
    await expect(page.locator('.image-boundaries'), '没有成功图片就没有边界说明').toHaveCount(0)
    // 提示可以自己关掉
    await notice.locator('.el-alert__close-btn').click()
    await expect(notice).toBeHidden()
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
    await confirmDialog(page)
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

  /**
   * 用户 2026-09-22 报告：发完图片后输入框里还留着它，每次都要手动点「移除」。
   * 复现条件是「带着历史附件进入会话」——服务端会把该会话的**全部**附件读回草稿区，
   * 已随消息发出的那些必须被剔除；但历史消息里仍要照常显示。
   */
  test('已随消息发出的图片不会回到输入框，历史消息里照常显示', async ({ page }) => {
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
                content: '帮我看下这张',
                sequence: 1,
                attachments: [
                  { id: 'img-1', displayName: '血常规.jpg', kind: 'image', status: 'ready', imageAvailable: true },
                ],
                createdAt: '2026-09-21T02:00:00Z',
              },
            ],
            hasMore: false,
          },
        },
        'GET /consultations/*/attachments': { body: { items: [IMAGE] } },
        // 让下一次提问真的发送成功，这样「请求体里没有 img-1」才是对真实发送路径的断言。
        'POST /consultations/c-e2e/messages': {
          status: 201,
          body: {
            id: 'm2',
            role: 'user',
            content: '这张单子里的白细胞怎么看',
            sequence: 2,
            attachmentIds: [],
            createdAt: '2026-09-21T03:00:00Z',
          },
        },
      },
    })
    let sendBody = ''
    await page.route('**/api/v1/consultations/*/messages', async (route) => {
      if (route.request().method() === 'POST') sendBody = route.request().postData() ?? ''
      await route.fallback()
    })

    await page.goto('/app/consultations/c-e2e')
    await settle(page)
    await waitForRendered(page, '.messages')

    // 历史消息里照常显示这张图，否则下面的断言可能只是「什么都没渲染」的假通过。
    await expect(page.locator('.user-attachments')).toContainText('血常规.jpg')
    // 输入框（草稿区）里不能再有它，也不该再出现「移除」按钮。
    await expect(page.locator('.composer .attachment-item')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '移除 血常规.jpg' })).toHaveCount(0)

    // 也不该被下一次提问重复带上。
    await page.locator('#symptom-input').fill('这张单子里的白细胞怎么看')
    await page.locator('button[aria-label="发送消息"]').click()
    await expect.poll(() => sendBody, { message: '应当真的发出了一次提问' }).toContain('这张单子里的白细胞怎么看')
    expect(sendBody, '已经发出去的图片不该被重复带上').not.toContain('img-1')
  })
})