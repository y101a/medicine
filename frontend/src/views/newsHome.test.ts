import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import DashboardView from './DashboardView.vue'
import { newsApi } from '../api/news'
import { ApiError } from '../api/http'

vi.mock('../api/news', () => ({
  newsApi: { page: vi.fn() },
}))

const emptyPage = {
  category: 'all' as const,
  status: 'sources_not_connected' as const,
  asOf: null,
  items: [],
  tips: [],
}

async function setup() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app', name: 'home', component: DashboardView },
      { path: '/app/chat', name: 'chat', component: { template: '<p>chat</p>' } },
    ],
  })
  await router.push('/app')
  await router.isReady()
  const wrapper = mount(DashboardView, {
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
  vi.mocked(newsApi.page).mockResolvedValue({ ...emptyPage })
})

describe('健康资讯首页（F1 页面框架）', () => {
  it('未接入新闻源时明确说明，不用占位内容冒充新闻', async () => {
    const { wrapper } = await setup()

    expect(wrapper.text()).toContain('新闻源尚未接入')
    expect(wrapper.text()).toContain('不会用示例内容冒充每日新闻')
    // 没有条目就不得声称「今日已更新」，也不出现任何来源外链。
    expect(wrapper.text()).not.toContain('今日已更新')
    expect(wrapper.find('.cards').exists()).toBe(false)
    expect(wrapper.find('.news a').exists()).toBe(false)
    expect(wrapper.text()).toContain('小贴士尚未接入来源')
  })

  it('四个分区可切换，并按分类请求资讯', async () => {
    const { wrapper } = await setup()
    expect(newsApi.page).toHaveBeenCalledWith('all')

    const wellness = wrapper.findAll('.tabs button').find(item => item.text() === '养生')
    await wellness?.trigger('click')
    await flushPromises()
    expect(newsApi.page).toHaveBeenLastCalledWith('wellness')
    expect(wellness?.attributes('aria-selected')).toBe('true')
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
    expect(wrapper.text()).toContain('发布')
    expect(wrapper.text()).toContain('获取')
    const link = wrapper.get('.cards a')
    expect(link.attributes('href')).toBe('https://www.chinacdc.cn/example')
    expect(link.attributes('rel')).toContain('noopener')
    expect(wrapper.find('.news a').text()).toContain('前往来源核对')
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