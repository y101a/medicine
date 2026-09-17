import { expect, test } from '@playwright/test'
import { installApiStubs, settle } from './support'

/**
 * 「接口异常时把原始 JSON 显示给用户」的回归。
 *
 * 单测断言的是 `getApiErrorMessage` 的返回值；这里断言**真实界面上的文字**，
 * 覆盖从 axios 拦截器到渲染的完整链路，两者缺一不可。
 *
 * 注意：断言的是「预期文案必须出现」，而不是「某个提示不含大括号」。
 * 后者会因为页面上另有别的提示（例如会话过期提示）而假通过——
 * 第一版就是这么写的，实测发现它通过的原因并不是我测的那条路径。
 */

const FASTAPI_DETAIL = {
  detail: [
    { loc: ['body', 'username'], msg: 'field required', type: 'value_error.missing' },
  ],
}

interface ErrorCase {
  name: string
  body: unknown
  expected: string
}

const LOGIN_CASES: ErrorCase[] = [
  {
    name: '只有 FastAPI 的 detail 数组（没有 message 字段）',
    body: FASTAPI_DETAIL,
    expected: '服务器暂时无法处理请求',
  },
  {
    name: 'message 字段被塞进 JSON 片段',
    body: { message: '{"detail":[{"msg":"field required"}]}' },
    expected: '服务器暂时无法处理请求',
  },
  {
    name: 'message 字段被塞进 HTML 错误页',
    body: { message: '<html><body>502 Bad Gateway</body></html>' },
    expected: '服务器暂时无法处理请求',
  },
  {
    name: 'message 是正常中文短句（应原样显示，不要过度过滤）',
    body: { message: '用户名或密码不正确' },
    expected: '用户名或密码不正确',
  },
]

for (const item of LOGIN_CASES) {
  test(`登录失败提示：${item.name}`, async ({ page }) => {
    await installApiStubs(page, {
      authenticated: false,
      extra: { 'POST /auth/login': { status: 500, body: item.body } },
    })

    let loginRequests = 0
    page.on('request', (request) => {
      if (request.url().includes('/auth/login')) loginRequests += 1
    })

    await page.goto('/login')
    await settle(page)

    // 用户名有 4–20 字符的前端校验：填 'e2e' 会被表单挡下，请求根本发不出去。
    await page.getByPlaceholder('请输入用户名').fill('e2e-user')
    await page.getByPlaceholder('请输入密码').fill('e2e-wrong-password')
    await page.locator('button[type="submit"]').first().click()

    const toasts = page.locator('.el-message')
    await expect(toasts.first(), '登录失败应该给出提示').toBeVisible()

    // 诊断日志必须放在断言之前：断言失败后这行就执行不到了，
    // 而失败时恰恰最需要知道「请求发了几次、页面究竟显示了什么」。
    const texts = await toasts.allInnerTexts()
    console.log(
      `[e2e] ${item.name} -> 页面提示：${texts.join(' | ')}（登录请求 ${loginRequests} 次）`,
    )
    expect(
      loginRequests,
      '应该真的发起了登录请求；为 0 通常说明提交被前端表单校验挡下了',
    ).toBeGreaterThan(0)

    await expect(
      page.locator('.el-message', { hasText: item.expected }),
      `应出现提示「${item.expected}」`,
    ).toBeVisible()

    for (const text of texts) {
      expect(text, `提示里出现了结构化内容：${text}`).not.toMatch(/[{}[\]<>]/)
    }
  })
}

test('导航接口返回结构化报文时，错误提示不出现原始 JSON', async ({ page }) => {
  await installApiStubs(page, {
    extra: { 'POST /navigation/hospitals-by-area': { status: 500, body: FASTAPI_DETAIL } },
  })

  await page.goto('/app/chat')
  await settle(page)
  await page.locator('.navigator-trigger').click()
  await page.getByRole('button', { name: '不使用定位' }).click()
  await page.getByLabel('城市或行政区编码').fill('北京')
  await page.getByRole('button', { name: '查询医院' }).click()

  const errorTitle = page.locator('.navigation-error .el-alert__title')
  await expect(errorTitle, '接口失败应该给出错误提示').toBeVisible()
  await expect(errorTitle, '应显示 500 对应的中文文案').toHaveText('服务器暂时无法处理请求')

  const text = (await errorTitle.innerText()).trim()
  console.log(`[e2e] 导航失败提示：${text}`)
  expect(text, `提示里出现了结构化内容：${text}`).not.toMatch(/[{}[\]<>]/)
})