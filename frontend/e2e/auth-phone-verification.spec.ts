import { expect, test, type Page } from '@playwright/test'
import {
  MOCK_USER,
  installApiStubs,
  measureOverflow,
  describeOverflow,
  settle,
  waitForRendered,
  type StubTable,
} from './support'

/**
 * 模拟短信、注册手机号验证与短信找回密码的前端验收。
 *
 * 契约来源：根目录 `SMS_VERIFICATION_PLAN.md` 第 5、6、11、13.2 节。
 *
 * 边界：这里**不碰后端、不碰数据库**，`/api/v1/**` 全部由 `page.route` 拦截，
 * 所以它验证的是「前端拿到某种响应后渲染成什么样、发了什么请求」。
 * 真实短信链路（终端打印验证码、限流跨进程共享、重置后旧令牌失效）属于后端联调，本文件不作断言。
 */
const PHONE = '13800138000'
const MASKED_PHONE = '138****8000'
const ID_CARD = '11010519491231002X'
const CODE_REQUEST = { challengeId: 'c-e2e', expiresInSeconds: 300, resendAfterSeconds: 60 }
const GRANT = { verificationToken: 'grant-e2e', expiresInSeconds: 600 }
const RESET_SENT_TEXT = '如果该手机号已绑定并完成验证，验证码将发送到该手机。'

function stubs(overrides: StubTable = {}): StubTable {
  return {
    'POST /auth/phone-verifications/code': { status: 202, body: CODE_REQUEST },
    'POST /auth/phone-verifications/verify': { body: GRANT },
    'POST /auth/register': { body: { user: { ...MOCK_USER, phoneVerified: true } } },
    'POST /auth/password-reset': { status: 204, body: '' },
    'POST /users/me/phone-verification/code': { status: 202, body: CODE_REQUEST },
    'POST /users/me/phone-verification/confirm': { status: 204, body: '' },
    'GET /users/me/avatar': { status: 404, body: {} },
    ...overrides,
  }
}

interface Captured {
  entries: string[]
  code: unknown[]
  verify: unknown[]
  register: unknown[]
  reset: unknown[]
  confirm: unknown[]
}

/** 记下前端真正发出的请求与请求体——「跳过 /stream」那类断言全靠它。 */
function capture(page: Page): Captured {
  const captured: Captured = {
    entries: [],
    code: [],
    verify: [],
    register: [],
    reset: [],
    confirm: [],
  }

  page.on('request', (request) => {
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/v1/')) return
    const entry = `${request.method()} ${url.pathname.replace('/api/v1', '')}`
    captured.entries.push(entry)

    const body = request.postData() ?? ''
    const target = {
      'POST /auth/phone-verifications/code': captured.code,
      'POST /auth/phone-verifications/verify': captured.verify,
      'POST /auth/register': captured.register,
      'POST /auth/password-reset': captured.reset,
      'POST /users/me/phone-verification/confirm': captured.confirm,
    }[entry]
    if (target) target.push(JSON.parse(body || '{}'))
  })

  return captured
}

async function openRegister(page: Page) {
  await page.goto('/register')
  await settle(page)
  await waitForRendered(page, '.register-card')
}

async function fillRegisterForm(page: Page) {
  await page.locator('.username-input input').fill('e2e-authed')
  await page.locator('.realname-input input').fill('端到端验收')
  await page.locator('.phone-input input').fill(PHONE)
  await page.locator('.id-card-input input').fill(ID_CARD)
  await page.locator('.gender-select').click()
  await page.locator('.el-select-dropdown__item').filter({ hasText: '男' }).first().click()
  await page.locator('.password-input input').fill('e2e-password-1')
  await page.locator('.confirm-password-input input').fill('e2e-password-1')
}

async function requestRegisterCode(page: Page) {
  await page.locator('.send-code-button').click()
  await expect(page.locator('.send-code-button')).toContainText('秒后可重发')
}

async function expectCardFitsViewport(page: Page, selector: string, label: string) {
  const box = await page.locator(selector).boundingBox()
  expect(box, `${label} 应有可见的卡片`).not.toBeNull()
  const right = Math.round(box!.x + box!.width)
  expect(right, `${label} 右边界 ${right}px 超出 375px 视口（宽 ${Math.round(box!.width)}px）`)
    .toBeLessThanOrEqual(376)
  const report = await measureOverflow(page)
  expect(report.overflow, describeOverflow(report, label, 375)).toBeLessThanOrEqual(1)
}

test.describe('注册手机号验证', () => {
  test('验证码通过后才允许创建账户，注册请求带上一次性令牌', async ({ page }) => {
    await installApiStubs(page, { authenticated: false, extra: stubs() })
    const captured = capture(page)
    await openRegister(page)
    await fillRegisterForm(page)

    const submit = page.locator('.register-button')
    await expect(submit, '还没验证手机号时不能提交').toBeDisabled()
    await submit.click({ force: true })
    expect(captured.register, '未验证就点了提交，不该发出注册请求').toHaveLength(0)

    await requestRegisterCode(page)
    expect(captured.code, '获取验证码要带上用途').toEqual([
      { phone: PHONE, purpose: 'registration' },
    ])

    await page.locator('.code-input input').fill('482731')
    await page.locator('.verify-code-button').click()
    await expect(page.getByText('手机号已通过短信验证')).toBeVisible()
    expect(captured.verify[0], '校验请求只带 challengeId 与验证码').toEqual({
      challengeId: 'c-e2e',
      code: '482731',
    })

    await expect(submit, '验证通过后才可以创建账户').toBeEnabled()
    await submit.click()
    await expect.poll(() => captured.register.length, { message: '应发出一次注册请求' }).toBe(1)
    expect(captured.register[0]).toMatchObject({
      phone: PHONE,
      username: 'e2e-authed',
      phoneVerificationToken: 'grant-e2e',
    })
    await page.waitForURL('**/login')
  })

  test('验证码错误只显示受控中文文案，且仍然不能提交', async ({ page }) => {
    await installApiStubs(page, {
      authenticated: false,
      extra: stubs({
        'POST /auth/phone-verifications/verify': {
          status: 422,
          body: { code: 'SMS_CODE_INVALID', message: '提交的信息校验未通过' },
        },
      }),
    })
    const captured = capture(page)
    await openRegister(page)
    await fillRegisterForm(page)
    await requestRegisterCode(page)

    await page.locator('.code-input input').fill('000000')
    await page.locator('.verify-code-button').click()

    await expect(page.getByText('验证码不正确，请检查后重试')).toBeVisible()
    await expect(page.locator('.code-hint--ok')).toHaveCount(0)
    await expect(page.locator('.register-button')).toBeDisabled()
    expect(captured.register).toHaveLength(0)
  })

  test('验证码过期后退回「重新获取」，输入框重新禁用', async ({ page }) => {
    await installApiStubs(page, {
      authenticated: false,
      extra: stubs({
        'POST /auth/phone-verifications/verify': {
          status: 422,
          body: { code: 'SMS_CODE_EXPIRED', message: '提交的信息校验未通过' },
        },
      }),
    })
    await openRegister(page)
    await fillRegisterForm(page)
    await requestRegisterCode(page)

    await page.locator('.code-input input').fill('482731')
    await page.locator('.verify-code-button').click()

    await expect(page.getByText('验证码已过期，请重新获取')).toBeVisible()
    await expect(page.locator('.code-input input')).toBeDisabled()
    await expect(page.locator('.code-hint')).toHaveCount(0)
    await expect(page.locator('.send-code-button')).toBeEnabled()
  })

  test('被限流时用服务端给的剩余秒数提示，并按该秒数开始倒计时', async ({ page }) => {
    await installApiStubs(page, {
      authenticated: false,
      extra: stubs({
        'POST /auth/phone-verifications/code': {
          status: 429,
          body: {
            code: 'SMS_RATE_LIMITED',
            message: '请求过于频繁，请稍后再试',
            details: { retryAfterSeconds: 42 },
          },
        },
      }),
    })
    await openRegister(page)
    await page.locator('.phone-input input').fill(PHONE)

    await page.locator('.send-code-button').click()

    await expect(page.getByText('发送过于频繁，请 42 秒后重试')).toBeVisible()
    await expect(page.locator('.send-code-button')).toContainText('42 秒后可重发')
    await expect(page.locator('.code-input input')).toBeDisabled()
  })
})

test.describe('短信找回密码', () => {
  test('发送后只显示统一文案；换个手机号与返回登录都算取消', async ({ page }) => {
    await installApiStubs(page, { authenticated: false, extra: stubs() })
    await page.goto('/forgot-password')
    await settle(page)
    await waitForRendered(page, '.forgot-card')

    await page.locator('.phone-input input').fill(PHONE)
    await page.locator('.send-code-button').click()

    await expect(page.locator('.reset-notice')).toHaveText(RESET_SENT_TEXT)
    const body = await page.locator('body').innerText()
    for (const leak of ['不存在', '未注册', '未验证']) {
      expect(body, `找回流程不得出现「${leak}」，那是账户枚举线索`).not.toContain(leak)
    }

    await page.locator('.back-to-phone-button').click()
    await expect(page.locator('.phone-input')).toBeVisible()
    await expect(page.locator('.reset-notice')).toHaveCount(0)

    await page.locator('.back-button').click()
    await page.waitForURL('**/login')
  })

  test('三步走完：验证码换令牌 → 重设密码 → 回登录页提示用新密码登录', async ({ page }) => {
    await installApiStubs(page, { authenticated: false, extra: stubs() })
    const captured = capture(page)
    await page.goto('/forgot-password')
    await settle(page)
    await waitForRendered(page, '.forgot-card')

    await page.locator('.phone-input input').fill(PHONE)
    await page.locator('.send-code-button').click()
    await expect(page.locator('.code-input')).toBeVisible()

    await page.locator('.code-input input').fill('482731')
    await page.locator('.verify-code-button').click()
    await expect(page.locator('.password-input')).toBeVisible()

    await page.locator('.password-input input').fill('e2e-new-password')
    await page.locator('.confirm-password-input input').fill('e2e-new-password')
    await page.locator('.reset-button').click()

    await expect.poll(() => captured.reset.length, { message: '应发出一次重置请求' }).toBe(1)
    expect(captured.reset[0]).toEqual({
      phone: PHONE,
      verificationToken: 'grant-e2e',
      newPassword: 'e2e-new-password',
    })
    await page.waitForURL('**/login?reason=password-reset')
    await expect(page.getByText('密码已重置，请使用新密码登录')).toBeVisible()
  })
})

test.describe('老用户补验证', () => {
  test('设置页显示补验证入口且只给脱敏号码，验证成功后入口消失', async ({ page }) => {
    await installApiStubs(page, {
      authenticated: true,
      extra: stubs({
        'GET /users/me': { body: { ...MOCK_USER, phoneMasked: MASKED_PHONE, phoneVerified: false } },
      }),
    })
    const captured = capture(page)
    await page.goto('/app/settings')
    await settle(page)
    await waitForRendered(page, '.settings')

    await expect(page.getByText('验证当前手机号')).toBeVisible()
    await expect(page.getByText(MASKED_PHONE).first()).toBeVisible()
    expect(await page.locator('body').innerText(), '界面上不得出现完整手机号')
      .not.toContain(PHONE)

    await page.locator('.phone-verification__request').click()
    await expect(page.locator('.phone-verification__hint')).toBeVisible()
    await page.locator('.phone-verification__code input').fill('482731')
    await page.locator('.phone-verification__confirm').click()

    await expect.poll(() => captured.confirm.length, { message: '应发出一次补验证确认' }).toBe(1)
    expect(captured.confirm[0]).toEqual({ challengeId: 'c-e2e', code: '482731' })
    await expect(page.locator('.phone-verification')).toHaveCount(0)
    await expect(page.getByText('手机号验证完成')).toBeVisible()
    expect(captured.entries).toContain('POST /users/me/phone-verification/code')
  })
})

test.describe('窄屏可用性', () => {
  test('375px：注册页与找回页卡片落在视口内，关键按钮可见可点', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await installApiStubs(page, { authenticated: false, extra: stubs() })

    await openRegister(page)
    await expectCardFitsViewport(page, '.register-card', '注册页')
    await expect(page.locator('.phone-input input')).toBeVisible()
    await expect(page.locator('.send-code-button')).toBeVisible()
    await expect(page.locator('.register-button')).toBeVisible()

    await page.goto('/forgot-password')
    await settle(page)
    await waitForRendered(page, '.forgot-card')
    await expectCardFitsViewport(page, '.forgot-card', '找回密码页')
    await expect(page.locator('.send-code-button')).toBeVisible()
    await expect(page.locator('.back-button')).toBeVisible()
  })
})