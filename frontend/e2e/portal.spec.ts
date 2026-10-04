import { expect, test } from '@playwright/test'
import { describeOverflow, installApiStubs, measureOverflow, waitForRendered } from './support'

/**
 * 独立资讯门户 `/portal`（F1 页面框架）。
 *
 * 与工作区不同：门户是独立布局，**不受 ADR-011 的 1000px 桌面优先约束**，
 * 所以这里 375px 也要真的无横向溢出，而不是靠 `.viewport-hint` 提示。
 * 接口全部走桩（`GET /news` 返回未接入新闻源的空页），不依赖后端。
 */
const NEWS_EMPTY = {
  category: 'all',
  status: 'sources_not_connected',
  asOf: null,
  items: [],
  tips: [],
}

for (const width of [1280, 375]) {
  test(`${width}px：/portal 无横向溢出，且不显示工作区侧栏`, async ({ page }) => {
    const stubs = await installApiStubs(page, {
      authenticated: true,
      extra: { 'GET /news': { body: NEWS_EMPTY } },
    })

    await page.setViewportSize({ width, height: width === 375 ? 720 : 800 })
    await page.goto('/portal')
    await waitForRendered(page, '.portal')

    const landed = new URL(page.url()).pathname
    expect(landed, `/portal 被重定向到了 ${landed}`).toBe('/portal')

    // 独立布局：没有工作区侧栏，也没有 ADR-011 的窄屏提示。
    await expect(page.locator('.sidebar')).toHaveCount(0)
    await expect(page.locator('.viewport-hint')).toHaveCount(0)
    await expect(page.getByText('新闻源尚未接入')).toBeVisible()

    const report = await measureOverflow(page)
    expect(report.overflow, describeOverflow(report, '/portal', width)).toBeLessThanOrEqual(1)
    expect(stubs.unmatched, `门户请求了未配置的接口：${stubs.unmatched.join('、')}`).toEqual([])
  })
}

test('1280px：AI 展示区约占首屏一半，装饰动画生效但不高过视口', async ({ page }) => {
  await installApiStubs(page, {
    authenticated: true,
    extra: { 'GET /news': { body: NEWS_EMPTY } },
  })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/portal')
  await waitForRendered(page, '.portal')

  const box = await page.locator('.hero').boundingBox()
  expect(box, '没有找到 AI 展示区 .hero').not.toBeNull()
  // 用户要求「占据一半屏幕」：实测不少于首屏的 45%，也不超过整屏（否则会把下面分区挤出首屏）。
  expect(box!.height).toBeGreaterThanOrEqual(800 * 0.45)
  expect(box!.height).toBeLessThanOrEqual(800)

  const heroAnimation = await page.locator('.hero').evaluate(el => getComputedStyle(el).animationName)
  expect(heroAnimation, 'AI 展示区的渐变动效应生效').not.toBe('none')
  const orbAnimation = await page.locator('.orb--1').evaluate(el => getComputedStyle(el).animationName)
  // scoped 样式会给关键帧名加哈希后缀（floatY-xxxxxxxx），只断言前缀。
  expect(orbAnimation, '漂浮光斑动效应生效').toContain('floatY')
})

test('1280px：五个分区（含全部）平铺在 AI 展示区下方并铺满整行', async ({ page }) => {
  await installApiStubs(page, {
    authenticated: true,
    extra: { 'GET /news': { body: NEWS_EMPTY } },
  })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/portal')
  await waitForRendered(page, '.portal')

  const tiles = page.locator('.category-tile')
  await expect(tiles).toHaveCount(5)
  await expect(tiles.nth(0)).toContainText('全部')

  const heroBox = await page.locator('.hero').boundingBox()
  const first = await tiles.nth(0).boundingBox()
  const last = await tiles.nth(4).boundingBox()
  expect(first, '没有找到分区卡片 .category-tile').not.toBeNull()

  // 平铺在 AI 展示区下面
  expect(first!.y, '分区应排在 AI 展示区下方').toBeGreaterThanOrEqual(heroBox!.y + heroBox!.height - 1)
  // 同一行五块，每块都够大，并铺满内容区整行
  expect(Math.abs(last!.y - first!.y), '五块应在同一行').toBeLessThan(2)
  expect(first!.width, '分区卡片应放大到至少 200px 宽').toBeGreaterThanOrEqual(200)
  const gridWidth = await page.locator('.categories').evaluate(el => el.getBoundingClientRect().width)
  const rowWidth = last!.x + last!.width - first!.x
  expect(rowWidth / gridWidth, '五块应铺满整行').toBeGreaterThan(0.98)
})

test('未登录访问 /portal 回到登录页并记住回跳地址', async ({ page }) => {
  await installApiStubs(page, { authenticated: false })
  await page.goto('/portal')
  await waitForRendered(page, 'main')

  const url = new URL(page.url())
  expect(url.pathname).toBe('/login')
  expect(url.searchParams.get('redirect')).toBe('/portal')
})

test('门户不伪造新闻，下载入口不可用，“与 AI 对话”进入工作区聊天', async ({ page }) => {
  await installApiStubs(page, {
    authenticated: true,
    extra: {
      'GET /news': { body: NEWS_EMPTY },
      // 聊天页会读语音预设；不配就会打印一条「未配置的接口」，干扰阅读。
      'GET /speech/presets': {
        body: {
          default: 'mandarin_female',
          items: [{ id: 'mandarin_female', label: '普通话·自然女声', language: 'zh-CN', dialect: null }],
        },
      },
    },
  })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/portal')
  await waitForRendered(page, '.portal')

  // 没有条目：不得出现「今日已更新」，也不得有卡片外链。
  await expect(page.getByText('今日已更新')).toHaveCount(0)
  await expect(page.locator('.cards')).toHaveCount(0)

  const download = page.getByRole('button', { name: /下载 Windows 版/ })
  await expect(download).toBeDisabled()

  await page.getByRole('button', { name: /与 AI 对话/ }).click()
  await waitForRendered(page, '.workspace')
  expect(new URL(page.url()).pathname).toBe('/app/chat')
  // 工作区照旧：侧栏导航在 /app/chat 上仍然可达。
  await expect(page.locator('.sidebar')).toHaveCount(1)
})

test('交付前先确认：工作区 /app 仍是原概览，没被门户改动覆盖', async ({ page }) => {
  await installApiStubs(page, {
    authenticated: true,
    extra: { 'GET /news': { body: NEWS_EMPTY } },
  })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/app')
  await waitForRendered(page, '.workspace')

  expect(new URL(page.url()).pathname).toBe('/app')
  await expect(page.getByText('快捷开始')).toBeVisible()
  // 门户的空态文案不该出现在工作区概览里。
  await expect(page.getByText('新闻源尚未接入')).toHaveCount(0)
})

/** F2 桩数据：真实形状——WHO 同一场疫情的多期更新（前两期标题逐字相同）+ 来源级状态。 */
const WHO_BASE = 'https://www.who.int/emergencies/disease-outbreak-news/item'
const WHO_TITLE = 'Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo'
const NEWS_READY = {
  category: 'disease',
  status: 'ready',
  asOf: '2026-10-04T16:04:47Z',
  nextRefreshAt: '2026-10-04T20:00:00Z',
  total: 3,
  hasMore: false,
  items: [
    {
      id: 'a',
      category: 'disease',
      title: WHO_TITLE,
      summary: null,
      sourceName: 'WHO 疾病暴发新闻',
      canonicalUrl: `${WHO_BASE}/2026-DON618`,
      publishedAt: '2026-09-25T15:16:26Z',
      retrievedAt: '2026-10-04T16:04:47Z',
      medicalReviewed: false,
    },
    {
      id: 'b',
      category: 'disease',
      title: WHO_TITLE,
      summary: null,
      sourceName: 'WHO 疾病暴发新闻',
      canonicalUrl: `${WHO_BASE}/2026-DON617`,
      publishedAt: '2026-09-10T08:16:08Z',
      retrievedAt: '2026-10-04T16:04:47Z',
      medicalReviewed: false,
    },
    {
      id: 'c',
      category: 'disease',
      title: 'Cholera - Haiti',
      summary: null,
      sourceName: 'WHO 疾病暴发新闻',
      canonicalUrl: `${WHO_BASE}/2026-DON614`,
      publishedAt: '2026-08-01T10:13:28Z',
      retrievedAt: '2026-10-04T16:04:47Z',
      medicalReviewed: false,
    },
  ],
  tips: [],
  sourceStatuses: [
    {
      id: 'who_disease_outbreak_news',
      name: 'WHO 疾病暴发新闻',
      status: 'ready',
      lastSuccessAt: '2026-10-04T16:04:47Z',
      lastErrorCode: null,
    },
  ],
}

for (const width of [1280, 375]) {
  test(`F2 ${width}px：同题多期折成一组、标出期号与来源状态，且不横向溢出`, async ({ page }) => {
    await installApiStubs(page, { authenticated: true, extra: { 'GET /news': { body: NEWS_READY } } })

    await page.setViewportSize({ width, height: width === 375 ? 720 : 800 })
    await page.goto('/portal')
    await waitForRendered(page, '.portal')

    // 3 条 → 2 张卡（同题两条折成一组），并标出期号与较早更新。
    await expect(page.locator('.cards > li')).toHaveCount(2)
    await expect(page.getByText('同题更新 2 期')).toBeVisible()
    await expect(page.getByText('DON618（2026）')).toBeVisible()
    await expect(page.getByText('另有 1 期较早更新')).toBeVisible()
    await expect(page.getByText('WHO 疾病暴发新闻：正常')).toBeVisible()
    await expect(page.getByText('未经医学审核').first()).toBeVisible()
    await expect(page.getByText('新闻源尚未接入')).toHaveCount(0)
    // 每条都必须指向来源原文，不能出现自造内容。
    await expect(page.locator('.cards a').first()).toHaveAttribute('href', /who\.int/)

    const report = await measureOverflow(page)
    expect(report.overflow, describeOverflow(report, '/portal', width)).toBeLessThanOrEqual(1)
  })
}

test('F2：点卡片标题能打开来源原文（新标签），且标题链接指向来源域名', async ({ page, context }) => {
  // 拦截真实外网：只验证「点得开、开的是来源地址」，不依赖 WHO 可达性。
  await context.route('**://www.who.int/**', route => route.fulfill({ body: 'stub', contentType: 'text/html' }))
  await installApiStubs(page, { authenticated: true, extra: { 'GET /news': { body: NEWS_READY } } })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/portal')
  await waitForRendered(page, '.portal')

  const title = page.locator('.cards > li').first().locator('a.card-title')
  await expect(title).toHaveAttribute('href', /who\.int/)

  const href = await title.getAttribute('href')

  const [popup] = await Promise.all([context.waitForEvent('page'), title.click()])
  // 等导航真正落到来源地址：只等 domcontentloaded 时 url 可能还是 about:blank。
  await popup.waitForURL(/who\.int/)
  // 打开的就是卡片上写的来源地址，不多不少。
  expect(popup.url(), `实际打开的地址是 ${popup.url()}`).toBe(href)
  await popup.close()
})