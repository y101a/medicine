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

test('1280px：四个分区平铺在 AI 展示区下方并铺满整行', async ({ page }) => {
  await installApiStubs(page, {
    authenticated: true,
    extra: { 'GET /news': { body: NEWS_EMPTY } },
  })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/portal')
  await waitForRendered(page, '.portal')

  const tiles = page.locator('.category-tile')
  await expect(tiles).toHaveCount(4)

  const heroBox = await page.locator('.hero').boundingBox()
  const first = await tiles.nth(0).boundingBox()
  const last = await tiles.nth(3).boundingBox()
  expect(first, '没有找到分区卡片 .category-tile').not.toBeNull()

  // 平铺在 AI 展示区下面
  expect(first!.y, '分区应排在 AI 展示区下方').toBeGreaterThanOrEqual(heroBox!.y + heroBox!.height - 1)
  // 同一行四块，每块都够大，并铺满内容区整行
  expect(Math.abs(last!.y - first!.y), '四块应在同一行').toBeLessThan(2)
  expect(first!.width, '分区卡片应放大到至少 200px 宽').toBeGreaterThanOrEqual(200)
  const gridWidth = await page.locator('.categories').evaluate(el => el.getBoundingClientRect().width)
  const rowWidth = last!.x + last!.width - first!.x
  expect(rowWidth / gridWidth, '四块应铺满整行').toBeGreaterThan(0.98)
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