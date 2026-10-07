import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import KnowledgeGraphView from './KnowledgeGraphView.vue'
import { knowledgeGraphApi } from '../api/knowledgeGraph'
import { ApiError } from '../api/http'
import { KNOWLEDGE_GRAPH_UNREVIEWED_NOTICE } from '../types/knowledgeGraphUi'

/**
 * 知识图谱探索页的专项测试。
 *
 * 最重要的验收点只有一个：**三态必须分开**——
 * ① 图谱不可用（报错 / 超时 / `available=false`）→ 「图谱暂不可用」+ 原因 + 重试；
 * ② 查询成功但无结果 → 「没有找到相关概念」+ 建议；
 * ③ 有结果 → 分组展示关系与证据。
 * 本项目有过「请求失败被显示成还没有知识库」的真实事故，所以这里对①专门断言
 * **不得出现**②的文案。
 *
 * 边界：接口模块整体被 mock，验证的是「拿到某种响应后页面渲染成什么样、发出什么请求」，
 * 不验证真实后端联调（真实链路见 `BROWSER_ACCEPTANCE.md` 的人工清单）。
 */
vi.mock('../api/knowledgeGraph', () => ({
  knowledgeGraphApi: { concepts: vi.fn(), explore: vi.fn() },
}))

const CONCEPT = { id: 'concept-1', name: '儿童发热', type: 'topic' }

function evidence(overrides: Record<string, unknown> = {}) {
  return {
    documentId: 'doc-1111-2222',
    chunkId: 'chunk-3333-4444',
    title: '儿童发热的家庭护理科普',
    section: '什么时候需要就医',
    url: 'https://example.org/health/fever',
    ...overrides,
  }
}

function relation(overrides: Record<string, unknown> = {}) {
  return {
    claimId: 'claim-1',
    subject: { id: 'concept-1', name: '儿童发热', type: 'topic' },
    object: { id: 'symptom-1', name: '发热伴精神差', type: 'symptom' },
    predicate: 'MAY_INCLUDE_SYMPTOM',
    evidence: [evidence()],
    ...overrides,
  }
}

async function setup() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/knowledge-graph', name: 'knowledge-graph', component: KnowledgeGraphView },
      { path: '/app', name: 'home', component: { template: '<p>工作区</p>' } },
    ],
  })
  await router.push('/knowledge-graph')
  await router.isReady()
  const wrapper = mount(KnowledgeGraphView, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

async function search(wrapper: VueWrapper, keyword: string) {
  await wrapper.find('#kg-query').setValue(keyword)
  await wrapper.find('form.kg-search').trigger('submit')
  await flushPromises()
}

function currentState(wrapper: VueWrapper) {
  return wrapper.find('.knowledge-graph').attributes('data-state')
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('知识图谱探索页：三态与边界', () => {
  it('初始状态只提示输入，不请求任何接口，并常驻科普边界声明', async () => {
    const { wrapper } = await setup()

    expect(currentState(wrapper)).toBe('idle')
    expect(knowledgeGraphApi.concepts).not.toHaveBeenCalled()
    expect(knowledgeGraphApi.explore).not.toHaveBeenCalled()

    const text = wrapper.text()
    expect(text).toContain('未经医学审核')
    expect(text).toContain('不构成诊断')
    expect(text).toContain('搜索概念')
  })

  it('① 接口 503：显示「图谱暂不可用」+ 原因 + 重试，且绝不显示成「没有找到」', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockRejectedValue(
      new ApiError('服务暂时不可用，请稍后再试', 'HTTP_503', 503),
    )
    const { wrapper } = await setup()
    await search(wrapper, '儿童发热')

    expect(currentState(wrapper)).toBe('unavailable')
    const section = wrapper.find('[data-testid="kg-state-unavailable"]')
    expect(section.exists()).toBe(true)
    expect(section.text()).toContain('图谱暂不可用')
    expect(section.text()).toContain('服务暂时不可用')
    expect(section.text()).toContain('HTTP 503')
    expect(section.text()).toContain('这不等于「没有相关概念」')
    expect(wrapper.find('.kg-retry').exists()).toBe(true)

    // 前车之鉴：失败不能被显示成空结果。
    expect(wrapper.find('[data-testid="kg-state-empty"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('没有找到相关概念')

    await wrapper.find('.kg-retry').trigger('click')
    await flushPromises()
    expect(knowledgeGraphApi.concepts).toHaveBeenCalledTimes(2)
  })

  it('① explore 返回 available=false（未启用/版本失配/故障）也是不可用，不是「没有关系」', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockResolvedValue([CONCEPT])
    vi.mocked(knowledgeGraphApi.explore).mockResolvedValue({
      available: false,
      revision: null,
      relations: [],
    })
    const { wrapper } = await setup()
    await search(wrapper, '儿童发热')

    expect(currentState(wrapper)).toBe('unavailable')
    const text = wrapper.text()
    expect(text).toContain('图谱暂不可用')
    expect(text).toContain('available=false')
    expect(text).not.toContain('没有找到相关关系')
    expect(text).not.toContain('没有找到相关概念')
  })

  it('① 概念接口返回无法识别的结构时按不可用处理，不退化成空结果', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockRejectedValue(
      new ApiError('知识图谱概念接口返回了无法识别的数据', 'GRAPH_CONTRACT_MISMATCH'),
    )
    const { wrapper } = await setup()
    await search(wrapper, '儿童发热')

    expect(currentState(wrapper)).toBe('unavailable')
    expect(wrapper.text()).toContain('无法识别的数据')
    expect(wrapper.text()).not.toContain('没有找到相关概念')
  })

  it('② 查询成功但没有概念：显示「没有找到相关概念」+ 建议 + 示例 + 开关关闭的说明', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockResolvedValue([])
    const { wrapper } = await setup()
    await search(wrapper, '不存在的词')

    expect(currentState(wrapper)).toBe('empty')
    const section = wrapper.find('[data-testid="kg-state-empty"]')
    expect(section.text()).toContain('没有找到相关概念')
    expect(section.text()).toContain('换一个更常见的说法')
    expect(section.text()).toContain('图谱读取开关关闭时')
    expect(wrapper.findAll('.kg-example').length).toBeGreaterThan(0)
    expect(knowledgeGraphApi.explore).not.toHaveBeenCalled()
  })

  it('② 概念存在但一条已发布关系都没有：显示「没有找到相关关系」，并保留概念可切换', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockResolvedValue([CONCEPT])
    vi.mocked(knowledgeGraphApi.explore).mockResolvedValue({
      available: true,
      revision: 4,
      relations: [],
    })
    const { wrapper } = await setup()
    await search(wrapper, '儿童发热')

    expect(currentState(wrapper)).toBe('empty')
    expect(wrapper.find('[data-testid="kg-state-empty"]').text()).toContain('没有找到相关关系')
    expect(wrapper.find('.kg-concept').text()).toContain('儿童发热')
  })

  it('③ 有结果：按关系类型分组，证据默认收起、可展开看到来源文档与定位标识', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockResolvedValue([CONCEPT])
    vi.mocked(knowledgeGraphApi.explore).mockResolvedValue({
      available: true,
      revision: 7,
      relations: [
        relation(),
        relation({
          claimId: 'claim-2',
          predicate: 'HAS_RED_FLAG',
          object: { id: 'flag-1', name: '精神差需及时就医', type: 'red_flag' },
          evidence: [evidence({ chunkId: 'chunk-5555' })],
        }),
      ],
    })
    const { wrapper } = await setup()
    await search(wrapper, '儿童发热')

    expect(currentState(wrapper)).toBe('ready')
    const ready = wrapper.find('[data-testid="kg-state-ready"]')
    expect(ready.text()).toContain('已发布关系（2 条）')
    expect(ready.text()).toContain('图谱版本 revision=7')
    expect(ready.text()).toContain('可能出现的表现（1）')
    expect(ready.text()).toContain('需要警惕的红旗提醒（1）')
    expect(ready.text()).toContain('不是诊断结论')

    // 概念已被标为选中，键盘用户不用再去猜当前查的是哪个概念。
    expect(wrapper.find('.kg-concept').attributes('aria-pressed')).toBe('true')

    // 证据默认收起（DOM 里没有），点开后才出现来源文档、章节、标识与链接。
    const toggles = wrapper.findAll('.kg-evidence-toggle')
    expect(toggles.length).toBe(2)
    expect(toggles[0].attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('.kg-evidence').exists()).toBe(false)

    await toggles[0].trigger('click')
    expect(toggles[0].attributes('aria-expanded')).toBe('true')
    const panel = wrapper.find('.kg-evidence')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('儿童发热的家庭护理科普')
    expect(panel.text()).toContain('什么时候需要就医')
    expect(panel.text()).toContain('doc-1111-2222')
    expect(panel.text()).toContain('chunk-3333-4444')
    const link = panel.find('a.kg-evidence__link')
    expect(link.attributes('href')).toBe('https://example.org/health/fever')
    expect(link.attributes('rel')).toContain('noopener')
    // 后端不返回正文片段，界面不得凭空生成摘录。
    expect(panel.text()).not.toContain('摘录')
  })

  it('③ 未审核/未发布的关系必须显著标注，已审核的不乱标', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockResolvedValue([CONCEPT])
    vi.mocked(knowledgeGraphApi.explore).mockResolvedValue({
      available: true,
      revision: 2,
      relations: [
        relation(),
        // 契约里目前没有审核字段；这里模拟后端将来把未审核关系放进了响应。
        relation({ claimId: 'claim-pending', reviewDecision: 'pending' }),
        relation({ claimId: 'claim-rejected', status: 'candidate', reviewDecision: 'rejected' }),
      ],
    })
    const { wrapper } = await setup()
    await search(wrapper, '儿童发热')

    const cards = wrapper.findAll('.kg-relation')
    expect(cards.length).toBe(3)
    expect(cards[0].classes()).not.toContain('kg-relation--unreviewed')
    expect(cards[0].text()).not.toContain(KNOWLEDGE_GRAPH_UNREVIEWED_NOTICE)

    for (const index of [1, 2]) {
      expect(cards[index].classes()).toContain('kg-relation--unreviewed')
      expect(cards[index].text()).toContain(KNOWLEDGE_GRAPH_UNREVIEWED_NOTICE)
    }
    expect(cards[1].text()).toContain('pending')
  })

  it('未知关系类型照实展示并说明后端扩展了枚举', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockResolvedValue([CONCEPT])
    vi.mocked(knowledgeGraphApi.explore).mockResolvedValue({
      available: true,
      revision: 1,
      relations: [relation({ claimId: 'claim-x', predicate: 'CAUSES' })],
    })
    const { wrapper } = await setup()
    await search(wrapper, '儿童发热')

    expect(currentState(wrapper)).toBe('ready')
    const group = wrapper.find('.kg-group')
    expect(group.attributes('data-predicate')).toBe('CAUSES')
    expect(group.text()).toContain('CAUSES')
    expect(group.text()).toContain('未登记的关系类型')
  })

  it('证据里不是 http(s) 的 url 不生成外链', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockResolvedValue([CONCEPT])
    vi.mocked(knowledgeGraphApi.explore).mockResolvedValue({
      available: true,
      revision: 1,
      relations: [relation({ evidence: [evidence({ url: null })] })],
    })
    const { wrapper } = await setup()
    await search(wrapper, '儿童发热')
    await wrapper.find('.kg-evidence-toggle').trigger('click')

    expect(wrapper.find('.kg-evidence__link').exists()).toBe(false)
    expect(wrapper.find('.kg-evidence__nourl').text()).toContain('未提供可打开的来源链接')
  })

  it('搜索词太短时本地拦下：不发请求、给出提示', async () => {
    const { wrapper } = await setup()
    await search(wrapper, '发')

    expect(knowledgeGraphApi.concepts).not.toHaveBeenCalled()
    expect(wrapper.find('#kg-query-error').text()).toContain('至少输入 2 个字符')
    expect(currentState(wrapper)).toBe('idle')
  })

  it('示例关键词直接发起查询，并且是真实请求（不是本地编结果）', async () => {
    vi.mocked(knowledgeGraphApi.concepts).mockResolvedValue([])
    const { wrapper } = await setup()

    await wrapper.findAll('.kg-example')[0].trigger('click')
    await flushPromises()

    expect(knowledgeGraphApi.concepts).toHaveBeenCalledWith('发热')
    expect((wrapper.find('#kg-query').element as HTMLInputElement).value).toBe('发热')
  })

  it('切换概念会重新查询该概念的关系', async () => {
    const second = { id: 'concept-2', name: '科学运动', type: 'topic' }
    vi.mocked(knowledgeGraphApi.concepts).mockResolvedValue([CONCEPT, second])
    vi.mocked(knowledgeGraphApi.explore).mockResolvedValue({
      available: true,
      revision: 3,
      relations: [relation({ subject: { id: 'concept-2', name: '科学运动', type: 'topic' } })],
    })
    const { wrapper } = await setup()
    await search(wrapper, '运动')

    expect(knowledgeGraphApi.explore).toHaveBeenLastCalledWith('concept-1')
    await wrapper.findAll('.kg-concept')[1].trigger('click')
    await flushPromises()

    expect(knowledgeGraphApi.explore).toHaveBeenLastCalledWith('concept-2')
    expect(wrapper.find('[data-testid="kg-state-ready"]').text()).toContain('科学运动')
  })
})