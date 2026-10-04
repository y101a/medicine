import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import PortalLayout from '../layouts/PortalLayout.vue'
import PortalView from './PortalView.vue'
import { newsApi } from '../api/news'
import { ApiError } from '../api/http'

vi.mock('../api/news', () => ({ newsApi: { page: vi.fn() } }))

/** 守卫会读登录态；这里给出可控的替身，避免依赖真实登录流程。 */
const authState = vi.hoisted(() => ({ isAuthenticated: true }))
vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({
    initialize: async () => {},
    user: { username: 'e2e' },
    get isAuthenticated() {
      return authState.isAuthenticated
    },
  }),
}))

const emptyPage = {
  category: 'all' as const,
  status: 'sources_not_connected' as const,
  asOf: null,
  items: [],
  tips: [],
}

/** F2 用：一条真实形状的资讯条目（WHO 疾病暴发新闻）。 */
const baseItem = {
  category: 'disease' as const,
  title: 'Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo',
  summary: null,
  sourceName: 'WHO 疾病暴发新闻',
  canonicalUrl: 'https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON618',
  publishedAt: '2026-09-25T15:16:26Z',
  retrievedAt: '2026-10-04T16:04:47Z',
  medicalReviewed: false,
}

async function setup() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/portal', name: 'portal', component: PortalView },
      { path: '/app/chat', name: 'chat', component: { template: '<p>chat</p>' } },
    ],
  })
  await router.push('/portal')
  await router.isReady()
  const wrapper = mount(PortalView, {
    global: {
      plugins: [router],
      stubs: { 'el-icon': { template: '<span><slot /></span>' } },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.resetAllMocks()
  authState.isAuthenticated = true
  vi.mocked(newsApi.page).mockResolvedValue({ ...emptyPage })
})

describe('独立资讯门户（/portal，F1 页面框架）', () => {
  it('未接入新闻源时明确说明，不用占位内容冒充新闻', async () => {
    const { wrapper } = await setup()

    expect(wrapper.text()).toContain('新闻源尚未接入')
    expect(wrapper.text()).toContain('不会用示例内容冒充每日新闻')
    expect(wrapper.text()).not.toContain('今日已更新')
    expect(wrapper.find('.cards').exists()).toBe(false)
    expect(wrapper.find('.news a').exists()).toBe(false)
    expect(wrapper.text()).toContain('小贴士尚未接入来源')
  })

  it('F2：同题多期折成一组并标出期号，来源状态用中文显示', async () => {
    vi.mocked(newsApi.page).mockResolvedValue({
      category: 'disease',
      status: 'ready',
      asOf: '2026-10-04T16:04:47Z',
      nextRefreshAt: '2026-10-04T20:00:00Z',
      items: [
        { ...baseItem, id: 'a' },
        {
          ...baseItem,
          id: 'b',
          publishedAt: '2026-09-10T08:16:08Z',
          canonicalUrl: 'https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON617',
        },
        {
          ...baseItem,
          id: 'c',
          title: 'Cholera - Haiti',
          publishedAt: '2026-08-01T10:13:28Z',
          canonicalUrl: 'https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON614',
        },
      ],
      tips: [],
      sourceStatuses: [
        {
          id: 'who_disease_outbreak_news',
          name: 'WHO 疾病暴发新闻',
          status: 'ready',
          lastSuccessAt: '2026-10-04T16:04:47Z',
          lastErrorCode: null,
        },
      ],
    })
    const { wrapper } = await setup()

    // 同题两条折成一组：3 条 → 2 张卡（注意用直接子元素，卡片内「较早更新」列表也是 li）
    expect(wrapper.findAll('.cards > li')).toHaveLength(2)
    expect(wrapper.get('.card-updates').text()).toContain('同题更新 2 期')
    expect(wrapper.get('.card-updates').text()).toContain('DON618（2026）')
    expect(wrapper.get('.card-more summary').text()).toContain('另有 1 期较早更新')
    expect(wrapper.get('.card-more a').attributes('href')).toContain('2026-DON617')
    expect(wrapper.get('.source-status').text()).toContain('WHO 疾病暴发新闻：正常')
    expect(wrapper.get('.status-line').text()).toContain('最近更新')
    expect(wrapper.get('.cards .badge').text()).toBe('未经医学审核')
  })

  it('F2：部分来源不可用时说明实情，不谎称全部正常', async () => {
    vi.mocked(newsApi.page).mockResolvedValue({
      category: 'disease',
      status: 'partial',
      asOf: '2026-10-04T16:04:47Z',
      nextRefreshAt: null,
      items: [{ ...baseItem, id: 'a' }],
      tips: [],
      sourceStatuses: [
        {
          id: 'source_ok',
          name: '甲来源',
          status: 'ready',
          lastSuccessAt: '2026-10-04T16:04:47Z',
          lastErrorCode: null,
        },
        {
          id: 'source_bad',
          name: '乙来源',
          status: 'failed',
          lastSuccessAt: null,
          lastErrorCode: 'FETCH_TIMEOUT',
        },
      ],
    })
    const { wrapper } = await setup()

    expect(wrapper.get('.status-line').text()).toContain('部分来源暂时不可用')
    expect(wrapper.get('.source-status').text()).toContain('乙来源：更新失败')
    expect(wrapper.get('.source-status').text()).toContain('FETCH_TIMEOUT')
  })

  it('F2：来源更新失败且没有条目时给失败空态，不用旧内容冒充更新', async () => {
    vi.mocked(newsApi.page).mockResolvedValue({
      category: 'disease',
      status: 'failed',
      asOf: null,
      items: [],
      tips: [],
    })
    const { wrapper } = await setup()

    expect(wrapper.text()).toContain('来源更新失败')
    expect(wrapper.find('.cards').exists()).toBe(false)
  })

  it('AI 展示区保留规格要求的能力说明与两个按钮', async () => {
    const { wrapper } = await setup()

    expect(wrapper.text()).toContain('病理诊断科普助手')
    // 规格 §1：能力介绍只说现有能力，不宣传确诊、处方或替代医生。
    for (const word of ['健康科普', '医学资料辅助解释', '就医方向梳理']) {
      expect(wrapper.text()).toContain(word)
    }
    expect(wrapper.text()).toContain('不作确诊')
    expect(wrapper.find('.hero .primary').exists()).toBe(true)
    expect(wrapper.find('.hero .ghost').exists()).toBe(true)
  })

  it('五个分区（含全部）平铺可切换，并按分类请求资讯', async () => {
    const { wrapper } = await setup()
    expect(newsApi.page).toHaveBeenCalledWith('all')

    const tiles = wrapper.findAll('.category-tile')
    expect(tiles).toHaveLength(5)
    expect(tiles.map(item => item.text().replace(/\s+/g, ''))).toEqual([
      '全部所有分区的资讯总览',
      '养生作息、饮食与日常调理',
      '健身运动方式与安全注意',
      '疾病常见疾病科普与就医方向',
      '药物药品用途与注意事项',
    ])
    // 分区卡片排在 AI 展示区之后（用户要求「平铺在病理科普助手下面」）。
    expect(wrapper.element.querySelector('.hero + .categories')).not.toBeNull()
    // 「全部」既保留为第一块卡片，就不该再有第二个做同一件事的按钮。
    expect(wrapper.find('.all-chip').exists()).toBe(false)

    const wellness = tiles[1]
    await wellness.trigger('click')
    await flushPromises()
    expect(newsApi.page).toHaveBeenLastCalledWith('wellness')
    expect(wellness.attributes('aria-selected')).toBe('true')
    expect(wrapper.get('.panel-head h2').text()).toBe('养生')

    const all = tiles[0]
    await all.trigger('click')
    await flushPromises()
    expect(newsApi.page).toHaveBeenLastCalledWith('all')
    expect(all.attributes('aria-selected')).toBe('true')
    expect(wrapper.get('.panel-head h2').text()).toBe('全部')
  })

  it('没有安装包时下载入口保持不可用，也不跳外链', async () => {
    const { wrapper } = await setup()

    const download = wrapper.findAll('button').find(item => item.text().includes('下载 Windows 版'))
    expect(download?.attributes('disabled')).toBeDefined()
    expect(wrapper.find('a[href*="windows"]').exists()).toBe(false)
  })

  it('“与 AI 对话”进入现有聊天页', async () => {
    const { wrapper, router } = await setup()

    await wrapper.get('.primary').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/app/chat')
  })

  it('请求失败只显示受控提示并可重试，不保留上一个分类的条目', async () => {
    vi.mocked(newsApi.page).mockRejectedValueOnce(new ApiError('服务器暂时无法处理请求', 'HTTP_500', 500))
    const { wrapper } = await setup()

    expect(wrapper.text()).toContain('服务器暂时无法处理请求')
    expect(wrapper.find('.cards').exists()).toBe(false)

    vi.mocked(newsApi.page).mockResolvedValue({ ...emptyPage })
    await wrapper.get('.retry').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('新闻源尚未接入')
  })

  it('有真实条目时显示来源、发布与获取时间，并标注未经医学审核', async () => {
    vi.mocked(newsApi.page).mockResolvedValue({
      category: 'all',
      status: 'ready',
      asOf: '2026-10-04T00:00:00Z',
      items: [{
        id: 'n1',
        category: 'disease',
        title: '某地流感监测周报',
        summary: '受控短摘要。',
        sourceName: '中国疾病预防控制中心',
        canonicalUrl: 'https://www.chinacdc.cn/example',
        publishedAt: '2026-10-03T02:00:00Z',
        retrievedAt: '2026-10-04T00:10:00Z',
        medicalReviewed: false,
      }],
      tips: [],
    })
    const { wrapper } = await setup()

    expect(wrapper.text()).toContain('某地流感监测周报')
    expect(wrapper.text()).toContain('未经医学审核')
    expect(wrapper.text()).toContain('中国疾病预防控制中心')
    const link = wrapper.get('.cards a')
    expect(link.attributes('href')).toBe('https://www.chinacdc.cn/example')
    expect(link.attributes('rel')).toContain('noopener')
  })

  it('发布时间核实不到时明确写出来，不用获取时间冒充', async () => {
    vi.mocked(newsApi.page).mockResolvedValue({
      category: 'all',
      status: 'ready',
      asOf: null,
      items: [{
        id: 'n2',
        category: 'wellness',
        title: '无发布时间的条目',
        summary: '摘要。',
        sourceName: '未知来源',
        canonicalUrl: 'https://example.test/a',
        publishedAt: null,
        retrievedAt: '2026-10-04T00:10:00Z',
        medicalReviewed: false,
      }],
      tips: [],
    })
    const { wrapper } = await setup()

    expect(wrapper.text()).toContain('发布时间未核实')
  })
})

describe('门户布局与路由', () => {
  it('门户布局没有工作区侧栏，也不出现 ADR-011 的窄屏提示', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/portal', name: 'portal', component: PortalLayout }],
    })
    await router.push('/portal')
    await router.isReady()
    const wrapper = mount(PortalLayout, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.find('.sidebar').exists()).toBe(false)
    expect(wrapper.find('.viewport-hint').exists()).toBe(false)
    expect(wrapper.find('.workspace').exists()).toBe(false)
    // 2026-10-04 用户要求删掉顶部品牌栏：门户不再有页头，只有内容区与页脚。
    expect(wrapper.find('.portal-top').exists()).toBe(false)
    expect(wrapper.text()).toContain('开发原型')
  })

  it('门户是顶层路由，不挂在工作区布局下', async () => {
    const { default: appRouter } = await import('../router')
    const resolved = appRouter.resolve('/portal')

    expect(resolved.name).toBe('portal')
    // 匹配链只有门户自己（父布局 + 子视图，两层都在 /portal）：父级不是 WorkspaceLayout。
    expect(resolved.matched.map(item => item.path)).toEqual(['/portal', '/portal'])
    expect(resolved.matched.some(item => item.path.startsWith('/app'))).toBe(false)
  })

  it('未登录进门户被送回登录页并记住回跳地址', async () => {
    const { default: appRouter } = await import('../router')
    authState.isAuthenticated = false
    await appRouter.push('/portal')
    await flushPromises()

    expect(appRouter.currentRoute.value.name).toBe('login')
    expect(appRouter.currentRoute.value.query.redirect).toBe('/portal')
  }, 20_000)

  it('已登录访问登录页改为进入门户', async () => {
    const { default: appRouter } = await import('../router')
    authState.isAuthenticated = true
    await appRouter.push('/login')
    await flushPromises()

    expect(appRouter.currentRoute.value.name).toBe('portal')
  }, 20_000)
})