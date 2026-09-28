import { expect, test, type Page, type Request } from '@playwright/test'
import { installApiStubs, settle, waitForRendered, type StubTable } from './support'

/**
 * 自然语言触发的 PPT/Word 科普文档生成的界面验收
 * （`PPT_WORD_PLAN.md` §8.2 交互硬要求、§9.2 前端自动化清单）。
 *
 * 这里走**真实用户路径**（输入 → 提交 → 说明弹窗 → 确认 → 任务卡 → 下载/删除），
 * 接口全部由 `page.route` 拦截，验证的是「前端拿到某种响应后渲染成什么样」。
 *
 * **边界**：桩里的「文件字节」只是 JSON 文本（`support.ts` 统一 `JSON.stringify`），
 * 所以只断言「下载被触发、文件名固定为契约格式」，**.docx/.pptx 的真实字节与 Office/WPS 版式
 * 无法在这里验证**——那要等后端落地后由人工用 Office/WPS 打开验收（方案 §9.3）。
 */

const NOTICE_KEY = 'medical-assistant:document-generation-notice-version'
const NOTICE_VERSION = 'document-generation-v1'
const SENTENCE = '帮我生成一份高血压预防的 PPT'

const CONSULTATION = {
  id: 'c-e2e',
  title: '当前咨询',
  messageCount: 1,
  createdAt: '2026-09-27T02:00:00Z',
  updatedAt: '2026-09-27T02:00:00Z',
}

/** 命中的用户消息：`documentGenerationIntent=true` 由服务端意图门控给出（前端不自行判断）。 */
function userMessage(content = SENTENCE, intent = true) {
  return {
    id: 'm-user-1',
    role: 'user',
    content,
    sequence: 1,
    documentGenerationIntent: intent,
    createdAt: '2026-09-27T02:00:00Z',
  }
}

const DOCX_FILE = {
  id: 'f-docx',
  format: 'docx',
  mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  byteSize: 84_211,
  pageCount: 5,
  available: true,
}

const PPTX_FILE = {
  id: 'f-pptx',
  format: 'pptx',
  mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  byteSize: 132_000,
  pageCount: 9,
  available: true,
}

const PENDING_TASK = {
  id: 'd-e2e',
  sourceMessageId: 'm-user-1',
  status: 'queued',
  formats: ['pptx'],
  title: null,
  model: 'e2e-model',
  files: [],
  sourceCount: 0,
  errorCode: null,
  expiresAt: null,
  // 固定历史日期：下载文件名 `AI医学科普-YYYYMMDD` 就是按 `createdAt` 定的，必须可预期。
  // 需要「刚提交不久」的等待时长时用 `freshPendingTask()`，不要动这个常量。
  createdAt: '2026-09-27T06:00:00Z',
  updatedAt: '2026-09-27T06:00:00Z',
}

/** 与 `PENDING_TASK` 同一形状，但 `createdAt` 就在 20 秒前：等待文案才会显示成「已等待 2X 秒」。 */
function freshPendingTask() {
  const createdAt = new Date(Date.now() - 20_000).toISOString()
  return { ...PENDING_TASK, createdAt, updatedAt: createdAt }
}

/** 一次「PPT + Word」请求完成后仍是**一个**任务、两个下载项（方案 §8.2）。 */
const COMPLETED_TASK = {
  ...PENDING_TASK,
  status: 'completed',
  formats: ['docx', 'pptx'],
  title: '高血压预防科普',
  files: [DOCX_FILE, PPTX_FILE],
  sourceCount: 6,
  expiresAt: '2026-10-27T06:00:00Z',
}

/**
 * 桩表。三条容易漏配的（注释里用 `<id>` 占位，避免出现会提前结束块注释的字符序列）：
 * 1. 发完第一条消息后前端会 `router.replace` 到会话路由并**重新从服务端读回消息**，
 *    所以 `GET /consultations/<id>/messages` 必须也返回这条消息，否则任务卡没有宿主。
 * 2. `GET /consultations/<id>/attachments` 是 HomeView 装载草稿区时调的。
 * 3. `GET /consultations/<id>/document-generations` 是刷新/切会话时的历史恢复入口。
 */
function stubs(overrides: StubTable = {}, intent = true, task: unknown = freshPendingTask()): StubTable {
  return {
    'POST /consultations': { status: 201, body: CONSULTATION },
    'POST /consultations/*/messages': { status: 201, body: userMessage(SENTENCE, intent) },
    'GET /consultations/*/messages': { body: { items: [userMessage(SENTENCE, intent)], hasMore: false } },
    'GET /consultations/*/attachments': { body: { items: [] } },
    // 配图链路与文档链路并行恢复：配图接口也要配好，否则日志里会出现无关的「未配置」告警。
    'GET /consultations/*/image-generations': { body: { items: [] } },
    'GET /consultations/*/document-generations': { body: { items: [] } },
    'POST /consultations/*/document-generations': { status: 202, body: task },
    'GET /document-generations/*/files/*/content': {
      contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      body: { stub: 'e2e-fake-ooxml' },
    },
    'GET /document-generations/*': { body: task },
    'DELETE /document-generations/*': { status: 204, body: {} },
    'GET /users/me/avatar': { status: 404, body: {} },
    ...overrides,
  }
}

interface CapturedRequests {
  paths: string[]
  methods: string[]
  bodies: Record<string, unknown>[]
  /** 带模板创建的 multipart **原文**：字段名与文件名只能从这里断言（`postDataJSON` 读不了表单）。 */
  templateBodies: string[]
  templateContentTypes: string[]
}

/** 记录请求路径、方法与创建任务的请求体：断言「有没有打这个接口、带了什么」。 */
function capture(page: Page): CapturedRequests {
  const captured: CapturedRequests = {
    paths: [], methods: [], bodies: [], templateBodies: [], templateContentTypes: [],
  }
  page.on('request', (request: Request) => {
    const path = new URL(request.url()).pathname
    captured.paths.push(path)
    captured.methods.push(`${request.method()} ${path}`)
    if (request.method() !== 'POST') return
    if (path.endsWith('/document-generations/with-template')) {
      captured.templateBodies.push(request.postData() || '')
      captured.templateContentTypes.push(request.headers()['content-type'] || '')
      return
    }
    if (path.endsWith('/document-generations')) {
      captured.bodies.push(request.postDataJSON() as Record<string, unknown>)
    }
  })
  return captured
}

async function openChat(page: Page, extra: StubTable = {}, intent = true) {
  await installApiStubs(page, { extra: stubs(extra, intent) })
  await page.goto('/app/chat')
  await settle(page)
  await waitForRendered(page, '.composer')
  const tip = page.locator('.voice-tip')
  if (await tip.isVisible()) await tip.locator('.el-alert__close-btn').click()
}

async function askForDocument(page: Page, sentence = SENTENCE) {
  await page.locator('#symptom-input').fill(sentence)
  await page.locator('button.send-button').click()
  await settle(page, 800)
}

function noticeDialog(page: Page) {
  return page.locator('.document-generation-dialog')
}

/** Element Plus 把原生 input 藏起来了，所以要点可见的框体。 */
function agreeCheckbox(page: Page) {
  return noticeDialog(page).locator('.el-checkbox')
}

test.describe('自然语言触发的 PPT/Word 生成', () => {
  test('命中意图：不请求 /stream，首次弹说明，确认后建任务且卡片挂在该用户消息下', async ({ page }) => {
    const captured = capture(page)
    await openChat(page)

    expect(await page.evaluate(key => window.localStorage.getItem(key), NOTICE_KEY)).toBeNull()

    await askForDocument(page)

    // ① 命中后必须跳过文字回答：打 /stream 只会让模型回一句「我无法生成文件」。
    const streamCalls = captured.paths.filter(path => path.endsWith('/stream'))
    expect(streamCalls, `命中意图时不应请求 /stream，实际请求：${captured.paths.join('、')}`).toHaveLength(0)

    // ② 首次使用自动弹出说明，未勾选不能生成：方案 §8.2 要求的要点逐项都在。
    const dialog = noticeDialog(page)
    await expect(dialog, '首次命中应自动弹出说明').toBeVisible({ timeout: 15_000 })
    await expect(dialog).toContainText('内容由 AI 根据当前知识库生成')
    await expect(dialog).toContainText('仅作健康科普，不作诊断、处方或治疗依据')
    await expect(dialog).toContainText('生成可能产生模型费用')
    await expect(dialog).toContainText('30 天后自动删除')
    await expect(dialog.getByRole('button', { name: '同意并生成' })).toBeDisabled()
    expect(captured.bodies, '未勾选前不得创建任务').toHaveLength(0)

    await agreeCheckbox(page).click()
    await dialog.getByRole('button', { name: '同意并生成' }).click()
    await settle(page, 1_200)

    // ③ 请求体按契约：来源是那条用户消息，主题与格式由服务端从原文解析。
    expect(captured.bodies, '确认后应恰好创建一次任务').toHaveLength(1)
    const body = captured.bodies[0]
    expect(body.sourceMessageId, '来源必须是用户消息 id').toBe('m-user-1')
    expect(body.noticeAccepted).toBe(true)
    expect(body.noticeVersion).toBe(NOTICE_VERSION)
    expect(typeof body.clientRequestId, '幂等键必须存在').toBe('string')
    expect('prompt' in body, '前端不传隐藏提示词').toBe(false)
    expect('formats' in body, '格式由服务端从原文解析，前端不传覆盖值').toBe(false)
    expect(await page.evaluate(key => window.localStorage.getItem(key), NOTICE_KEY)).toBe(NOTICE_VERSION)

    // ④ 任务卡挂在这条用户消息下（不是回答下、也不是页面级别）。
    const pair = page.locator('.message-pair').filter({ hasText: '高血压预防' })
    await expect(pair.locator('.user-message'), '用户消息本体应可见').toBeVisible()
    await expect(pair.locator('.generated-document-card'), '任务卡应在该用户消息下').toHaveCount(1)
    await expect(pair.locator('.generated-document-card__status')).toContainText('已排队')
    await expect(pair.locator('.generated-document-card__meta')).toContainText('PPT 演示文稿')

    // ④b 等待体验：有思考动效、有真实阶段与已等待时长；**没有**编造的进度百分比或预计剩余时间。
    const card = pair.locator('.generated-document-card')
    await expect(card.locator('.generated-document-card__thinking'), '等待态应有思考动效').toBeVisible()
    await expect(card.locator('.generated-document-card__pending-hint')).toContainText('等待生成服务')
    await expect(card.locator('.generated-document-card__waited')).toContainText(/已等待 \d+ 秒/)
    await expect(card.locator('.generated-document-card__step'), '三个阶段应全部列出').toHaveCount(3)
    await expect(card.locator('.generated-document-card__step').first(), '当前阶段应高亮').toHaveClass(/is-active/)
    await expect(card).toContainText('最长处理约 5 分钟')
    await expect(card, '不得出现编造的进度百分比').not.toContainText('%')
    await expect(card, '不得出现预计剩余时间').not.toContainText('剩余')

    // ⑤ 页面里不存在任何「点一下生成」的入口：只能靠用户再说那句话（方案 §8.2）。
    await expect(page.getByRole('button', { name: /生成科普文档|生成 PPT|生成 Word|制作文档/ }))
      .toHaveCount(0)
  })

  test('取消说明：不发创建请求、不记版本；「取消」与右上角 × 都算取消', async ({ page }) => {
    const captured = capture(page)
    await openChat(page)
    await askForDocument(page)

    const dialog = noticeDialog(page)
    await expect(dialog).toBeVisible({ timeout: 15_000 })
    await dialog.getByRole('button', { name: '取消' }).click()
    await settle(page, 900)

    // 方案 §8.2「用户取消不发请求」：既不建任务，也不该把说明版本记下来，更不能伪造回答。
    await expect(dialog, '点取消后弹窗应关闭').toBeHidden()
    expect(captured.bodies, '取消不得创建任务').toHaveLength(0)
    expect(captured.paths.filter(path => path.endsWith('/stream')), '取消不得回退聊天').toHaveLength(0)
    expect(await page.evaluate(key => window.localStorage.getItem(key), NOTICE_KEY)).toBeNull()
    await expect(page.locator('.generation-cancel-notice'), '应说明没有建任务、不会扣费')
      .toContainText('没有创建任务，也不会产生费用')
    await expect(page.locator('.generated-document-card')).toHaveCount(0)

    // 再来一次仍先弹说明（没有被静默记住），然后走「右上角 ×」这条路。
    await askForDocument(page)
    await expect(dialog, '未确认过说明时应重新弹出').toBeVisible({ timeout: 15_000 })
    await dialog.locator('.el-dialog__headerbtn').click()
    await settle(page, 900)
    await expect(dialog).toBeHidden()
    expect(captured.bodies, '关闭弹窗同样不得创建任务').toHaveLength(0)
    expect(await page.evaluate(key => window.localStorage.getItem(key), NOTICE_KEY)).toBeNull()
  })

  test('非命中：普通提问照常走 /stream，且页面上没有任何生成入口', async ({ page }) => {
    const captured = capture(page)
    await openChat(page, {}, false)

    await askForDocument(page, '帮我生成一份风景介绍的 PPT')

    const streamCalls = captured.paths.filter(path => path.endsWith('/stream'))
    expect(streamCalls.length, '未命中时仍应正常请求 /stream').toBeGreaterThan(0)
    expect(captured.bodies, '未命中不得创建任何任务').toHaveLength(0)
    await expect(noticeDialog(page)).toHaveCount(0)
    await expect(page.locator('.generated-document-card')).toHaveCount(0)
  })

  test('确认后失败：受控中文原因显示在说明弹窗里，且不回退聊天模型', async ({ page }) => {
    const captured = capture(page)
    await openChat(page, {
      'POST /consultations/*/document-generations': {
        status: 422,
        body: {
          code: 'DOCUMENT_EVIDENCE_INSUFFICIENT',
          message: 'no sources: {"raw":"internal detail"}',
        },
      },
    })
    await askForDocument(page)

    const dialog = noticeDialog(page)
    await expect(dialog).toBeVisible({ timeout: 15_000 })
    await agreeCheckbox(page).click()
    await dialog.getByRole('button', { name: '同意并生成' }).click()
    await settle(page, 1_000)

    const error = dialog.locator('.document-generation-dialog__error')
    await expect(error, '失败原因应显示在说明弹窗里').toBeVisible()
    await expect(error).toContainText('知识库没有足够的可引用资料')
    await expect(error, '不得透传内部错误原文').not.toContainText('internal detail')
    expect(captured.paths.filter(path => path.endsWith('/stream')), '失败不回退聊天模型').toHaveLength(0)
  })
})

test.describe('双格式、下载、删除与恢复', () => {
  test('刷新进入会话：恢复双格式任务，一个卡片两个下载项，下载触发固定文件名', async ({ page }) => {
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [NOTICE_KEY, NOTICE_VERSION],
    )
    await installApiStubs(page, {
      extra: stubs({
        'GET /consultations/*/document-generations': { body: { items: [COMPLETED_TASK] } },
        'GET /consultations/*/messages': { body: { items: [userMessage()], hasMore: false } },
      }),
    })
    await page.goto('/app/consultations/c-e2e')
    await settle(page)

    const card = page.locator('.generated-document-card')
    await expect(card, '刷新进入会话应恢复任务卡').toBeVisible({ timeout: 15_000 })
    await expect(card.locator('.generated-document-card__status'), '状态必须有 aria-live 播报')
      .toHaveAttribute('aria-live', 'polite')
    await expect(card.locator('.generated-document-card__status')).toContainText('已生成')
    await expect(card.locator('.generated-document-card__meta')).toContainText('参考 6 条来源')
    await expect(card.locator('.generated-document-card__disclaimer'), '必须显示 AI 生成边界')
      .toContainText('AI 生成的健康科普资料')
    // 本站不提供在线预览：卡片里不应出现图片或内嵌框架。
    await expect(card.locator('img'), '文档卡片不得做预览').toHaveCount(0)
    await expect(card.locator('iframe'), '文档卡片不得做预览').toHaveCount(0)

    // 两个下载项：格式、页数、大小都对得上。
    const files = card.locator('.generated-document-card__file')
    await expect(files, '两种格式仍是一个任务卡里的两个下载项').toHaveCount(2)
    await expect(files.nth(0)).toContainText('Word 文档')
    await expect(files.nth(0)).toContainText('5 页')
    await expect(files.nth(1)).toContainText('PPT 演示文稿')
    await expect(files.nth(1)).toContainText('9 页幻灯片')

    // 下载走鉴权 Blob（浏览器会给出确定的文件名与扩展名）。
    const downloadPromise = page.waitForEvent('download')
    await files.nth(0).getByRole('button', { name: '下载' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename(), '文件名固定为 AI医学科普-YYYYMMDD.docx')
      .toBe('AI医学科普-20260927.docx')
  })

  test('删除：点删除并确认后调用删除接口，卡片消失', async ({ page }) => {
    const captured = capture(page)
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [NOTICE_KEY, NOTICE_VERSION],
    )
    await installApiStubs(page, {
      extra: stubs({
        'GET /consultations/*/document-generations': { body: { items: [COMPLETED_TASK] } },
        'GET /consultations/*/messages': { body: { items: [userMessage()], hasMore: false } },
      }),
    })
    await page.goto('/app/consultations/c-e2e')
    await settle(page)

    const card = page.locator('.generated-document-card')
    await expect(card).toBeVisible({ timeout: 15_000 })
    await card.getByRole('button', { name: '删除' }).click()
    await settle(page, 400)
    await page.locator('.el-popconfirm').getByRole('button', { name: '删除' }).click()
    await settle(page, 900)

    expect(
      captured.methods.some(item => item === 'DELETE /api/v1/document-generations/d-e2e'),
      `应调用删除接口，实际请求：${captured.methods.join('、')}`,
    ).toBe(true)
    await expect(card, '删除后卡片应消失').toHaveCount(0)
  })

  test('轮询失败只提示不改状态，且提示是受控中文而不是内部原文', async ({ page }) => {
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [NOTICE_KEY, NOTICE_VERSION],
    )
    await installApiStubs(page, {
      extra: stubs({
        'GET /consultations/*/document-generations': { body: { items: [PENDING_TASK] } },
        'GET /consultations/*/messages': { body: { items: [userMessage()], hasMore: false } },
        'GET /document-generations/*': {
          status: 502,
          body: { code: 'DOCUMENT_MODEL_UNAVAILABLE', message: 'upstream boom' },
        },
      }),
    })
    await page.goto('/app/consultations/c-e2e')
    await settle(page)

    const card = page.locator('.generated-document-card')
    await expect(card.locator('.generated-document-card__status')).toBeVisible({ timeout: 15_000 })
    const notice = card.locator('.generated-document-card__notice')
    await expect(notice, '轮询失败应给提示').toBeVisible({ timeout: 20_000 })
    await expect(notice).toContainText('内容生成服务暂时不可用')
    await expect(notice, '不得透传内部错误原文').not.toContainText('upstream boom')
    await expect(card.locator('.generated-document-card__status'), '前端不得改写服务端状态')
      .toContainText('已排队')
  })

  test('降低动态效果：等待信息一个不少，只是不动', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [NOTICE_KEY, NOTICE_VERSION],
    )
    await installApiStubs(page, {
      extra: stubs({
        'GET /consultations/*/document-generations': { body: { items: [freshPendingTask()] } },
        'GET /consultations/*/messages': { body: { items: [userMessage()], hasMore: false } },
      }),
    })
    await page.goto('/app/consultations/c-e2e')
    await settle(page)

    const card = page.locator('.generated-document-card')
    await expect(card.locator('.generated-document-card__status')).toBeVisible({ timeout: 15_000 })
    // 信息不靠动画才读得到：阶段、已等待时长、处理上限照常显示。
    await expect(card.locator('.generated-document-card__pending-hint')).toContainText('等待生成服务')
    await expect(card.locator('.generated-document-card__waited')).toContainText(/已等待 \d+ 秒/)
    await expect(card.locator('.generated-document-card__step')).toHaveCount(3)
    await expect(card).toContainText('最长处理约 5 分钟')
    // 动画本身必须真的关掉（三个思考点）。
    const animations = await card.locator('.generated-document-card__thinking i').evaluateAll(
      nodes => nodes.map(node => getComputedStyle(node).animationName),
    )
    expect(animations, '降低动态效果时三点不应再动').toEqual(['none', 'none', 'none'])
  })

  test('375px：说明弹窗完整落在视口内，勾选框与两个按钮可见可点', async ({ page }) => {
    await openChat(page)
    await page.setViewportSize({ width: 375, height: 720 })
    await askForDocument(page)

    const dialog = noticeDialog(page)
    await expect(dialog).toBeVisible({ timeout: 15_000 })
    const box = await dialog.boundingBox()
    expect(box, '说明弹窗应有布局盒').not.toBeNull()
    const left = Math.round(box!.x)
    const right = Math.round(box!.x + box!.width)
    const width = Math.round(box!.width)
    console.log(`[e2e] 文档说明弹窗坐标：left=${left} right=${right} width=${width}`)
    expect(left, `弹窗左边界 ${left}px 为负，说明被视口裁掉`).toBeGreaterThanOrEqual(-1)
    expect(right, `弹窗右边界 ${right}px 超出 375px 视口（弹窗宽 ${width}px）`).toBeLessThanOrEqual(376)

    await expect(dialog.locator('.el-checkbox'), '勾选框应可见').toBeVisible()
    await expect(dialog.getByRole('button', { name: '同意并生成' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: '取消' })).toBeEnabled()
    // 与配图弹窗同一条规则：工作区本身是桌面优先（`min-width: 1000px`，ADR-011），
    // 窄屏下页面整体会横向溢出，所以只量**弹窗**（挂在 body 上，必须自己适配视口）的几何。
    // 纵向也要量：加了模板区之后弹窗变高，确认按钮必须仍落在视口内（正文区自己滚动）。
    const confirmBox = await dialog.getByRole('button', { name: '同意并生成' }).boundingBox()
    expect(confirmBox, '确认按钮应有布局盒').not.toBeNull()
    const bottom = Math.round(confirmBox!.y + confirmBox!.height)
    console.log(`[e2e] 文档说明弹窗确认按钮下沿：${bottom}px（视口高 720px）`)
    expect(bottom, '确认按钮被挤出视口，用户点不到').toBeLessThanOrEqual(720)
  })
})

/**
 * 上传 PPTX 模板（契约 `PPT_WORD_PLAN.md` §3.3；Codex 在 `COORDINATION.md` §6 第 175 行的前端交接）。
 *
 * 这里只能验证「前端按契约发了什么、拿到响应后显示成什么样」：桩里的「.pptx」是一段假字节，
 * **真实 Office/WPS 版式、背景与文字框映射必须由人工打开文件验收**（方案 §9.3）。
 */
test.describe('上传 PPTX 模板', () => {
  /** 带模板创建返回的任务：`templateMode` 是 `uploaded`（契约 §3.3），前端只显示这个值。 */
  const UPLOADED_TASK = { ...PENDING_TASK, templateMode: 'uploaded' }

  test('选中 .pptx 走带模板接口，multipart 字段齐全，卡片显示实际模板类型', async ({ page }) => {
    const captured = capture(page)
    await installApiStubs(page, {
      extra: stubs({
        'POST /consultations/*/document-generations/with-template': { status: 202, body: UPLOADED_TASK },
      }),
    })
    // 预置说明版本：走「已确认过」的短版弹窗——老用户也必须还能选模板（用户 2026-09-28 的决定）。
    await page.addInitScript(
      ([key, version]) => window.localStorage.setItem(key, version),
      [NOTICE_KEY, NOTICE_VERSION],
    )
    await page.goto('/app/chat')
    await settle(page)
    await waitForRendered(page, '.composer')

    await askForDocument(page)
    const dialog = noticeDialog(page)
    await expect(dialog, '已确认过说明也要弹窗，否则模板没有入口').toBeVisible({ timeout: 15_000 })
    await expect(dialog).toContainText('说明已经确认过')
    await expect(dialog.getByRole('button', { name: '同意并生成' }), '短版不再要求勾说明').toBeEnabled()

    await dialog.locator('input[type="file"]').setInputFiles({
      name: 'my-template.pptx',
      mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      buffer: Buffer.from('e2e-fake-pptx-not-a-real-file'),
    })
    await expect(dialog).toContainText('my-template.pptx')
    // 契约 §3.3：选了模板就必须单独确认模板说明，否则服务端 422 PPT_TEMPLATE_NOTICE_REQUIRED。
    await expect(dialog.getByRole('button', { name: '同意并生成' }), '未勾模板说明不得提交').toBeDisabled()
    await dialog.locator('.el-checkbox', { hasText: '模板原件' }).click()
    await expect(dialog.getByRole('button', { name: '同意并生成' })).toBeEnabled()
    await dialog.getByRole('button', { name: '同意并生成' }).click()
    await settle(page, 1_200)

    expect(captured.bodies, '带模板时不得再打原 JSON 创建接口').toHaveLength(0)
    expect(captured.templateBodies, '应恰好打一次带模板接口').toHaveLength(1)
    const body = captured.templateBodies[0]
    for (const field of [
      'clientRequestId', 'sourceMessageId', 'noticeAccepted', 'noticeVersion', 'templateNoticeAccepted',
    ]) {
      expect(body, `multipart 里缺字段 ${field}`).toContain(`name="${field}"`)
    }
    expect(body, '模板必须以 file 字段上传并带上原文件名').toContain('name="file"; filename="my-template.pptx"')
    expect(body, '说明版本必须是契约固定值').toContain(NOTICE_VERSION)
    expect(captured.templateContentTypes[0], '必须是 multipart 表单').toContain('multipart/form-data')

    await expect(
      page.locator('.generated-document-card__meta'),
      '卡片要显示服务端给的实际模板类型',
    ).toContainText('你上传的模板')
  })

  test('首次给完整说明，确认过一次后第二次是短版，模板入口不消失', async ({ page }) => {
    await openChat(page)
    await askForDocument(page)

    const dialog = noticeDialog(page)
    await expect(dialog).toBeVisible({ timeout: 15_000 })
    await expect(dialog).toContainText('内容由 AI 根据当前知识库生成')
    await agreeCheckbox(page).click()
    await dialog.getByRole('button', { name: '同意并生成' }).click()
    await settle(page, 1_200)
    await expect(page.locator('.generated-document-card')).toBeVisible()

    // 再来一次：不是静默直连生成，而是短版确认——所以模板入口随时可达。
    await askForDocument(page)
    await expect(dialog).toBeVisible({ timeout: 15_000 })
    await expect(dialog).toContainText('说明已经确认过')
    await expect(dialog.locator('.el-checkbox', { hasText: '我已阅读并同意上述说明' })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: '同意并生成' })).toBeEnabled()
    await expect(dialog.locator('input[type="file"]'), '短版也要能选模板').toHaveCount(1)
  })
})