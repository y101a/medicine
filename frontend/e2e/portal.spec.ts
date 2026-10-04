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