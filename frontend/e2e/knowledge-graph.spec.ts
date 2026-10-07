import { expect, test, type Page } from '@playwright/test'
import {
  describeOverflow,
  installApiStubs,
  measureOverflow,
  waitForRendered,
  type StubTable,
} from './support'

/**
 * 知识图谱探索页 `/knowledge-graph` 的浏览器验收。
 *
 * 与工作区不同：本页是**独立路由页**，不受 ADR-011 的 1000px 桌面优先约束，
 * 所以 375px 也必须真的没有横向溢出（与 `/portal` 同一取舍），失败消息里会带上
 * 越界元素的坐标与宽度，供看不到界面的读者定位。
 *
 * 接口全部走桩：`GET /knowledge-graph/concepts` 与 `POST /knowledge-graph/explore`，
 * 不依赖后端与数据库。真实联调仍要人工在开发库里跑（见 `BROWSER_ACCEPTANCE.md`）。
 */

const CONCEPT = { id: 'kg-concept-1', name: '儿童发热', type: 'topic' }

const READY_RESULT = {
  available: true,
  revision: 12,
  relations: [
    {
      claimId: 'claim-e2e-1',
      subject: CONCEPT,
      object: { id: 'kg-symptom-1', name: '发热伴精神差', type: 'symptom' },
      predicate: 'MAY_INCLUDE_SYMPTOM',
      evidence: [
        {
          documentId: 'doc-e2e-1-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
          chunkId: 'chunk-e2e-1-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
          title: '儿童发热的家庭护理与就医信号',
          section: '什么时候需要就医',
          url: 'https://wjw.beijing.gov.cn/example/knowledge-graph-evidence',
        },
      ],
    },
    {
      claimId: 'claim-e2e-2',
      subject: CONCEPT,
      object: { id: 'kg-department-1', name: '儿科', type: 'department' },
      predicate: 'SUGGESTS_DEPARTMENT',
      evidence: [
        {
          documentId: 'doc-e2e-2',
          chunkId: 'chunk-e2e-2',
          title: '儿科就诊指引（科普）',
          section: '',
          url: 'https://example.org/department',
        },
      ],
    },
  ],
}

const UNAVAILABLE_RESULT = { available: false, revision: null, relations: [] }
const EMPTY_CONCEPTS = { items: [] }
const CONCEPTS = { items: [CONCEPT] }

async function openPage(page: Page, width: number, extra: StubTable) {
  const stubs = await installApiStubs(page, { authenticated: true, extra })
  await page.setViewportSize({ width, height: width === 375 ? 720 : 800 })
  await page.goto('/knowledge-graph')
  await waitForRendered(page, '.knowledge-graph')
  return stubs
}

async function runSearch(page: Page, keyword = '儿童发热') {
  await page.locator('#kg-query').fill(keyword)
  await page.locator('.kg-search__submit').click()
}

for (const width of [1280, 375]) {
  test(`${width}px：空结果页可用且无横向溢出（独立路由，无工作区侧栏）`, async ({ page }) => {
    const stubs = await openPage(page, width, {
      'GET /knowledge-graph/concepts': { body: EMPTY_CONCEPTS },
    })

    const landed = new URL(page.url()).pathname
    expect(landed, `/knowledge-graph 被重定向到了 ${landed}`).toBe('/knowledge-graph')

    // 独立页面：没有工作区侧栏，也没有 ADR-011 的窄屏提示。
    await expect(page.locator('.sidebar')).toHaveCount(0)
    await expect(page.locator('.viewport-hint')).toHaveCount(0)

    await runSearch(page, '不存在的词')
    await expect(page.locator('.knowledge-graph')).toHaveAttribute('data-state', 'empty')
    // 断言到具体标题：页面里还有一个读屏用的 aria-live 播报区，文案相同（严格模式会命中两个）。
    await expect(page.locator('[data-testid="kg-state-empty"] h2')).toHaveText('没有找到相关概念')

    const report = await measureOverflow(page)
    expect(report.overflow, describeOverflow(report, '/knowledge-graph', width)).toBeLessThanOrEqual(1)
    expect(stubs.unmatched, `页面请求了未配置的接口：${stubs.unmatched.join('、')}`).toEqual([])
  })

  test(`${width}px：有结果页（含长 ID 与证据展开）无横向溢出`, async ({ page }) => {
    const stubs = await openPage(page, width, {
      'GET /knowledge-graph/concepts': { body: CONCEPTS },
      'POST /knowledge-graph/explore': { body: READY_RESULT },
    })

    await runSearch(page)
    await expect(page.locator('.knowledge-graph')).toHaveAttribute('data-state', 'ready')

    // 展开全部证据：长 UUID、长标题与来源链接都必须能换行。
    const toggles = page.locator('.kg-evidence-toggle')
    await expect(toggles).toHaveCount(2)
    await toggles.nth(0).click()
    await toggles.nth(1).click()
    await expect(page.locator('.kg-evidence')).toHaveCount(2)

    const report = await measureOverflow(page)
    expect(report.overflow, describeOverflow(report, '/knowledge-graph', width)).toBeLessThanOrEqual(1)
    expect(stubs.unmatched, `页面请求了未配置的接口：${stubs.unmatched.join('、')}`).toEqual([])
  })
}

test('主入口在侧栏主导航里，且输入框内没有任何知识图谱入口', async ({ page }) => {
  // `/app/chat` 挂载时会取语音预设；不补这个桩就会打出一条「未配置的接口」噪音日志。
  await installApiStubs(page, {
    authenticated: true,
    extra: {
      'GET /speech/presets': {
        body: {
          default: 'mandarin_female',
          items: [{ id: 'mandarin_female', label: '普通话·自然女声', language: 'zh-CN', dialect: null }],
        },
      },
    },
  })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/app/chat')
  await waitForRendered(page, '.workspace')

  const navLink = page.locator('nav[aria-label="主导航"] a[href="/knowledge-graph"]')
  await expect(navLink, '主导航里应有「知识图谱」入口').toHaveCount(1)
  await expect(navLink).toContainText('知识图谱')

  // 用户明令：不得把入口放进聊天输入框（`.composer` 内任何位置都不行）。
  await expect(page.locator('.composer a[href="/knowledge-graph"]')).toHaveCount(0)
  await expect(page.locator('.composer')).not.toContainText('知识图谱')

  await navLink.click()
  await waitForRendered(page, '.knowledge-graph')
  expect(new URL(page.url()).pathname).toBe('/knowledge-graph')
  await expect(page.locator('.kg-title')).toHaveText('知识图谱探索')
  // 页面内提供回到工作区的唯一回程入口。
  await expect(page.locator('.kg-back')).toHaveText(/返回工作区/)
})

test('① available=false：显示「图谱暂不可用」+ 原因 + 重试，绝不显示成「没有找到」', async ({ page }) => {
  await openPage(page, 1280, {
    'GET /knowledge-graph/concepts': { body: CONCEPTS },
    'POST /knowledge-graph/explore': { body: UNAVAILABLE_RESULT },
  })
  await runSearch(page)

  await expect(page.locator('.knowledge-graph')).toHaveAttribute('data-state', 'unavailable')
  const section = page.locator('[data-testid="kg-state-unavailable"]')
  await expect(section).toBeVisible()
  await expect(section).toContainText('图谱暂不可用')
  await expect(section).toContainText('available=false')
  await expect(page.locator('.kg-retry')).toBeVisible()

  // 前车之鉴：失败不能被显示成空结果。
  await expect(page.locator('[data-testid="kg-state-empty"]')).toHaveCount(0)
  await expect(page.locator('.knowledge-graph')).not.toContainText('没有找到相关概念')
  await expect(page.locator('.knowledge-graph')).not.toContainText('没有找到相关关系')
})

test('① 接口 503：同样是「图谱暂不可用」，重试会真的再发一次请求', async ({ page }) => {
  await openPage(page, 1280, {
    'GET /knowledge-graph/concepts': { status: 503, body: { message: '服务暂时不可用，请稍后再试' } },
  })

  let conceptRequests = 0
  page.on('request', (request) => {
    if (request.url().includes('/knowledge-graph/concepts')) conceptRequests += 1
  })

  await runSearch(page)
  await expect(page.locator('.knowledge-graph')).toHaveAttribute('data-state', 'unavailable')
  await expect(page.locator('.kg-state__reason')).toContainText('HTTP 503')
  await expect(page.locator('[data-testid="kg-state-empty"]')).toHaveCount(0)

  await page.locator('.kg-retry').click()
  await expect.poll(() => conceptRequests, { message: '点重试必须真的重新请求' }).toBeGreaterThanOrEqual(2)
})

test('③ 有结果：按类型分组、证据可展开看到来源文档与标识、边界声明常驻', async ({ page }) => {
  await openPage(page, 1280, {
    'GET /knowledge-graph/concepts': { body: CONCEPTS },
    'POST /knowledge-graph/explore': { body: READY_RESULT },
  })
  await runSearch(page)

  await expect(page.locator('.knowledge-graph')).toHaveAttribute('data-state', 'ready')
  await expect(page.locator('.kg-concept')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.kg-group[data-predicate="MAY_INCLUDE_SYMPTOM"]')).toContainText('可能出现的表现')
  await expect(page.locator('.kg-group[data-predicate="SUGGESTS_DEPARTMENT"]')).toContainText('通常咨询的科室')

  const firstToggle = page.locator('.kg-evidence-toggle').first()
  await expect(firstToggle).toHaveAttribute('aria-expanded', 'false')
  await expect(page.locator('.kg-evidence')).toHaveCount(0)
  await firstToggle.click()
  await expect(firstToggle).toHaveAttribute('aria-expanded', 'true')
  const panel = page.locator('.kg-evidence').first()
  await expect(panel).toContainText('儿童发热的家庭护理与就医信号')
  await expect(panel).toContainText('什么时候需要就医')
  await expect(panel).toContainText('doc-e2e-1-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
  await expect(panel.locator('a.kg-evidence__link')).toHaveAttribute('href', /^https:\/\//)

  // 页面必须常驻科普边界声明（未经医学审核、不构成诊断/用药建议）。
  await expect(page.locator('.kg-disclaimer')).toContainText('未经医学审核')
  await expect(page.locator('.kg-disclaimer')).toContainText('不构成诊断')
  await expect(page.locator('.kg-foot')).toContainText('不构成诊断或用药建议')
})

test('③ 未审核关系必须显著标注「未审核、仅供参考、不是医学结论」', async ({ page }) => {
  const pending = {
    ...READY_RESULT,
    relations: [
      READY_RESULT.relations[0],
      { ...READY_RESULT.relations[1], claimId: 'claim-e2e-pending', reviewDecision: 'pending' },
    ],
  }
  await openPage(page, 1280, {
    'GET /knowledge-graph/concepts': { body: CONCEPTS },
    'POST /knowledge-graph/explore': { body: pending },
  })
  await runSearch(page)

  const unreviewed = page.locator('.kg-relation--unreviewed')
  await expect(unreviewed).toHaveCount(1)
  await expect(unreviewed).toContainText('未审核、仅供参考、不是医学结论')
  await expect(page.locator('.kg-relation:not(.kg-relation--unreviewed)')).toHaveCount(1)
})

test('键盘可达：输入框回车即查询，证据开关可用 Enter 展开', async ({ page }) => {
  await openPage(page, 1280, {
    'GET /knowledge-graph/concepts': { body: CONCEPTS },
    'POST /knowledge-graph/explore': { body: READY_RESULT },
  })

  await page.locator('#kg-query').fill('儿童发热')
  await page.locator('#kg-query').press('Enter')
  await expect(page.locator('.knowledge-graph')).toHaveAttribute('data-state', 'ready')

  const toggle = page.locator('.kg-evidence-toggle').first()
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
})

test('搜索词太短时本地拦下：不发请求、给出可读提示', async ({ page }) => {
  const stubs = await openPage(page, 1280, {
    'GET /knowledge-graph/concepts': { body: CONCEPTS },
  })
  await runSearch(page, '发')

  await expect(page.locator('#kg-query-error')).toContainText('至少输入 2 个字符')
  await expect(page.locator('.knowledge-graph')).toHaveAttribute('data-state', 'idle')
  expect(stubs.unmatched, '没搜索成功时不应有未配置的接口').toEqual([])
})