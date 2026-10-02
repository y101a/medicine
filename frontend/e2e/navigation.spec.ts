import { expect, test } from '@playwright/test'
import { installApiStubs, settle } from './support'

/**
 * 附近医院导航的定位降级。
 *
 * 报告里说「定位失败」，但 jsdom 里 geolocation 是假的，5 条降级分支测不到真实行为。
 * 这里在页面里替换 `getCurrentPosition`，**确定性地**触发各个失败分支，
 * 验证每一种都会给出中文说明并自动切到城市/区县查询。
 */

interface FailureCase {
  code: number
  expected: string
  label: string
}

const FAILURE_CASES: FailureCase[] = [
  { code: 1, expected: '定位权限被拒绝', label: '权限被拒绝' },
  { code: 2, expected: '无法提供位置', label: '设备无法定位' },
  { code: 3, expected: '获取位置超时', label: '定位超时' },
]

const DIALOG = '附近医院导航'

async function openNavigator(page: import('@playwright/test').Page) {
  await page.goto('/app/chat')
  await settle(page)
  // 入口 2026-10-02 已按用户要求从输入框移到右上角账号菜单（Codex 提交 `0ca7a5e`）。
  await page.locator('.user-menu').click()
  await page.locator('.navigator-menu-item').click()
  await expect(page.locator('.el-dialog', { hasText: DIALOG })).toBeVisible()
}

test('账号菜单里的导航入口在申请定位前先说明用途', async ({ page }) => {
  await installApiStubs(page)
  await page.goto('/app/chat')
  await settle(page)

  // 输入框里的旧触发器已隐藏：全页只剩账号菜单这一个入口。
  await expect(page.locator('.composer-bottom .navigator-trigger'), '输入框里不该再出现导航入口').toBeHidden()
  await page.locator('.user-menu').click()
  const item = page.locator('.navigator-menu-item')
  await expect(item, '账号菜单里应有「附近医院导航」').toBeVisible()
  await expect(item).toContainText('附近医院导航')
  await item.click()

  // 隐私说明必须在**申请定位之前**就出现，而不是等用户点了定位才补上。
  const consent = page.locator('.location-consent p')
  await expect(consent, '申请定位前必须先说明用途').toContainText('坐标仅在本次请求内存中使用')
  await expect(consent, '必须说明不落库不写日志').toContainText('不会保存')
})

async function failGeolocation(
  page: import('@playwright/test').Page,
  code: number,
): Promise<void> {
  await page.addInitScript((failureCode: number) => {
    navigator.geolocation.getCurrentPosition = (
      _success: PositionCallback,
      failure?: PositionErrorCallback | null,
    ) => {
      failure?.({
        code: failureCode,
        message: 'e2e 注入的定位失败',
        PERMISSION_DENIED: 1,
        POSITION_UNAVAILABLE: 2,
        TIMEOUT: 3,
      } as GeolocationPositionError)
    }
  }, code)
}

for (const item of FAILURE_CASES) {
  test(`定位${item.label}：给出中文说明并切到城市/区县查询`, async ({ page }) => {
    await installApiStubs(page)
    await failGeolocation(page, item.code)
    await openNavigator(page)

    await page.locator('.locate-button').click()

    const fallback = page.locator('.area-fallback')
    await expect(fallback, `定位失败后应该切到城市/区县查询`).toBeVisible()

    const notice = await page.locator('.fallback-title').innerText()
    console.log(`[e2e] code=${item.code} 降级说明：${notice}`)

    expect(notice, `降级说明应该说明原因，实际为「${notice}」`).toContain(item.expected)
    expect(notice, '降级说明必须是中文').toMatch(/[\u4e00-\u9fa5]/)
    // 降级说明是用户可见文案，不得夹带原始报文。
    expect(notice, `降级说明疑似夹带原始报文：${notice}`).not.toMatch(/[{}[\]<>]/)
  })
}

test('降级后仍可用城市查询并列出医院', async ({ page }) => {
  await installApiStubs(page)
  await openNavigator(page)

  // 「不使用定位」这条路径不需要浏览器权限，是最稳的降级入口。
  await page.getByRole('button', { name: '不使用定位' }).click()
  await expect(page.locator('.area-fallback')).toBeVisible()

  await page.getByLabel('城市或行政区编码').fill('北京')
  await page.getByRole('button', { name: '查询医院' }).click()

  const firstCard = page.locator('.hospital-card').first()
  await expect(firstCard, '城市查询后应该列出医院').toBeVisible()
  await expect(firstCard).toContainText('示例市第一医院')
  await expect(firstCard.getByRole('link', { name: '打开高德导航' })).toBeVisible()
})
