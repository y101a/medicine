import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessageBox } from 'element-plus'
import HomeView from './HomeView.vue'
import DashboardView from './DashboardView.vue'
import HistoryView from './HistoryView.vue'
import { useAuthStore } from '../stores/auth'
import { useConsultationsStore } from '../stores/consultations'
import { consultationsApi } from '../api/consultations'
import { modelsApi } from '../api/models'
import { ApiError } from '../api/http'

vi.mock('../api/consultations', () => ({ consultationsApi: {
  create: vi.fn(), send: vi.fn(), stream: vi.fn(), get: vi.fn(), messages: vi.fn(), list: vi.fn(), remove: vi.fn(),
} }))
vi.mock('../api/models', () => ({ modelsApi: { list: vi.fn() } }))
const conversation = { id: 'c1', title: '头痛', messageCount: 1, createdAt: '2026-09-06', updatedAt: '2026-09-06' }
const message = { id: 'm1', role: 'user' as const, content: '头痛', sequence: 1, createdAt: '2026-09-06' }
const answer = { id: 'm2', role: 'assistant' as const, content: '请先说明疼痛位置。', sequence: 2, provider: 'zhipuai', modelId: 'glm-4.7-flash', modelName: '智谱 GLM-4.7 Flash', generationStatus: 'completed' as const, answerFormat: 'plain' as const, medicalContent: true, sourceMessageId: null, createdAt: '2026-09-06' }
const aiModels = [
  { id: 'glm-4.7-flash', name: '智谱 GLM-4.7 Flash', provider: 'zhipuai', providerName: '智谱 AI', description: '免费轻量模型', isDefault: true, keySource: 'server' as const },
  { id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash', provider: 'deepseek', providerName: 'DeepSeek', description: '低价模型', isDefault: false, keySource: 'server' as const },
]
function authSetup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = { id: 'u1', username: 'tester', realName: '测试', gender: 'private', role: 'user', registeredAt: '2026-09-06' }
  return { pinia, auth }
}
async function setup(path = '/app/chat') {
  const { pinia, auth } = authSetup()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app/chat', component: HomeView },
      { path: '/app/consultations/:id', name: 'consultation', component: HomeView },
    ],
  })
  await router.push(path)
  const wrapper = mount({ template: '<router-view :key="$route.fullPath" />' }, {
    attachTo: document.body, global: { plugins: [pinia, router, ElementPlus] },
  })
  await flushPromises()
  return { wrapper, router, auth }
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(consultationsApi.create).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.send).mockResolvedValue(message)
  vi.mocked(consultationsApi.get).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [message], hasMore: false })
  vi.mocked(consultationsApi.list).mockResolvedValue({ items: [conversation], hasMore: false })
  vi.mocked(consultationsApi.stream).mockResolvedValue(answer)
  vi.mocked(modelsApi.list).mockResolvedValue(aiModels)
  HTMLElement.prototype.scrollTo = vi.fn()
})

describe('真实咨询界面', () => {
  it('首页展示当前用户与最近咨询，快捷入口会带入提问模板', async () => {
    const { pinia } = authSetup()
    const store = useConsultationsStore()
    store.items = [conversation]
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/app', component: DashboardView },
        { path: '/app/chat', component: { template: '<p>chat</p>' } },
      ],
    })
    await router.push('/app')
    const wrapper = mount(DashboardView, { global: { plugins: [pinia, router, ElementPlus] } })
    expect(wrapper.text()).toContain('测试，你好')
    expect(wrapper.text()).toContain('头痛')
    await wrapper.get('.quick-list button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/app/chat')
    expect(router.currentRoute.value.query.prompt).toBe('我想了解这些症状的可能原因：')
    wrapper.unmount()
  })

  it('保存失败保留输入，重试复用请求编号，成功后切换到持久会话地址', async () => {
    vi.mocked(consultationsApi.send)
      .mockRejectedValueOnce(new ApiError('保存超时', 'REQUEST_TIMEOUT'))
      .mockResolvedValueOnce(message)
    const { wrapper, router } = await setup()
    await wrapper.get('textarea').setValue('头痛')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('textarea').element.value).toBe('头痛')
    expect(wrapper.text()).toContain('保存超时')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(consultationsApi.create).toHaveBeenCalledTimes(1)
    expect(vi.mocked(consultationsApi.send).mock.calls[0]).toEqual(vi.mocked(consultationsApi.send).mock.calls[1])
    expect(router.currentRoute.value.path).toBe('/app/consultations/c1')
    expect(wrapper.get('textarea').element.value).toBe('')
    expect(wrapper.text()).toContain('已保存')
    wrapper.unmount()
  })
  it('流式显示回答，并允许用户停止生成', async () => {
    vi.mocked(consultationsApi.stream).mockImplementationOnce(
      async (_id, _requestId, _modelId, _answerFormat, signal, onDelta) => {
        onDelta('正在回答的内容')
        return await new Promise((_, reject) => {
          signal.addEventListener('abort', () => reject(new DOMException('已停止', 'AbortError')))
        })
      },
    )
    const { wrapper } = await setup()
    await wrapper.get('textarea').setValue('头痛两天')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('正在回答的内容')
    const stop = wrapper.get('button[aria-label="停止生成"]')
    await stop.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('回答已停止生成')
    expect(wrapper.find('button[aria-label="停止生成"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('联网超时与资料确实为空时给出不同提示，且不显示虚构引用', async () => {
    vi.mocked(consultationsApi.stream).mockImplementationOnce(
      async (_id, _requestId, _modelId, _format, _signal, _delta, onRetrieval) => {
        onRetrieval({
          status: 'empty', gateReason: 'medical_content',
          webSearchStatus: 'failed', webSearchErrorCode: 'WEB_SEARCH_TIMEOUT',
        })
        return answer
      },
    )
    const timeout = await setup('/app/consultations/c1')
    await timeout.wrapper.get('textarea').setValue('甲状腺结节科普')
    await timeout.wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(timeout.wrapper.get('.retrieval-notice').text()).toContain('官网搜索超时')
    expect(timeout.wrapper.find('.reference-sources').exists()).toBe(false)
    timeout.wrapper.unmount()

    vi.mocked(consultationsApi.stream).mockImplementationOnce(
      async (_id, _requestId, _modelId, _format, _signal, _delta, onRetrieval) => {
        onRetrieval({
          status: 'empty', gateReason: 'medical_content', webSearchStatus: 'empty',
        })
        return answer
      },
    )
    const noSources = await setup('/app/consultations/c1')
    await noSources.wrapper.get('textarea').setValue('甲状腺结节科普')
    await noSources.wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(noSources.wrapper.get('.retrieval-notice').text()).toContain('均未找到可引用')
    expect(noSources.wrapper.find('.reference-sources').exists()).toBe(false)
    noSources.wrapper.unmount()
  })
  it('普通聊天跳过医学检索时不显示资料不足提示', async () => {
    vi.mocked(consultationsApi.stream).mockImplementationOnce(
      async (_id, _requestId, _modelId, _format, _signal, _delta, onRetrieval) => {
        onRetrieval({
          status: 'skipped', gateReason: 'non_medical_content', webSearchStatus: 'skipped',
        })
        return answer
      },
    )
    const { wrapper } = await setup()
    await wrapper.get('textarea').setValue('你好')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('.retrieval-notice').exists()).toBe(false)
    wrapper.unmount()
  })
  it('泛疾病资料只有部分类型时提示不是完整清单', async () => {
    vi.mocked(consultationsApi.stream).mockImplementationOnce(
      async (_id, _requestId, _modelId, _format, _signal, _delta, onRetrieval) => {
        onRetrieval({
          status: 'completed', gateReason: 'medical_content',
          webSearchStatus: 'completed', coverageLimited: true,
        })
        return answer
      },
    )
    const { wrapper } = await setup('/app/consultations/c1')
    await wrapper.get('textarea').setValue('甲状腺相关疾病有哪些')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('.retrieval-notice').text()).toContain('不能视为完整清单')
    wrapper.unmount()
  })
  it('首次发送后跳转到新会话时仍保留本次无资料提示', async () => {
    vi.mocked(consultationsApi.stream).mockImplementationOnce(
      async (_id, _requestId, _modelId, _format, _signal, _delta, onRetrieval) => {
        onRetrieval({
          status: 'empty', gateReason: 'medical_content', webSearchStatus: 'empty',
        })
        return answer
      },
    )
    const { wrapper, router } = await setup()
    await wrapper.get('textarea').setValue('甲状腺结节科普')
    await wrapper.get('form').trigger('submit')
    await vi.waitFor(() => {
      expect(router.currentRoute.value.path).toBe('/app/consultations/c1')
      expect(wrapper.find('.retrieval-notice').exists()).toBe(true)
    })
    wrapper.unmount()
  })
  it('每条消息可以切换模型，并将所选模型发送给后端', async () => {
    const { wrapper } = await setup()
    const select = wrapper.findComponent({ name: 'ElSelect' })
    select.vm.$emit('update:modelValue', 'deepseek-v4-flash')
    await wrapper.get('textarea').setValue('请解释最近的头痛')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(consultationsApi.stream).toHaveBeenCalled()
    expect(vi.mocked(consultationsApi.stream).mock.calls[0]?.[2]).toBe('deepseek-v4-flash')
    expect(vi.mocked(consultationsApi.stream).mock.calls[0]?.[3]).toBe('plain')
    wrapper.unmount()
  })
  it('普通医疗回答后保留原回答，并按原回答追加病理科普卡片', async () => {
    const cardAnswer = {
      ...answer,
      id: 'm3',
      sequence: 3,
      content: '## 情况梳理\n头痛需要结合持续时间判断。',
      answerFormat: 'card' as const,
      sourceMessageId: answer.id,
    }
    vi.mocked(consultationsApi.stream)
      .mockResolvedValueOnce(answer)
      .mockResolvedValueOnce(cardAnswer)
    const { wrapper } = await setup('/app/consultations/c1')
    expect(wrapper.findComponent({ name: 'ElSwitch' }).exists()).toBe(false)
    expect(wrapper.get('.composer-bottom .navigator-trigger').text()).toContain('附近医院导航')
    await wrapper.get('textarea').setValue('头痛两天应该注意什么')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('是否生成一张病理科普卡片')
    expect(wrapper.text()).toContain('请先说明疼痛位置')
    await wrapper.get('.pathology-card-offer button').trigger('click')
    await flushPromises()
    expect(consultationsApi.send).toHaveBeenCalledTimes(1)
    expect(consultationsApi.stream).toHaveBeenCalledTimes(2)
    expect(vi.mocked(consultationsApi.stream).mock.calls[0]?.[3]).toBe('plain')
    expect(vi.mocked(consultationsApi.stream).mock.calls[1]?.[3]).toBe('card')
    expect(vi.mocked(consultationsApi.stream).mock.calls[1]?.[7]).toBe(answer.id)
    expect(wrapper.text()).toContain('请先说明疼痛位置')
    expect(wrapper.text()).toContain('头痛需要结合持续时间判断')
    expect(wrapper.find('.pathology-card-offer').exists()).toBe(false)
    wrapper.unmount()
  })
  it('模型超时时提示切换备用模型，确认后不重复保存问题并重新生成', async () => {
    const backupAnswer = {
      ...answer,
      provider: 'deepseek',
      modelId: 'deepseek-v4-flash',
      modelName: 'DeepSeek V4 Flash',
    }
    vi.mocked(consultationsApi.stream)
      .mockRejectedValueOnce(new ApiError('智谱 GLM-4.7 Flash 响应超时', 'AI_PROVIDER_TIMEOUT', 504))
      .mockResolvedValueOnce(backupAnswer)
    vi.mocked(consultationsApi.messages).mockResolvedValue({
      items: [message, backupAnswer],
      hasMore: false,
    })
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
      .mockResolvedValueOnce('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
    const { wrapper } = await setup()
    await wrapper.get('textarea').setValue('头痛应该注意什么')
    await wrapper.get('form').trigger('submit')
    await vi.waitFor(() => expect(wrapper.text()).toContain('请先说明疼痛位置'))
    expect(consultationsApi.stream).toHaveBeenCalledTimes(2)
    expect(vi.mocked(consultationsApi.stream).mock.calls.map(call => call[2]))
      .toEqual(['glm-4.7-flash', 'deepseek-v4-flash'])
    expect(consultationsApi.send).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('请先说明疼痛位置')
    confirm.mockRestore()
    wrapper.unmount()
  })
  it('直接打开会话地址可恢复消息，读取失败时禁止发送', async () => {
    const { wrapper } = await setup('/app/consultations/c1')
    expect(wrapper.text()).toContain('头痛')
    expect(consultationsApi.messages).toHaveBeenCalledWith('c1', undefined)
    wrapper.unmount()
    vi.mocked(consultationsApi.get).mockRejectedValue(new ApiError('无权访问', 'NOT_FOUND', 404))
    const failed = await setup('/app/consultations/other')
    expect(failed.wrapper.text()).toContain('无权访问')
    expect(failed.wrapper.get('textarea').element.disabled).toBe(true)
    failed.wrapper.unmount()
  })
  it('普通用户消息只显示为用户气泡，不会重复渲染为助手消息', async () => {
    const { wrapper } = await setup('/app/consultations/c1')
    expect(wrapper.findAll('.user-message')).toHaveLength(1)
    expect(wrapper.findAll('.assistant-message')).toHaveLength(0)
    wrapper.unmount()
  })
  it('将标准医疗回答渲染成分区卡片，并突出就医提示', async () => {
    const cardAnswer = {
      ...answer,
      content: `## 情况梳理
- 头痛已持续两天，并伴有轻微恶心。
## 可能相关的常见原因
- 紧张性头痛或偏头痛都可能出现类似表现。
## 现在可以怎么做
- 保证休息并记录疼痛变化。
## 建议尽快就医的情况
- 若突然剧烈头痛或出现肢体无力，请及时就医。
以上仅供健康科普参考，不作确诊，不能替代医生面诊。`,
    }
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [message, cardAnswer], hasMore: false })
    const { wrapper } = await setup('/app/consultations/c1')
    expect(wrapper.find('.answer-card').exists()).toBe(true)
    expect(wrapper.text()).toContain('根据您提供的信息')
    expect(wrapper.text()).toContain('可能相关的常见原因')
    expect(wrapper.find('.answer-section--warning').text()).toContain('突然剧烈头痛')
    expect(wrapper.text()).toContain('不能替代医生面诊')
    wrapper.unmount()
  })
  it('知识概览卡按常见类型展示，并清理模型输出的加粗符号', async () => {
    const overviewAnswer = {
      ...answer,
      content: `## 问题概览
- 甲状腺相关问题可以从功能、结构等方向了解。
## 常见类型
- **功能变化**：甲亢与甲减。
- **结构变化**：甲状腺结节。
- **炎症问题**：甲状腺炎。
## 区分要点
- 具体情况需结合检查结果，由医生评估。
以上仅供健康科普参考，不作确诊，不能替代医生面诊。`,
    }
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [message, overviewAnswer], hasMore: false })
    const { wrapper } = await setup('/app/consultations/c1')
    expect(wrapper.find('.answer-card').exists()).toBe(true)
    expect(wrapper.text()).toContain('先了解常见情况')
    expect(wrapper.find('.answer-section--types').findAll('li')).toHaveLength(3)
    expect(wrapper.find('.answer-section--types').text()).not.toContain('**')
    wrapper.unmount()
  })
  it('普通回答直接显示对话内容，不套知识卡栏目', async () => {
    const plainAnswer = {
      ...answer,
      content: '甲状腺相关问题常见涉及功能变化、结节和炎症等，具体情况需要结合检查结果判断。',
    }
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [message, plainAnswer], hasMore: false })
    const { wrapper } = await setup('/app/consultations/c1')
    expect(wrapper.find('.answer-card').exists()).toBe(false)
    expect(wrapper.find('.raw-answer').text()).toContain('甲状腺相关问题常见涉及')
    wrapper.unmount()
  })
  it('只在回答使用资料时显示可折叠来源，并区分审核来源与开发原型', async () => {
    const citedAnswer = {
      ...answer,
      citations: [
        {
          referenceNumber: 1, sourceKey: 'nhc', organization: '国家卫生健康委员会', title: '居民健康素养资料',
          canonicalUrl: 'https://www.nhc.gov.cn/example', sectionTitle: '合理用药',
          similarity: 0.82, trustLevel: 'approved' as const,
        },
        {
          referenceNumber: 2, sourceKey: 'prototype', organization: '项目开发者', title: '合理用药原型资料',
          canonicalUrl: 'https://prototype.invalid/medical-knowledge/medicine-use',
          sectionTitle: '普通感冒', similarity: 0.79, trustLevel: 'prototype' as const,
        },
      ],
    }
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [message, citedAnswer], hasMore: false })
    const { wrapper } = await setup('/app/consultations/c1')
    const sources = wrapper.get('details.reference-sources')
    expect(sources.get('summary').text()).toContain('参考资料 2 条')
    expect(sources.text()).toContain('国家卫生健康委员会')
    expect(sources.text()).toContain('未经医学专业审核')
    expect(sources.findAll('a')).toHaveLength(1)
    expect(sources.get('a').attributes('href')).toBe('https://www.nhc.gov.cn/example')
    wrapper.unmount()

    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [message, answer], hasMore: false })
    const withoutSources = await setup('/app/consultations/c1')
    expect(withoutSources.wrapper.find('.reference-sources').exists()).toBe(false)
    withoutSources.wrapper.unmount()
  })
  it('结构化追问卡支持选择和提交，并将补充信息作为一条新消息发送', async () => {
    const followUpAnswer = {
      ...answer,
      content: '请补充以下症状信息',
      followUp: {
        intro: '为了更准确地提供科普信息，请补充以下情况',
        questions: [
          { id: 'location', label: '疼痛位置', type: 'single_choice' as const, required: true, options: [
            { value: 'one_side', label: '单侧' }, { value: 'both_sides', label: '双侧' },
          ] },
          { id: 'severity', label: '疼痛程度', type: 'scale' as const, required: true, options: [], min: 1, max: 10 },
        ],
      },
    }
    const supplemented = { ...message, id: 'm3', content: '补充信息', sequence: 3 }
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [message, followUpAnswer], hasMore: false })
    vi.mocked(consultationsApi.send).mockResolvedValue(supplemented)
    const { wrapper } = await setup('/app/consultations/c1')
    expect(wrapper.find('.follow-up-card').exists()).toBe(true)
    const choices = wrapper.findAll('.choices button')
    await choices[0]!.trigger('click')
    await wrapper.get('.submit-follow-up').trigger('click')
    await flushPromises()
    expect(consultationsApi.send).toHaveBeenCalledTimes(1)
    expect(vi.mocked(consultationsApi.send).mock.calls[0]?.[1]).toContain('疼痛位置：单侧')
    expect(vi.mocked(consultationsApi.send).mock.calls[0]?.[1]).toContain('疼痛程度：6')
    expect(consultationsApi.stream).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('无可用模型时仍执行紧急预检，展示分流卡且不请求模型', async () => {
    const emergencyMessage = {
      ...message,
      content: '突然胸痛，喘不上气',
      triage: {
        level: 'emergency' as const,
        title: '可能存在紧急情况',
        summary: '系统从您的描述中检测到需要优先处理的危险信号。',
        reasons: ['胸痛或胸部明显压迫感', '明显呼吸困难或窒息'],
        actions: ['请立即拨打中国大陆急救电话 120，并向调度员说明症状和所在位置。'],
        ruleIds: ['acute_chest_pain', 'severe_breathing_problem'],
        assessedAt: '2026-09-10T00:00:00Z',
      },
    }
    vi.mocked(modelsApi.list).mockResolvedValue([])
    vi.mocked(consultationsApi.send).mockResolvedValue(emergencyMessage)
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [emergencyMessage], hasMore: false })
    const { wrapper } = await setup()
    await wrapper.get('textarea').setValue('突然胸痛，喘不上气')
    await wrapper.get('form').trigger('submit')
    await vi.waitFor(() => expect(wrapper.find('.emergency-card').exists()).toBe(true))
    expect(wrapper.text()).toContain('可能存在紧急情况')
    expect(wrapper.get('a[href="tel:120"]').text()).toBe('拨打 120')
    expect(consultationsApi.stream).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('退出时清空列表，较晚到达的旧用户响应不会重新显示', async () => {
    const { auth } = authSetup()
    const store = useConsultationsStore()
    let finish!: (page: { items: typeof conversation[]; hasMore: boolean }) => void
    vi.mocked(consultationsApi.list).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const pending = store.load()
    auth.clearSession()
    finish({ items: [conversation], hasMore: false })
    await pending
    expect(store.items).toEqual([])
    expect(store.loading).toBe(false)
  })
  it('删除需要确认，成功后历史列表刷新为空', async () => {
    const { pinia } = authSetup()
    const router = createRouter({
      history: createMemoryHistory(), routes: [{ path: '/app/history', component: HistoryView }],
    })
    await router.push('/app/history')
    const wrapper = mount({ template: '<router-view />' }, {
      global: { plugins: [pinia, router, ElementPlus] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('头痛')
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(consultationsApi.remove).not.toHaveBeenCalled()
    confirm.mockResolvedValueOnce('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
    vi.mocked(consultationsApi.remove).mockResolvedValue()
    vi.mocked(consultationsApi.list).mockResolvedValue({ items: [], hasMore: false })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(consultationsApi.remove).toHaveBeenCalledWith('c1')
    expect(wrapper.text()).toContain('还没有咨询记录')
    confirm.mockRestore()
    wrapper.unmount()
  })
})
