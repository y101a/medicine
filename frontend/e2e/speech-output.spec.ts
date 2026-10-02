import { expect, test, type Page, type Request } from '@playwright/test'
import { installApiStubs, settle, waitForRendered, type StubTable } from './support'

/**
 * 语音输出（TTS）的界面验收（方案 `VOICE_OUTPUT_PLAN.md` §6、§7）。
 *
 * **边界（必须先说清）**：
 * 1. 后端 `/speech/*` **尚未落地**，这里的响应全部来自 `page.route` 桩，所以验证的是
 *    「前端按契约发了什么、拿到某种响应后渲染成什么样」，**不是真实语音链路**。
 * 2. 桩里的「音频」只是 JSON 字节，Chromium 解不了；所以 `HTMLMediaElement.play/pause`
 *    在页面初始化时被替换成可控实现（见 `installSpeechProbe`）。**真实音频能否出声、
 *    音色是否真的换了方言，必须等后端落地后人工听一遍**（方案 §7.3）。
 * 3. 「自动播放被拦」在真实浏览器里只在**没有用户手势**时发生；这里用桩强制抛
 *    `NotAllowedError` 来验收降级界面，触发路径本身由单测覆盖。
 */

const CONSULTATION = {
  id: 'c-e2e',
  title: '语音输出验收',
  messageCount: 3,
  createdAt: '2026-10-01T02:00:00Z',
  updatedAt: '2026-10-01T02:00:00Z',
}

const PRESETS = {
  default: 'mandarin_female',
  items: [
    { id: 'mandarin_female', label: '普通话·自然女声', language: 'zh-CN', dialect: null },
    { id: 'cantonese', label: '广东话', language: 'zh-CN', dialect: 'cantonese' },
  ],
}

const USER_MESSAGE = {
  id: 'm-user',
  role: 'user',
  content: '最近总是头痛，怎么办',
  sequence: 1,
  createdAt: '2026-10-01T02:00:00Z',
}

const ANSWER = {
  id: 'm-answer',
  role: 'assistant',
  content: '头痛的常见原因有很多，多数与睡眠不足、紧张或感冒有关。本回答仅作健康科普，不能替代医生面诊。',
  sequence: 2,
  generationStatus: 'completed',
  createdAt: '2026-10-01T02:00:10Z',
}

/** 已停止生成、只剩占位文字的回答：**不能**出现朗读入口。 */
const STOPPED_ANSWER = {
  id: 'm-stopped',
  role: 'assistant',
  content: '（回答已停止生成）',
  sequence: 4,
  generationStatus: 'stopped',
  createdAt: '2026-10-01T02:00:20Z',
}

function stubs(overrides: StubTable = {}): StubTable {
  return {
    'GET /consultations/c-e2e': { body: CONSULTATION },
    'GET /consultations/*/messages': {
      body: { items: [USER_MESSAGE, ANSWER, STOPPED_ANSWER], hasMore: false },
    },
    'GET /consultations/*/attachments': { body: { items: [] } },
    'GET /consultations/*/image-generations': { body: { items: [] } },
    'GET /consultations/*/document-generations': { body: { items: [] } },
    'GET /speech/presets': { body: PRESETS },
    // 语音接口不用桩表：它要回**可解码的音频字节**，见 `stubSpeechAudio`。
    ...overrides,
  }
}

/**
 * 一段真正的静音 WAV（16 位 PCM，0.2 秒）。
 *
 * 为什么不用「JSON 当假音频」：媒体元素拿到解不开的字节会触发 `error` 事件，
 * 前端据此显示「语音播放失败」——那会把状态机盖掉，测出来的就不是我们想验的降级界面。
 * 契约里真实响应是 `audio/mpeg`；这里给 WAV 只是因为本仓库不带 MP3 编码器，
 * 而**前端不关心容器格式**（它只把响应当 Blob 用），所以对验收目标没有影响。
 */
function silentWav(): Buffer {
  const sampleRate = 8000
  const data = Buffer.alloc(Math.floor(sampleRate * 0.2) * 2)
  const header = Buffer.alloc(44)
  header.write('RIFF', 0)
  header.writeUInt32LE(36 + data.length, 4)
  header.write('WAVE', 8)
  header.write('fmt ', 12)
  header.writeUInt32LE(16, 16)
  header.writeUInt16LE(1, 20)
  header.writeUInt16LE(1, 22)
  header.writeUInt32LE(sampleRate, 24)
  header.writeUInt32LE(sampleRate * 2, 28)
  header.writeUInt16LE(2, 32)
  header.writeUInt16LE(16, 34)
  header.write('data', 36)
  header.writeUInt32LE(data.length, 40)
  return Buffer.concat([header, data])
}

/** 覆盖语音接口的响应。必须在 `installApiStubs` **之后**注册（后注册的 route 先生效）。 */
async function stubSpeechAudio(page: Page, failure?: { status: number; body: unknown }): Promise<void> {
  await page.route('**/api/v1/consultations/*/messages/*/speech', async (route) => {
    if (failure) {
      await route.fulfill({
        status: failure.status,
        contentType: 'application/json',
        body: JSON.stringify(failure.body),
      })
      return
    }
    await route.fulfill({ status: 200, contentType: 'audio/wav', body: silentWav() })
  })
}

interface SpeechProbe {
  created: string[]
  revoked: string[]
  playCalls: number
  pauseCalls: number
}

/**
 * 页面初始化时装两件事（必须在 `goto` 之前调用）：
 * 1. 记录 Object URL 的创建与释放，用来证明「停止/离开页面确实释放了音频」；
 * 2. 把 `HTMLMediaElement.play/pause` 换成可控实现——桩里的字节不是真音频，
 *    `rejectPlay` 用来验收浏览器拦住自动播放时的降级界面。
 */
async function installSpeechProbe(page: Page, options: { rejectPlay?: boolean } = {}): Promise<void> {
  await page.addInitScript(({ rejectPlay }) => {
    const probe: SpeechProbe = { created: [], revoked: [], playCalls: 0, pauseCalls: 0 }
    Object.assign(window, { __speechProbe: probe })
    const create = URL.createObjectURL.bind(URL)
    const revoke = URL.revokeObjectURL.bind(URL)
    URL.createObjectURL = (blob: Blob) => {
      const url = create(blob)
      probe.created.push(url)
      return url
    }
    URL.revokeObjectURL = (url: string) => {
      probe.revoked.push(url)
      revoke(url)
    }
    HTMLMediaElement.prototype.play = function play() {
      probe.playCalls += 1
      // 只拒绝**第一次**（浏览器拦的是没有用户手势的那次自动播放）；
      // 用户点「点击播放」后必须能真的播起来，否则测不出降级后的恢复路径。
      if (!rejectPlay || probe.playCalls > 1) return Promise.resolve()
      return Promise.reject(Object.assign(new Error('blocked'), { name: 'NotAllowedError' }))
    }
    HTMLMediaElement.prototype.pause = function pause() {
      probe.pauseCalls += 1
    }
  }, { rejectPlay: options.rejectPlay === true })
}

async function speechProbe(page: Page): Promise<SpeechProbe> {
  return page.evaluate(() => (window as unknown as { __speechProbe: SpeechProbe }).__speechProbe)
}

interface Captured {
  methods: string[]
  bodies: Record<string, unknown>[]
}

/** 记录方法与请求体：用来断言「有没有打这个接口、带了什么字段」。 */
function capture(page: Page): Captured {
  const captured: Captured = { methods: [], bodies: [] }
  page.on('request', (request: Request) => {
    const path = new URL(request.url()).pathname
    captured.methods.push(`${request.method()} ${path}`)
    if (request.method() === 'POST' && path.endsWith('/speech')) {
      captured.bodies.push(request.postDataJSON() as Record<string, unknown>)
    }
  })
  return captured
}

async function openConversation(
  page: Page,
  extra: StubTable = {},
  speechFailure?: { status: number; body: unknown },
): Promise<void> {
  await installApiStubs(page, { extra: stubs(extra) })
  await stubSpeechAudio(page, speechFailure)
  await page.goto('/app/consultations/c-e2e')
  await settle(page)
  await waitForRendered(page, '.composer')
  const tip = page.locator('.voice-tip')
  if (await tip.isVisible()) await tip.locator('.el-alert__close-btn').click()
}

function answerPair(page: Page) {
  return page.locator('.message-pair').filter({ hasText: '头痛的常见原因' })
}

test.describe('语音输出的入口与请求契约', () => {
  test('只有「已完成且有正文」的助手回答才有朗读入口', async ({ page }) => {
    await installSpeechProbe(page)
    await openConversation(page)

    const pair = answerPair(page)
    await expect(pair.locator('.speech-control'), '完成的回答应有且只有一个朗读控件').toHaveCount(1)
    await expect(pair.getByRole('button', { name: '朗读' })).toBeVisible()
    // 用户自己的消息没有入口（契约 §2.2：只朗读助手回答）。
    await expect(
      page.locator('.message-pair').filter({ hasText: '最近总是头痛' }).getByRole('button', { name: '朗读' }),
      '用户消息不得有朗读入口',
    ).toHaveCount(0)
    // 已停止生成、只剩占位文字的回答也没有入口。
    await expect(
      page.locator('.message-pair').filter({ hasText: '回答已停止生成' }).locator('.speech-control'),
      '未完成的回答不得有朗读入口',
    ).toHaveCount(0)
    await expect(page.locator('.speech-control'), '整页只应出现一个朗读控件').toHaveCount(1)
  })

  test('点朗读：只发产品枚举（无待朗读文本、无供应商参数），播放后停止会释放音频', async ({ page }) => {
    const captured = capture(page)
    await installSpeechProbe(page)
    await openConversation(page)

    await answerPair(page).getByRole('button', { name: '朗读' }).click()
    await settle(page, 800)

    expect(captured.methods, `应恰好请求一次语音接口，实际：${captured.methods.join('、')}`)
      .toContain('POST /api/v1/consultations/c-e2e/messages/m-answer/speech')
    expect(captured.bodies, '应只有一个语音请求体').toHaveLength(1)
    const body = captured.bodies[0]
    expect(body, '客户端只提交产品枚举与语速').toEqual({ speechPreset: 'mandarin_female', rate: 1 })
    for (const forbidden of ['text', 'voice', 'instruction', 'model', 'modelId']) {
      expect(forbidden in body, `不得提交 ${forbidden}（契约 §4.2）`).toBe(false)
    }

    const probe = await speechProbe(page)
    expect(probe.created.length, '应创建过一个内存音频 URL').toBe(1)
    expect(probe.playCalls, '应实际调用过播放').toBe(1)
    expect(probe.revoked, '播放期间不得提前释放').toHaveLength(0)
    await expect(answerPair(page).getByRole('button', { name: '暂停' })).toBeVisible()

    await answerPair(page).getByRole('button', { name: '停止' }).click()
    await settle(page, 500)

    const stopped = await speechProbe(page)
    expect(stopped.revoked, '停止后必须释放 Object URL').toEqual(stopped.created)
    expect(stopped.pauseCalls, '停止应先暂停播放').toBeGreaterThan(0)
    await expect(answerPair(page).getByRole('button', { name: '朗读' }), '停止后回到可朗读状态').toBeVisible()
  })

  test('浏览器拦住自动播放：显示「语音已生成，点击播放」，点它不再重复请求', async ({ page }) => {
    const captured = capture(page)
    await installSpeechProbe(page, { rejectPlay: true })
    await openConversation(page)

    await answerPair(page).getByRole('button', { name: '朗读' }).click()
    await settle(page, 800)

    const pair = answerPair(page)
    await expect(pair.locator('.speech-status'), '被拦后应给出可点的降级文案').toContainText('语音已生成，点击播放')
    await expect(pair.getByRole('button', { name: '点击播放' })).toBeVisible()
    expect(captured.bodies, '被拦只产生一次请求').toHaveLength(1)

    await pair.getByRole('button', { name: '点击播放' }).click()
    await settle(page, 600)

    expect(captured.bodies, '复用已生成的音频，不得再请求一次（重复请求=重复计费）').toHaveLength(1)
    await expect(pair.getByRole('button', { name: '暂停' })).toBeVisible()
  })

  test('后端未落地（404）：受控中文原因，不透传内部字段，文字回答照常显示', async ({ page }) => {
    await installSpeechProbe(page)
    await openConversation(page, {}, {
      status: 404,
      body: { code: 'SPEECH_SERVICE_UNAVAILABLE', message: 'e2e 未配置该接口：internal detail' },
    })

    await answerPair(page).getByRole('button', { name: '朗读' }).click()
    await settle(page, 800)

    const status = answerPair(page).locator('.speech-status')
    await expect(status, '失败要给受控中文短句').toContainText('没有找到可朗读的回答')
    const text = (await status.textContent()) || ''
    expect(text, '不得透传内部错误原文').not.toContain('internal detail')
    expect(text, '不得泄露错误体结构').not.toMatch(/[<>{}[\]]/)
    // 语音失败只影响语音：文字回答与免责声明原样保留。
    await expect(answerPair(page)).toContainText('头痛的常见原因')
    await expect(answerPair(page)).toContainText('不能替代医生面诊')
  })

  test('预设列表拉不到：退回「只普通话」兜底并提示，朗读仍可用', async ({ page }) => {
    const captured = capture(page)
    await installSpeechProbe(page)
    await openConversation(page, {
      'GET /speech/presets': { status: 404, body: { message: 'e2e 未配置该接口' } },
    })

    await expect(page.locator('.speech-preset-select'), '模式关闭时不常驻占用底栏').toHaveCount(0)
    await page.locator('.speech-mode-button').click()
    await expect(page.locator('.speech-settings-panel'), '点耳机先弹出设置面板').toBeVisible()
    await page.locator('.speech-mode-enable').click()
    await expect(page.locator('.speech-preset-select'), '开启后音色与语速就在同一面板里').toBeVisible()
    await expect(page.locator('.speech-presets-notice'), '要说明方言列表暂时拿不到').toContainText('普通话')
    await expect(page.locator('.speech-preset-select'), '兜底只留普通话').toContainText('普通话·自然女声')
    await expect(page.locator('.speech-preset-select'), '不得自己编一个方言').not.toContainText('广东话')
    await expect(page.locator('.speech-preset-select option'), '下拉里只应有一个兜底音色').toHaveCount(1)
    await expect(page.locator('.speech-preset-select option[value="cantonese"]'), '不得伪造服务端没有的方言')
      .toHaveCount(0)
    await expect(page.locator('.speech-preset-select')).toHaveValue('mandarin_female')
    await expect(page.locator('.speech-rate-select')).toHaveValue('1')

    await answerPair(page).getByRole('button', { name: '朗读' }).click()
    await settle(page, 800)
    expect(captured.bodies[0]?.speechPreset, '兜底时用默认普通话').toBe('mandarin_female')
  })
})

test.describe('语音对话模式与生命周期', () => {
  test('模式默认关闭、刷新后仍是关闭、刷新也不重播历史回答', async ({ page }) => {
    const captured = capture(page)
    await installSpeechProbe(page)
    await openConversation(page)

    const mode = page.locator('.speech-mode-button')
    await expect(mode, '默认必须关闭（公共电脑不能自己出声）').toHaveAttribute('aria-pressed', 'false')
    await expect(page.locator('.speech-preset-select'), '关闭时不显示音色与语速').toHaveCount(0)
    await mode.click()
    await expect(page.locator('.speech-settings-panel'), '点耳机先弹出设置面板').toBeVisible()
    await expect(page.locator('.speech-mode-enable'), '默认应是「开启」按钮，而不是已在朗读').toBeVisible()
    await page.locator('.speech-mode-enable').click()
    await expect(mode, '开启后按钮状态可见').toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('.speech-preset-select')).toBeVisible()
    await expect(page.locator('.speech-rate-select')).toBeVisible()

    // 面板内关闭：音色与语速随之收起，不需要靠刷新回到关闭。
    await page.locator('.speech-mode-disable').click()
    await expect(page.locator('.speech-preset-select'), '关闭后不再显示音色').toHaveCount(0)
    await expect(page.locator('.speech-mode-enable'), '关闭后回到「开启」按钮').toBeVisible()

    // 再次开启后刷新，仍应按公共电脑安全规则回到关闭。
    await page.locator('.speech-mode-enable').click()
    await expect(page.locator('.speech-preset-select')).toBeVisible()

    await page.reload()
    await settle(page)
    await waitForRendered(page, '.composer')
    await expect(page.locator('.speech-mode-button'), '刷新后回到关闭：模式不落本地存储')
      .toHaveAttribute('aria-pressed', 'false')
    await expect(page.locator('.speech-preset-select')).toHaveCount(0)
    const stored = await page.evaluate(() => Object.keys(window.localStorage))
    expect(stored.filter(key => key.includes('speech-mode')), `不得存模式：${stored.join('、')}`).toHaveLength(0)
    expect(captured.bodies, '刷新进入会话不得自动朗读历史回答').toHaveLength(0)
  })

  test('给用户明确要求历史的回答配了意图：进入页面也不会自己出声', async ({ page }) => {
    const captured = capture(page)
    await installSpeechProbe(page)
    await openConversation(page, {
      'GET /consultations/*/messages': {
        body: {
          items: [
            { ...USER_MESSAGE, speechOutputIntent: { requested: true, speechPreset: 'cantonese' } },
            ANSWER,
          ],
          hasMore: false,
        },
      },
    })

    await expect(answerPair(page).locator('.speech-control')).toHaveCount(1)
    await settle(page, 600)
    expect(captured.bodies, '只有「本轮回答刚完成」才自动朗读，历史意图不重播').toHaveLength(0)
  })

  test('离开会话（切到设置页）要先停止播放并释放音频', async ({ page }) => {
    await installSpeechProbe(page)
    await openConversation(page)

    await answerPair(page).getByRole('button', { name: '朗读' }).click()
    await settle(page, 800)
    expect((await speechProbe(page)).playCalls, '先确认真的在播').toBe(1)

    // 同一个 SPA 内换到设置页：HomeView 卸载，播放必须停下、字节必须释放。
    // 顺带证明这是 SPA 导航（整页加载会把 JS 环境连同探针一起重置，那样测不出释放）。
    let loads = 0
    page.on('load', () => { loads += 1 })
    await page.locator('a[href="/app/settings"]').first().click()
    await expect(page).toHaveURL(/\/app\/settings/)
    await settle(page, 800)

    const probe = await speechProbe(page)
    console.log(`[e2e] 离开会话：loads=${loads} playCalls=${probe.playCalls} pauseCalls=${probe.pauseCalls}`
      + ` created=${probe.created.length} revoked=${probe.revoked.length}`)
    expect(loads, '必须是 SPA 内导航（整页加载会掩盖释放行为）').toBe(0)
    expect(probe.pauseCalls, '离开页面应暂停播放').toBeGreaterThan(0)
    expect(probe.revoked, '离开页面必须释放 Object URL').toEqual(probe.created)
  })
})

test.describe('可访问性与窄屏', () => {
  test('朗读控件是真实按钮、可键盘触发，状态有 aria-live 播报', async ({ page }) => {
    const captured = capture(page)
    await installSpeechProbe(page)
    await openConversation(page)

    const button = answerPair(page).getByRole('button', { name: '朗读' })
    await expect(button).toHaveAttribute('type', 'button')
    await expect(answerPair(page).locator('.speech-status')).toHaveAttribute('aria-live', 'polite')

    await button.focus()
    await page.keyboard.press('Enter')
    await settle(page, 800)

    expect(captured.methods, '键盘 Enter 应与点击等效').toContain(
      'POST /api/v1/consultations/c-e2e/messages/m-answer/speech',
    )
  })

  test('375px：朗读入口与音色/语速选择仍在容器内可见可点', async ({ page }) => {
    const captured = capture(page)
    await installSpeechProbe(page)
    await openConversation(page)
    await page.setViewportSize({ width: 375, height: 720 })
    await settle(page, 600)

    await expect(page.locator('.speech-preset-select'), '关闭时选择器不应常驻').toHaveCount(0)
    await page.locator('.speech-mode-button').click()
    await page.locator('.speech-mode-enable').click()
    await expect(page.locator('.speech-settings-panel')).toBeVisible()
    await expect(page.locator('.speech-preset-select'), '开启后音色选择可见').toBeVisible()

    // 用户 2026-10-02 的布局要求：左下角是「+」，其余（含语音模式与麦克风）在右侧。
    const composerBox = await page.locator('.composer').boundingBox()
    const moreBox = await page.locator('.composer-more-button').boundingBox()
    const modeBox = await page.locator('.speech-mode-button').boundingBox()
    expect(composerBox, '输入框应有布局盒').not.toBeNull()
    expect(moreBox, '左下角的「+」应有布局盒').not.toBeNull()
    expect(modeBox, '语音模式入口应有布局盒').not.toBeNull()
    console.log(`[e2e] 375px 布局：「+」=${Math.round(moreBox!.x)}~${Math.round(moreBox!.x + moreBox!.width)}px，语音模式左边界 ${Math.round(modeBox!.x)}px`)
    expect(moreBox!.x - composerBox!.x, '「+」应贴输入框左侧').toBeLessThan(composerBox!.width / 2)
    expect(modeBox!.x, '语音模式入口应在「+」右侧').toBeGreaterThanOrEqual(moreBox!.x + moreBox!.width)

    // 工作区是桌面优先（`min-width: 1000px`，ADR-011），窄屏整页会横向溢出，
    // 所以只量「控件是否溢出它自己的容器」，而不是量视口。
    for (const [label, child, parent] of [
      ['朗读控件', answerPair(page).locator('.speech-control'), answerPair(page).locator('.assistant-message')],
      ['音色/语速设置', page.locator('.speech-setting-field').first(), page.locator('.speech-settings-panel')],
      ['音色选择', page.locator('.speech-preset-select'), page.locator('.speech-settings-panel')],
      ['语速选择', page.locator('.speech-rate-select'), page.locator('.speech-settings-panel')],
    ] as const) {
      const childBox = await child.boundingBox()
      const parentBox = await parent.boundingBox()
      expect(childBox, `${label}应有布局盒`).not.toBeNull()
      expect(parentBox, `${label}的容器应有布局盒`).not.toBeNull()
      const childRight = Math.round(childBox!.x + childBox!.width)
      const parentRight = Math.round(parentBox!.x + parentBox!.width)
      console.log(`[e2e] 375px ${label}：右边界 ${childRight}px，容器右边界 ${parentRight}px`)
      expect(childRight, `${label}溢出容器（${childRight}px > ${parentRight}px）`).toBeLessThanOrEqual(parentRight + 1)
    }

    await expect(page.locator('.composer-more-button'), '「+」入口仍可见').toBeVisible()
    await expect(page.locator('.speech-preset-select'), '开启后音色选择可见').toBeVisible()
    await expect(page.locator('.speech-rate-select'), '开启后语速选择可见').toBeVisible()

    await answerPair(page).getByRole('button', { name: '朗读' }).click()
    await settle(page, 800)
    expect(captured.bodies, '窄屏下仍能点出语音请求').toHaveLength(1)
  })
})
