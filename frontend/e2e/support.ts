import type { Page } from '@playwright/test'

/**
 * e2e 的公共设施。
 *
 * 两条设计原则：
 * 1. **不依赖后端**：只起 Vite，所有 `/api/v1/**` 请求由 `page.route` 拦截。这样能精确
 *    构造异常响应（例如故意返回 `{"detail":[...]}`），也不必占用数据库。
 * 2. **断言要产出可读文字**：失败消息里带上元素选择器、坐标与尺寸，让看不到界面的
 *    AI 也能定位问题，而不是只收到一句「断言失败」。
 *
 * 边界：这里验证的是「前端拿到某种响应后渲染成什么样」，**不验证真实接口联调**。
 */

export const API_GLOB = '**/api/v1/**'

export const MOCK_USER = {
  id: 'e2e-user',
  username: 'e2e',
  realName: '端到端测试',
  gender: 'private',
  role: 'user',
  phoneVerified: true,
  registeredAt: '2026-09-01T00:00:00Z',
} as const

export interface Stub {
  status?: number
  body: unknown
  contentType?: string
}

/** 键的格式：`GET /health-records`；路径段可用 `*` 通配，如 `PATCH /health-records/*`。 */
export type StubTable = Record<string, Stub>

function daysAgo(days: number): string {
  return new Date(Date.now() - days * 86_400_000).toISOString()
}

function settingsFor(noticeSeen: boolean) {
  return { collectionEnabled: true, noticeSeen, recordCount: 3 }
}

const RECORDS = {
  items: [
    {
      id: 'r1',
      category: 'symptom',
      categoryLabel: '症状',
      content: '最近两周偶有咳嗽，无发热',
      source: 'conversation',
      recordedAt: daysAgo(10),
      updatedAt: daysAgo(10),
    },
    {
      id: 'r2',
      category: 'medication',
      categoryLabel: '用药',
      content: '每天早晨服用降压药',
      source: 'user',
      recordedAt: daysAgo(40),
      updatedAt: daysAgo(40),
    },
    {
      id: 'r3',
      category: 'lifestyle',
      categoryLabel: '生活习惯',
      content: '睡眠偏少，每天约六小时',
      source: 'onboarding',
      recordedAt: daysAgo(75),
      updatedAt: daysAgo(75),
    },
  ],
}

const HOSPITALS = {
  items: [
    {
      poiId: 'p1',
      name: '示例市第一医院',
      district: '示例区',
      address: '示例路 1 号',
      routeDurationSeconds: 900,
      routeDistanceMeters: 3200,
      navigationUrl: 'https://uri.amap.com/navigation?to=e2e',
    },
    {
      poiId: 'p2',
      name: '示例市中心医院',
      district: '中心区',
      address: '中心路 2 号',
      routeDurationSeconds: 1500,
      routeDistanceMeters: 6100,
      navigationUrl: 'https://uri.amap.com/navigation?to=e2e2',
    },
  ],
  notice: '以下结果按路线时间排序，仅供就医分流参考，不构成就诊建议。',
}

function defaultStubs(authenticated: boolean, noticeSeen: boolean): StubTable {
  const settings = settingsFor(noticeSeen)
  return {
    'GET /users/me': authenticated
      ? { body: MOCK_USER }
      : { status: 401, body: { message: '当前未登录' } },
    'POST /auth/refresh': { status: 401, body: { message: '登录状态已失效，请重新登录' } },
    'POST /auth/login': { body: { user: MOCK_USER } },
    'POST /auth/register': { body: { user: MOCK_USER } },
    'POST /auth/logout': { body: {} },

    'GET /health-records/settings': { body: settings },
    'PATCH /health-records/settings': { body: settings },
    'POST /health-records/onboarding': { body: settings },
    'POST /health-records/extract': { body: { stored: 0 } },
    'GET /health-records': { body: RECORDS },
    'POST /health-records': { body: RECORDS.items[0] },
    'PATCH /health-records/*': { body: RECORDS.items[0] },
    'DELETE /health-records/*': { body: {} },

    'GET /consultations': { body: { items: [], hasMore: false } },
    'GET /consultations/*': { body: { items: [], hasMore: false } },
    'GET /models': {
      body: {
        items: [
          {
            id: 'e2e-model',
            name: '端到端测试模型',
            provider: 'deepseek',
            providerName: 'DeepSeek',
            description: '仅用于界面验收',
            isDefault: true,
            keySource: 'server',
          },
        ],
      },
    },

    'GET /users/me/model-credentials': { body: { items: [] } },
    'PUT /users/me/model-credentials/*': {
      body: {
        provider: 'deepseek',
        maskedKey: 'sk-…4f2a',
        updatedAt: '2026-09-19T12:00:00Z',
        lastVerifiedAt: '2026-09-19T12:00:00Z',
      },
    },
    'DELETE /users/me/model-credentials/*': { body: {} },

    /*
     * 工作区布局与主页在挂载时就会取头像和私人知识库列表，所以这两个必须放在**默认桩**里：
     * 之前没配，每个没显式接管它们的规格都会打出「未配置的接口：GET /users/me/avatar」，
     * 逼得 `private-knowledge.spec.ts` 专门为这条既存缺口写例外。
     *
     * 头像返回 404 是**有意的**：这里验的是「没有头像时界面回落到首字母」，而不是造假图；
     * 两个用头像的模板都带 `@error="avatarFailed = true"`，404 走的就是回落分支。
     */
    'GET /users/me/avatar': { status: 404, body: { message: '端到端测试未设置头像' } },
    'GET /private-knowledge/collections': { body: { items: [] } },

    'POST /navigation/nearby-hospitals': { body: HOSPITALS },
    'POST /navigation/hospitals-by-area': { body: HOSPITALS },
  }
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function findStub(table: StubTable, method: string, path: string): Stub | undefined {
  const exact = table[`${method} ${path}`]
  if (exact) return exact

  for (const [key, stub] of Object.entries(table)) {
    const [keyMethod, pattern] = key.split(' ')
    if (keyMethod !== method || !pattern.includes('*')) continue
    const regex = new RegExp(`^${pattern.split('*').map(escapeRegExp).join('[^/]*')}$`)
    if (regex.test(path)) return stub
  }
  return undefined
}

export interface InstallOptions {
  /** false 时 `GET /users/me` 返回 401，用于验收登录页/注册页。 */
  authenticated?: boolean
  /**
   * 是否已看过采集说明。默认 true（不弹窗）——那是模态弹窗，会拦截页面点击，
   * 也只在专门验收弹窗的用例里才需要设为 false。
   */
  noticeSeen?: boolean
  /** 覆盖或补充默认桩，键格式同 `StubTable`。 */
  extra?: StubTable
}

export interface InstalledStubs {
  /** 测试期间没有被配置到的接口，测试末尾可用它自查漏配。 */
  unmatched: string[]
}

/**
 * 安装接口桩。未配置的接口返回 404，并把 `方法 路径` 打印出来——
 * 漏配会以文字形式暴露，而不是让测试莫名其妙地失败。
 */
export async function installApiStubs(
  page: Page,
  options: InstallOptions = {},
): Promise<InstalledStubs> {
  const { authenticated = true, noticeSeen = true, extra = {} } = options
  const table: StubTable = { ...defaultStubs(authenticated, noticeSeen), ...extra }
  const unmatched: string[] = []

  await page.route(API_GLOB, async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace('/api/v1', '')
    const method = request.method()
    const stub = findStub(table, method, path)

    if (!stub) {
      unmatched.push(`${method} ${path}`)
      console.log(`[e2e] 未配置的接口：${method} ${path}`)
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'e2e 未配置该接口' }),
      })
      return
    }

    await route.fulfill({
      status: stub.status ?? 200,
      contentType: stub.contentType ?? 'application/json',
      body: JSON.stringify(stub.body),
    })
  })

  return { unmatched }
}

export interface OverflowOffender {
  label: string
  right: number
  width: number
}

export interface OverflowReport {
  innerWidth: number
  scrollWidth: number
  overflow: number
  offenders: OverflowOffender[]
}

/** 量出横向溢出，并列出「右边界越界」的元素，供失败消息直接引用。 */
export async function measureOverflow(page: Page): Promise<OverflowReport> {
  return page.evaluate(() => {
    const innerWidth = window.innerWidth
    const offenders: { label: string; right: number; width: number }[] = []

    for (const element of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
      const rect = element.getBoundingClientRect()
      if (rect.width <= 0 || rect.right <= innerWidth + 1) continue
      const id = element.id ? `#${element.id}` : ''
      const className = typeof element.className === 'string'
        ? element.className.trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.')
        : ''
      offenders.push({
        label: `${element.tagName.toLowerCase()}${id}${className ? `.${className}` : ''}`,
        right: Math.round(rect.right),
        width: Math.round(rect.width),
      })
    }

    offenders.sort((a, b) => b.right - a.right)
    return {
      innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      overflow: document.documentElement.scrollWidth - innerWidth,
      offenders: offenders.slice(0, 6),
    }
  })
}

/** 把溢出报告拼成一句人能读、AI 也能读的话。 */
export function describeOverflow(report: OverflowReport, path: string, width: number): string {
  const offenders = report.offenders.length
    ? report.offenders.map(item => `${item.label}(右边界 ${item.right}px, 宽 ${item.width}px)`).join('；')
    : '未定位到具体元素'
  return `${path} 在 ${width}px 视口下横向溢出 ${report.overflow}px`
    + `（scrollWidth=${report.scrollWidth}, innerWidth=${report.innerWidth}）。越界元素：${offenders}`
}

/** 等待页面渲染稳定：Vite 的 HMR 长连接会让 networkidle 不可靠，所以按时间兜底。 */
export async function settle(page: Page, ms = 600): Promise<void> {
  await page.waitForLoadState('load')
  await page.waitForTimeout(ms)
}

/**
 * 等页面真正渲染到「可以测量」的状态。
 *
 * 固定 sleep 不是确定性：实测出现过 `load` 事件已触发、URL 已是 `/app`，但路由守卫仍在等
 * `GET /users/me`、`.workspace` 尚未挂载的情况——此时测出来的「无横向溢出」毫无意义
 * （页面上根本没有那个 1000px 的工作区）。所以**测量前必须显式等到元素出现**，
 * 而不是睡一段时间赌它渲染完了。
 */
export async function waitForRendered(page: Page, selector = '.workspace, main'): Promise<void> {
  await page.locator(selector).first().waitFor({ state: 'visible' })
}