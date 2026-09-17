import { expect, test } from '@playwright/test'
import { describeOverflow, installApiStubs, measureOverflow, settle } from './support'

/**
 * 横向溢出检查。
 *
 * 重要前提（别把它当漏测）：应用工作区 `.workspace` 带 `min-width: 1000px`，
 * 是**桌面优先**的有意设计。所以在 375px 手机宽度下 `/app/*` 必然横向溢出——
 * 这属于产品范围问题（要不要支持移动端），不是本套件能判定的缺陷。因此：
 *   - 桌面 1280px：所有路由都必须无横向溢出；
 *   - 手机 375px：只验收确实做了移动端适配的 /login 与 /register；
 *   - 另有一条用例把「1000px 约束」固定下来，一旦开始做移动端适配就会失败提醒。
 *
 * 另一个坑：采集说明弹窗会锁住 body 滚动，从而**掩盖**横向溢出。所以这里统一用
 * `noticeSeen: true` 不弹窗，否则测量结果会随弹窗打开时机时好时坏。
 */

const ROUTE_NAMES: Record<string, string> = {
  '/login': '登录',
  '/register': '注册',
  '/app': '首页',
  '/app/chat': '智能咨询',
  '/app/history': '咨询历史',
  '/app/profile': '个人中心',
  '/app/health-records': '健康记录',
}

/** 未登录访客能访问、且已做移动端适配的页面。 */
const MOBILE_ROUTES = ['/login', '/register']

const MATRIX = [
  ...Object.keys(ROUTE_NAMES).map(path => ({ path, width: 1280, label: '桌面' })),
  ...MOBILE_ROUTES.map(path => ({ path, width: 375, label: '手机' })),
]

for (const item of MATRIX) {
  test(`${item.label} ${item.width}px：${ROUTE_NAMES[item.path]} ${item.path} 无横向溢出`, async ({ page }) => {
    const authenticated = !['/login', '/register'].includes(item.path)
    await installApiStubs(page, { authenticated })

    await page.setViewportSize({ width: item.width, height: item.width === 375 ? 720 : 800 })
    await page.goto(item.path)
    await settle(page)

    // 先确认没被重定向，否则溢出检查可能是在测另一个页面。
    const landed = new URL(page.url()).pathname
    expect(landed, `${item.path} 被重定向到了 ${landed}`).toBe(item.path)

    const report = await measureOverflow(page)
    expect(
      report.overflow,
      describeOverflow(report, item.path, item.width),
    ).toBeLessThanOrEqual(1)
  })
}

test('移动端：记录工作区 1000px 桌面优先约束（已知范围问题，非缺陷）', async ({ page }) => {
  await installApiStubs(page)
  await page.setViewportSize({ width: 375, height: 720 })
  await page.goto('/app')
  await settle(page)

  const report = await measureOverflow(page)
  console.log(
    `[e2e] 375px 下工作区实际宽 ${report.scrollWidth}px、横向溢出 ${report.overflow}px；`
    + `越界元素：${report.offenders.map(item => `${item.label}(${item.right}px)`).join('；')}`,
  )

  // 把当前约束写成断言：一旦有人开始做移动端适配，这里会失败，提醒同步更新
  // frontend/BROWSER_ACCEPTANCE.md 与产品范围结论，而不是让约束悄悄变化。
  expect(
    report.scrollWidth,
    '工作区宽度应来自 .workspace 的 min-width: 1000px；若已变化，请先确认移动端是否已纳入范围',
  ).toBe(1000)
})