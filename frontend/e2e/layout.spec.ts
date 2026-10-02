import { expect, test } from '@playwright/test'
import { describeOverflow, installApiStubs, measureOverflow, waitForRendered } from './support'

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
  '/app/settings': '设置',
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
    await waitForRendered(page)

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

test('旧路径重定向到设置页的对应分栏', async ({ page }) => {
  await installApiStubs(page)
  await page.setViewportSize({ width: 1280, height: 800 })

  await page.goto('/app/health-records')
  await waitForRendered(page)
  // 重定向本身必须断言：只看内容的话，万一重定向失效、旧路由仍渲染着页面，测试会照旧通过。
  expect(new URL(page.url()).pathname, '/app/health-records 应重定向到 /app/settings').toBe('/app/settings')
  expect(page.url(), '重定向应带上 tab=health').toContain('tab=health')
  await expect(page.locator('.health-records__title')).toBeVisible()

  await page.goto('/app/profile')
  await waitForRendered(page)
  expect(new URL(page.url()).pathname, '/app/profile 应重定向到 /app/settings').toBe('/app/settings')
  await expect(page.locator('#profile-title')).toBeVisible()
})

test('右上角账号菜单提供附近医院导航，并保留定位说明', async ({ page }) => {
  await installApiStubs(page)
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/app/chat')
  await waitForRendered(page)

  await page.locator('.user-menu').click()
  const menuItem = page.locator('.navigator-menu-item')
  await expect(menuItem).toBeVisible()
  await expect(menuItem).toContainText('附近医院导航')
  await menuItem.click()

  const dialog = page.getByRole('dialog', { name: '附近医院导航' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('坐标仅在本次请求内存中使用')
  await expect(page.locator('.composer-bottom .navigator-trigger')).toBeHidden()
})

test('智能咨询隐藏页面级滚动条，只保留消息区域滚动条', async ({ page }) => {
  await installApiStubs(page)
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/app/chat')
  await waitForRendered(page)

  const outerScrollStyle = await page.locator('.workspace-content').evaluate(element => {
    const style = getComputedStyle(element)
    return { overflowY: style.overflowY, scrollbarWidth: style.scrollbarWidth }
  })
  const conversationOverflow = await page.locator('.conversation').evaluate(element => getComputedStyle(element).overflowY)

  expect(outerScrollStyle.overflowY, '工作区内容仍应可通过滚轮滚动').toBe('auto')
  expect(outerScrollStyle.scrollbarWidth, '最右侧页面级滚动条应隐藏').toBe('none')
  expect(conversationOverflow, '对话消息区域应保留独立滚动').toBe('auto')
})

test('移动端：记录工作区 1000px 桌面优先约束（已知范围问题，非缺陷）', async ({ page }) => {
  await installApiStubs(page)
  await page.setViewportSize({ width: 375, height: 720 })
  await page.goto('/app')
  await waitForRendered(page)

  // 先确认测的确实是工作区页面：曾经出现过工作区还没渲染就测量、得到
  // 「无横向溢出」这种假结论的情况，所以「测对了页面」本身也要断言。
  const landed = new URL(page.url()).pathname
  expect(landed, `/app 被重定向到了 ${landed}，本次测量无效`).toBe('/app')

  const workspaceCount = await page.locator('.workspace').count()
  const workspaceWidth = workspaceCount
    ? await page.locator('.workspace').evaluate(element => Math.round(element.getBoundingClientRect().width))
    : 0

  const report = await measureOverflow(page)
  console.log(
    `[e2e] 375px：.workspace 共 ${workspaceCount} 个、宽 ${workspaceWidth}px；`
    + `documentElement.scrollWidth ${report.scrollWidth}px、横向溢出 ${report.overflow}px；`
    + `越界元素：${report.offenders.map(item => `${item.label}(${item.right}px)`).join('；') || '无'}`,
  )

  expect(workspaceCount, '工作区应当已渲染；为 0 说明本页不是工作区页面').toBeGreaterThan(0)

  // 把当前约束写成断言：一旦有人开始做移动端适配，这里会失败，提醒同步更新
  // frontend/BROWSER_ACCEPTANCE.md 与产品范围结论，而不是让约束悄悄变化。
  expect(
    report.scrollWidth,
    '工作区宽度应来自 .workspace 的 min-width: 1000px；若已变化，请先确认移动端是否已纳入范围',
  ).toBe(1000)
})

test('窄屏 375px：明确提示需要宽屏，而不是让界面默默横向撑开', async ({ page }) => {
  await installApiStubs(page)
  await page.setViewportSize({ width: 375, height: 720 })
  await page.goto('/app')
  await waitForRendered(page)

  const hint = page.locator('.viewport-hint')
  await hint.waitFor({ state: 'attached' })

  // 先把浏览器的实际计算样式打出来再断言——见 error-text.spec.ts 里的同类教训：
  // 日志放在断言之后，失败时就什么都看不到。
  const diagnosis = await hint.evaluate((element) => {
    const style = getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return {
      display: style.display,
      position: style.position,
      visibility: style.visibility,
      rect: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      innerWidth: window.innerWidth,
      matchesNarrowMedia: window.matchMedia('(max-width: 999px)').matches,
    }
  })
  console.log(`[e2e] 窄屏提示诊断：${JSON.stringify(diagnosis)}`)

  await expect(hint, '窄屏下必须给出明确的宽屏提示').toBeVisible()
  await expect(hint).toContainText('1000')

  // 提示是窄屏下唯一该完整可见的东西：它必须落在视口内。
  // 若它被 .workspace 的 min-width 撑开（例如误用了 absolute 或被 transform 祖先影响），
  // 这里就会失败。
  const box = await hint.boundingBox()
  expect(box, '窄屏提示应该有布局盒').not.toBeNull()
  const right = Math.round(box!.x + box!.width)
  console.log(`[e2e] 窄屏提示坐标：left=${Math.round(box!.x)} right=${right} width=${Math.round(box!.width)}`)
  expect(right, `窄屏提示右边界 ${right}px 超出 375px 视口`).toBeLessThanOrEqual(376)
})

test('桌面 1280px：不显示窄屏提示', async ({ page }) => {
  await installApiStubs(page)
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/app')
  await waitForRendered(page)
  await expect(page.locator('.viewport-hint'), '宽屏下不应出现窄屏提示').toBeHidden()
})

test('登录页在窄屏下不显示工作区提示（该页已做移动端适配）', async ({ page }) => {
  await installApiStubs(page, { authenticated: false })
  await page.setViewportSize({ width: 375, height: 720 })
  await page.goto('/login')
  await waitForRendered(page)
  await expect(page.locator('.viewport-hint'), '登录页不该出现工作区提示').toBeHidden()
})
