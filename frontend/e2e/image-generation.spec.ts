import { expect, test, type Page, type Request } from '@playwright/test'
import { installApiStubs, settle, waitForRendered, type StubTable } from './support'

/**
 * 自然语言触发的 AI 科普配图的界面验收（`IMAGE_GENERATION_PLAN.md` §7.1/§7.2/§8.2、
 * `COORDINATION.md` 第 175/178/179 行的交接）。
 *
 * 2026-09-25 起没有回答底部的生成按钮：用户在对话里说「帮我生成一张关于人体结构的图片」，
 * 服务端 `/messages` 响应给 `imageGenerationIntent=true`，前端**跳过 `/stream`** 直接创建任务，
 * 任务卡挂在该用户消息下；首次使用先弹一次费用/标识协议，确认后按协议版本记忆。
 *
 * 这里走的是**真实用户路径**（输入 → 提交 → 弹窗 → 确认），接口全部由 `page.route` 拦截，
 * 所以验证的是「前端拿到某种响应后渲染成什么样」。**边界**：成品字节是桩（不可解码的假 webp），
 * 因此只断言「创建了 Blob URL 与固定下载名」，画面内容与图内是否有水印文字只能在人工验收里看
 * （见 `BROWSER_ACCEPTANCE.md`）。
 */

const NOTICE_KEY = 'medical-assistant:image-generation-notice-version'
const NOTICE_VERSION = 'image-generation-v1'
const SENTENCE = '帮我生成一张关于人体结构的图片'

const CONSULTATION = {
  id: 'c-e2e',
  title: '当前咨询',
  messageCount: 1,
  createdAt: '2026-09-25T02:00:00Z',
  updatedAt: '2026-09-25T02:00:00Z',
}

/** 命中的用户消息：`imageGenerationIntent=true` 由服务端意图门控给出（前端不自行判断）。 */
function userMessage(content = SENTENCE, intent = true) {
  return {
    id: 'm-user-1',
    role: 'user',
    content,
    sequence: 1,
    imageGenerationIntent: intent,
    createdAt: '2026-09-25T02:00:00Z',
  }
}

const PENDING_TASK = {
  id: 'g-e2e',
  contentId: 'ig-content-1',
  sourceMessageId: 'm-user-1',
  status: 'submitted',
  style: 'medical_illustration',
  aspectRatio: '4:3',
  model: 'wan2.6-t2i',
  imageAvailable: false,
  imageExpiresAt: null,
  errorCode: null,
  createdAt: '2026-09-25T06:00:00Z',
  updatedAt: '2026-09-25T06:00:00Z',
}

const COMPLETED_TASK = {
  ...PENDING_TASK,
  status: 'completed',
  imageAvailable: true,
  imageExpiresAt: '2026-12-24T06:00:00Z',
}

/**
 * 桩表。注意三条容易漏配的（这里用 `<id>` 占位，避免注释里出现会提前结束块注释的字符）：
 * 1. 发完第一条消息后前端会 `router.replace` 到会话路由并**重新从服务端读回消息**，
 *    所以 `GET /consultations/<id>/messages` 必须也返回这条消息，否则卡片没有可挂的宿主。
 * 2. `GET /consultations/<id>/attachments` 是 HomeView 装载草稿区时调的。
 * 3. 假 webp 的字节是桩（`support.ts` 只会 `JSON.stringify`），只用于断言 Blob URL 已创建。
 */
function stubs(overrides: StubTable = {}, intent = true, task: unknown = PENDING_TASK): StubTable {
  return {
    'POST /consultations': { status: 201, body: CONSULTATION },
    'POST /consultations/*/messages': { status: 201, body: userMessage(SENTENCE, intent) },
    'GET /consultations/*/messages': { body: { items: [userMessage(SENTENCE, intent)], hasMore: false } },
    'GET /consultations/*/attachments': { body: { items: [] } },
    'GET /consultations/*/image-generations': { body: { items: [] } },
    'POST /consultations/*/image-generations': { status: 202, body: task },
    'GET /image-generations/*/content': { contentType: 'image/webp', body: { stub: 'e2e-fake-webp' } },
    'GET /image-generations/*': { body: task },
    'GET /users/me/avatar': { status: 404, body: {} },
    ...overrides,
  }
}

interface CapturedRequests {
  paths: string[]
  bodies: Record<string, unknown>[]
}

/** 记录请求路径与创建任务的请求体：断言「有没有打这个接口、带了什么」。 */
function capture(page: Page): CapturedRequests {
  const captured: CapturedRequests = { paths: [], bodies: [] }
  page.on('request', (request: Request) => {
    const path = new URL(request.url()).pathname
    captured.paths.push(path)
    if (request.method() === 'POST' && path.endsWith('/image-generations')) {
      const body = request.postDataJSON() as Record<string, unknown>
      captured.bodies.push(body)
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

async function askForImage(page: Page, sentence = SENTENCE) {
  await page.locator('#symptom-input').fill(sentence)
  await page.locator('button.send-button').click()
  await settle(page, 800)
}

function noticeDialog(page: Page) {
  return page.locator('.image-generation-dialog')
}

/** Element Plus 把原生 input 藏起来了（`.el-checkbox__original` 是 hidden），所以要点可见的框体。 */
function agreeCheckbox(page: Page) {
  return noticeDialog(page).locator('.el-checkbox')
}

test.describe('自然语言触发的科普配图', () => {
  test('命中意图：不请求 /stream，首次弹协议，确认后建任务且卡片挂在该用户消息下', async ({ page }) => {
    const captured = capture(page)
    await openChat(page)

    expect(await page.evaluate(key => window.localStorage.getItem(key), NOTICE_KEY)).toBeNull()

    await askForImage(page)

    // ① 命中后必须跳过文字回答：一旦打了 /stream，DeepSeek 就会回「不能生成图片」。
    const streamCalls = captured.paths.filter(path => path.endsWith('/stream'))
    expect(streamCalls, `命中意图时不应请求 /stream，实际请求：${captured.paths.join('、')}`).toHaveLength(0)

    // ② 首次使用自动弹出费用/标识/用途协议，且未勾选不能生成（方案 §7.2）。
    const dialog = noticeDialog(page)
    await expect(dialog, '首次命中应自动弹出协议').toBeVisible({ timeout: 15_000 })
    await expect(dialog).toContainText('图片由 AI 生成，仅作科普示意')
    await expect(dialog).toContainText('不作为诊断、检查或治疗依据')
    await expect(dialog).toContainText('每次生成可能产生费用')
    await expect(dialog).toContainText('图片内不含水印标识')
    await expect(dialog.getByRole('button', { name: '同意并生成' })).toBeDisabled()
    expect(captured.bodies, '未勾选前不得创建任务').toHaveLength(0)

    await agreeCheckbox(page).click()
    await dialog.getByRole('button', { name: '同意并生成' }).click()
    await settle(page, 1_200)

    // ③ 请求体按契约：来源是那条用户消息，风格/比例交给服务端默认值。
    expect(captured.bodies, '确认后应恰好创建一次任务').toHaveLength(1)
    const body = captured.bodies[0]
    expect(body.sourceMessageId, '来源必须是用户消息 id').toBe('m-user-1')
    expect(body.noticeAccepted).toBe(true)
    expect(body.noticeVersion).toBe(NOTICE_VERSION)
    expect(body.prompt, 'prompt 只作非空占位，服务端会用来源消息重新取值').toBe(SENTENCE)
    expect('style' in body, '前端不选风格，交给服务端默认').toBe(false)
    expect('aspectRatio' in body, '前端不选比例，交给服务端默认').toBe(false)
    expect(await page.evaluate(key => window.localStorage.getItem(key), NOTICE_KEY)).toBe(NOTICE_VERSION)

    // ④ 任务卡挂在这条用户消息下（不是回答下、也不是页面级别）。
    const pair = page.locator('.message-pair').filter({ hasText: '人体结构' })
    await expect(pair.locator('.user-message'), '用户消息本体应可见').toBeVisible()
    await expect(pair.locator('.generated-image-card'), '任务卡应在该用户消息下').toHaveCount(1)
    await expect(pair.locator('.generated-image-card__status')).toContainText('等待生成')

    // ⑤ 页面里不存在任何「点一下生成」的入口：只能靠用户再说那句话（方案 §7.1）。
    await expect(page.locator('.image-generation-offer'), '旧入口组件必须已删除').toHaveCount(0)
    await expect(page.getByRole('button', { name: /生成科普配图|生成配图/ })).toHaveCount(0)
  })

  test('取消协议：不发创建请求、不记协议版本；「取消」与右上角 × 都算取消', async ({ page }) => {
    const captured = capture(page)
    await openChat(page)
    await askForImage(page)

    const dialog = noticeDialog(page)
    await expect(dialog).toBeVisible({ timeout: 15_000 })
    await dialog.getByRole('button', { name: '取消' }).click()
    await settle(page, 900)

    // 方案 §8.2「用户取消不发请求」：既不建任务，也不该把协议版本记下来。
    await expect(dialog, '点取消后弹窗应关闭').toBeHidden()
    expect(captured.bodies, '取消不得创建任务').toHaveLength(0)
    expect(await page.evaluate(key => window.localStorage.getItem(key), NOTICE_KEY)).toBeNull()
    await expect(page.locator('.generation-cancel-notice'), '应说明没有建任务、不会扣费')
      .toContainText('没有创建任务，也不会产生费用')

    // 再来一次仍然先弹协议（没有被静默记住），然后再走「右上角 ×」这条路。
    await askForImage(page)
    await expect(dialog, '未确认过协议时应重新弹出').toBeVisible({ timeout: 15_000 })
    await dialog.locator('.el-dialog__headerbtn').click()
    await settle(page, 900)
    await expect(dialog).toBeHidden()
    expect(captured.bodies, '关闭弹窗同样不得创建任务').toHaveLength(0)
    expect(await page.evaluate(key => window.localStorage.getItem(key), NOTICE_KEY)).toBeNull()
  })

  test('非命中：普通提问照常走 /stream，且页面上没有任何生成入口', async ({ page }) => {
    const captured = capture(page)
    await openChat(page, {}, false)

    await askForImage(page, '帮我生成一张风景图片')

    const streamCalls = captured.paths.filter(path => path.endsWith('/stream'))
    expect(streamCalls.length, '未命中时仍应正常请求 /stream').toBeGreaterThan(0)
    expect(captured.bodies, '未命中不得创建任何任务').toHaveLength(0)
    await expect(noticeDialog(page)).toHaveCount(0)
    await expect(page.locator('.generated-image-card')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /生成科普配图|生成配图/ })).toHaveCount(0)
  })
})

test.describe('状态、窄屏与恢复', () => {
  test('任务状态用 aria-live 播报；降低动态效果时同样能立刻读到', async ({ page }) => {
    // 预置已确认的协议版本：绕开弹窗，直接验收任务卡本身。
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await installApiStubs(page, {
      extra: stubs({
        'GET /consultations/*/image-generations': { body: { items: [COMPLETED_TASK] } },
        'GET /consultations/*/messages': { body: { items: [userMessage()], hasMore: false } },
      }),
    })
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [NOTICE_KEY, NOTICE_VERSION],
    )
    await page.goto('/app/consultations/c-e2e')
    await settle(page)

    const status = page.locator('.generated-image-card__status')
    await expect(status, '刷新进入会话应恢复任务卡').toBeVisible({ timeout: 15_000 })
    await expect(status, '状态必须有 aria-live 播报').toHaveAttribute('role', 'status')
    await expect(status).toHaveAttribute('aria-live', 'polite')
    await expect(status).toContainText('已生成')

    // 成品与固定下载名：用的是鉴权取回的 Blob URL，不是供应商 URL。
    const link = page.locator('.generated-image-card__download')
    await expect(link, '完成态应给出下载入口').toBeVisible()
    await expect(link).toHaveAttribute('download', 'AI科普配图-20260925.webp')
    expect(
      (await link.getAttribute('href'))?.startsWith('blob:'),
      '下载链接必须是本地 Blob URL',
    ).toBe(true)
    await expect(page.locator('.generated-image-card__disclaimer')).toContainText('AI 生成·科普示意')
  })

  test('375px：协议弹窗完整落在视口内，勾选框与两个按钮可见可点', async ({ page }) => {
    await openChat(page)
    await page.setViewportSize({ width: 375, height: 720 })
    await askForImage(page)

    const dialog = noticeDialog(page)
    await expect(dialog).toBeVisible({ timeout: 15_000 })
    const box = await dialog.boundingBox()
    expect(box, '协议弹窗应有布局盒').not.toBeNull()
    const left = Math.round(box!.x)
    const right = Math.round(box!.x + box!.width)
    const width = Math.round(box!.width)
    console.log(`[e2e] 协议弹窗坐标：left=${left} right=${right} width=${width}`)
    expect(left, `弹窗左边界 ${left}px 为负，说明被视口裁掉`).toBeGreaterThanOrEqual(-1)
    // 关键回归：固定 560px 宽时右边界会到 560，在 375px 视口里直接出界。
    expect(right, `弹窗右边界 ${right}px 超出 375px 视口（弹窗宽 ${width}px）`).toBeLessThanOrEqual(376)

    await expect(dialog.locator('.el-checkbox'), '勾选框应可见').toBeVisible()
    await expect(dialog.getByRole('button', { name: '同意并生成' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: '取消' })).toBeEnabled()
    // 说明：工作区本身是桌面优先（`min-width: 1000px`，ADR-011），窄屏下页面整体会横向溢出，
    // 所以这里只量**弹窗**的几何——弹窗挂在 body 上，必须自己适配视口。
  })

  test('轮询失败只提示不改状态，且提示是受控中文而不是供应商原文', async ({ page }) => {
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [NOTICE_KEY, NOTICE_VERSION],
    )
    await installApiStubs(page, {
      extra: stubs({
        'GET /consultations/*/image-generations': { body: { items: [PENDING_TASK] } },
        'GET /consultations/*/messages': { body: { items: [userMessage()], hasMore: false } },
        'GET /image-generations/*': {
          status: 502,
          body: { code: 'IMAGE_GENERATION_PROVIDER_UNAVAILABLE', message: 'upstream boom' },
        },
      }),
    })
    await page.goto('/app/consultations/c-e2e')
    await settle(page)

    const status = page.locator('.generated-image-card__status')
    await expect(status).toBeVisible({ timeout: 15_000 })
    const notice = page.locator('.generated-image-card__notice')
    await expect(notice, '轮询失败应给提示').toBeVisible({ timeout: 20_000 })
    await expect(notice).toContainText('图片生成服务暂时不可用')
    await expect(notice, '不得透传供应商/内部错误原文').not.toContainText('upstream boom')
    await expect(status, '服务端才是状态的事实来源，前端不得改写状态').toContainText('等待生成')
  })

  test('桩返回内部错误码时只显示受控中文文案，且不回退成文字回答', async ({ page }) => {
    const captured = capture(page)
    await openChat(page, {
      'POST /consultations/*/image-generations': {
        status: 502,
        body: { code: 'IMAGE_GENERATION_PROVIDER_REJECTED', message: 'provider rejected: {"raw":1}' },
      },
    })
    await askForImage(page)

    const dialog = noticeDialog(page)
    await expect(dialog).toBeVisible({ timeout: 15_000 })
    await agreeCheckbox(page).click()
    await dialog.getByRole('button', { name: '同意并生成' }).click()
    await settle(page, 1_000)

    const error = dialog.locator('.image-generation-dialog__error')
    await expect(error, '失败原因应显示在协议弹窗里').toBeVisible()
    await expect(error).toContainText('没有通过内容审核')
    await expect(error, '不得透传供应商正文或内部码').not.toContainText('provider rejected')
    expect(captured.paths.filter(path => path.endsWith('/stream')), '失败不回退聊天模型').toHaveLength(0)
  })
})