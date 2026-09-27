import { expect, test } from '@playwright/test'
import { MOCK_USER, installApiStubs, settle, waitForRendered, type StubTable } from './support'

/**
 * 设置页「模型与密钥」分栏的浏览器验收。
 *
 * 只验证「前端拿到某种响应后渲染成什么样」，接口全部由 `page.route` 拦截；
 * 真实密钥联调（真 Key 打真服务商）不在这一层范围内，那是后端的验证路径。
 */
test.describe('设置页 · 模型与密钥', () => {
  test('列出四家服务商，并披露数据流向与脱敏限度', async ({ page }) => {
    await installApiStubs(page)
    await page.goto('/app/settings?tab=credentials')
    await waitForRendered(page, '.credentials')
    await settle(page, 300)

    for (const name of ['DeepSeek', '阿里云百炼', 'Kimi', '智谱 AI']) {
      const row = page.locator('.credentials__item', { hasText: name })
      await expect(row).toBeVisible()
      await expect(row).toContainText('未配置')
    }

    const notice = page.locator('.credentials__notice')
    await expect(notice).toContainText('会发送到该服务商')
    await expect(notice).toContainText('不等于健康文本已经匿名化')
    await expect(notice).toContainText('不作诊断、不替代医生')
  })

  test('填入 API Key 并保存后只显示掩码，明文输入框消失', async ({ page }) => {
    await installApiStubs(page)
    await page.goto('/app/settings?tab=credentials')
    await waitForRendered(page, '.credentials')

    const row = page.locator('.credentials__item', { hasText: 'DeepSeek' })
    await row.getByRole('button', { name: '填入 API Key' }).click()
    await row.locator('input').fill('sk-e2e-1234567890')
    await row.getByRole('button', { name: '验证并保存' }).click()

    await expect(row).toContainText('已配置 · sk-…4f2a')
    await expect(row.locator('input')).toHaveCount(0)
  })

  test('Key 被服务商拒绝时给出可读原因，且状态不变成已配置', async ({ page }) => {
    await installApiStubs(page, {
      extra: {
        'PUT /users/me/model-credentials/*': {
          status: 422,
          body: {
            code: 'MODEL_CREDENTIAL_INVALID',
            message: 'API Key 无效、无权限或当前不可用',
          },
        },
      },
    })
    await page.goto('/app/settings?tab=credentials')
    await waitForRendered(page, '.credentials')

    const row = page.locator('.credentials__item', { hasText: 'DeepSeek' })
    await row.getByRole('button', { name: '填入 API Key' }).click()
    await row.locator('input').fill('sk-bad-1234567890')
    await row.getByRole('button', { name: '验证并保存' }).click()

    await expect(page.locator('.el-message')).toContainText('API Key 无效')
    await expect(row).toContainText('未配置')
  })

  test('已配置的服务商可以删除，删除后回到未配置', async ({ page }) => {
    await installApiStubs(page, {
      extra: {
        'GET /users/me/model-credentials': {
          body: {
            items: [
              {
                provider: 'deepseek',
                maskedKey: 'sk-…4f2a',
                updatedAt: '2026-09-19T12:00:00Z',
                lastVerifiedAt: '2026-09-19T12:00:00Z',
              },
            ],
          },
        },
      },
    })
    await page.goto('/app/settings?tab=credentials')
    await waitForRendered(page, '.credentials')

    const row = page.locator('.credentials__item', { hasText: 'DeepSeek' })
    await expect(row).toContainText('已配置 · sk-…4f2a')
    await row.getByRole('button', { name: '删除' }).click()

    const dialog = page.locator('.el-message-box')
    await expect(dialog).toContainText('会回落到本站默认密钥')
    await dialog.getByRole('button', { name: '删除' }).click()

    await expect(row).toContainText('未配置')
  })
})

/**
 * 设置页「账户信息」分栏：可改用户名、可换绑手机号（用户 2026-09-27 要求）。
 *
 * 与上面一样只拦接口：这里验证「界面收到响应后显示什么、发出了什么请求」。
 * 真实换绑（后端验密码、验证码发到新号码、旧号失效）属于后端联调，本文件不作断言。
 */
test.describe('设置页 · 账户信息', () => {
  const ACCOUNT_USER = {
    ...MOCK_USER,
    phoneMasked: '138****8000',
    idCardMasked: '110105********002X',
  }
  const CODE_CHALLENGE = { challengeId: 'c-e2e', expiresInSeconds: 300, resendAfterSeconds: 60 }

  function accountStubs(extra: StubTable = {}): StubTable {
    return {
      'GET /users/me': { body: ACCOUNT_USER },
      // 账户分栏会请求头像，未配桩会打印噪音并返回 404（这里本来就没有头像）。
      'GET /users/me/avatar': { status: 404, body: {} },
      ...extra,
    }
  }

  test('改用户名要求当前密码，提交后登录名更新', async ({ page }) => {
    let patched: unknown
    await installApiStubs(page, {
      extra: accountStubs({ 'PATCH /users/me': { body: { ...ACCOUNT_USER, username: 'e2e-new' } } }),
    })
    page.on('request', (request) => {
      if (request.method() === 'PATCH' && request.url().includes('/api/v1/users/me')) {
        patched = request.postDataJSON()
      }
    })
    await page.goto('/app/settings?tab=account')
    await waitForRendered(page, '.profile-card')

    const password = page.locator('input[autocomplete="current-password"]')
    await expect(password, '用户名没变时不显示密码框').toHaveCount(0)

    await page.locator('input[autocomplete="username"]').fill('e2e-new')
    await expect(password).toHaveCount(1)
    await password.fill('e2e-password-1')
    await page.getByRole('button', { name: '保存修改' }).click()

    await expect(page.locator('.el-message').last()).toContainText('用户名已更新')
    expect(patched).toEqual({ username: 'e2e-new', currentPassword: 'e2e-password-1' })
    await expect(page.locator('input[autocomplete="username"]')).toHaveValue('e2e-new')
  })

  test('换绑手机号：验证码发给新号码，确认后掩码更新', async ({ page }) => {
    const calls: { url: string; body: unknown }[] = []
    await installApiStubs(page, {
      extra: accountStubs({
        'POST /users/me/phone-verification/change-code': { status: 202, body: CODE_CHALLENGE },
        'POST /users/me/phone-verification/change': {
          body: { ...ACCOUNT_USER, phoneMasked: '139****9001' },
        },
      }),
    })
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname
      if (path.includes('/users/me/phone-verification/change')) {
        calls.push({ url: path, body: request.postDataJSON() })
      }
    })
    await page.goto('/app/settings?tab=account')
    await waitForRendered(page, '.profile-card')

    await page.locator('.phone-change__toggle').click()
    await page.locator('input[autocomplete="tel"]').fill('13900139001')
    await page.locator('.phone-change__fields input[autocomplete="current-password"]').fill('e2e-password-1')
    await page.locator('.phone-change__request').click()
    await expect(page.locator('.phone-change__request')).toContainText('秒后可重发')

    await page.locator('input[autocomplete="one-time-code"]').fill('482731')
    await page.locator('.phone-change__confirm').click()
    await expect(page.locator('.el-message').last()).toContainText('手机号已更换')

    expect(calls[0]).toEqual({
      url: '/api/v1/users/me/phone-verification/change-code',
      body: { phone: '13900139001', currentPassword: 'e2e-password-1' },
    })
    expect(calls[1]).toEqual({
      url: '/api/v1/users/me/phone-verification/change',
      body: { phone: '13900139001', challengeId: 'c-e2e', code: '482731' },
    })
    await expect(page.locator('.account-info')).toContainText('139****9001')
  })

  test('改号即清验证：换号码后必须重新获取验证码', async ({ page }) => {
    await installApiStubs(page, {
      extra: accountStubs({
        'POST /users/me/phone-verification/change-code': { status: 202, body: CODE_CHALLENGE },
      }),
    })
    await page.goto('/app/settings?tab=account')
    await waitForRendered(page, '.profile-card')

    await page.locator('.phone-change__toggle').click()
    const phone = page.locator('input[autocomplete="tel"]')
    await phone.fill('13900139001')
    await page.locator('.phone-change__fields input[autocomplete="current-password"]').fill('e2e-password-1')
    await page.locator('.phone-change__request').click()
    await expect(page.locator('.phone-change__hint')).toBeVisible()

    await phone.fill('13900139002')
    await expect(page.locator('.phone-change__hint')).toHaveCount(0)
    await expect(page.locator('input[autocomplete="one-time-code"]')).toBeDisabled()
  })

  test('当前密码不正确时给出服务端文案', async ({ page }) => {
    await installApiStubs(page, {
      extra: accountStubs({
        'POST /users/me/phone-verification/change-code': {
          status: 422,
          body: { code: 'ACCOUNT_PASSWORD_INVALID', message: '当前密码不正确' },
        },
      }),
    })
    await page.goto('/app/settings?tab=account')
    await waitForRendered(page, '.profile-card')

    await page.locator('.phone-change__toggle').click()
    await page.locator('input[autocomplete="tel"]').fill('13900139001')
    await page.locator('.phone-change__fields input[autocomplete="current-password"]').fill('wrong-password')
    await page.locator('.phone-change__request').click()
    await expect(page.locator('.phone-change__error')).toContainText('当前密码不正确')
  })
})