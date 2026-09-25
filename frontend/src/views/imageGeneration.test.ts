import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import HomeView from './HomeView.vue'
import { useAuthStore } from '../stores/auth'
import { consultationsApi } from '../api/consultations'
import { modelsApi } from '../api/models'
import { attachmentsApi } from '../api/attachments'
import { imageGenerationsApi, IMAGE_GENERATION_NOTICE_VERSION } from '../api/imageGenerations'
import { ApiError } from '../api/http'
import { IMAGE_GENERATION_NOTICE_STORAGE_KEY } from '../stores/composerHints'
import { IMAGE_GENERATION_DISCLAIMER } from '../types/imageGenerations'
import type { ImageGeneration } from '../types/imageGenerations'
import type { Message } from '../types/consultations'

/**
 * 自然语言触发的 AI 科普配图（方案 `IMAGE_GENERATION_PLAN.md` §7.1/§7.2、`COORDINATION.md` 第 175 行）。
 *
 * 2026-09-25 起没有回答底部的生成按钮：用户在对话里说「帮我生成一张关于人体结构的图片」，
 * 服务端 `/messages` 响应给 `imageGenerationIntent=true`，前端**跳过 `/stream`** 直接创建任务，
 * 任务卡渲染在该用户消息下；首次使用先过一遍费用/标识协议，确认后按协议版本记忆。
 *
 * 全部走接口桩：这里证明的是「前端按契约调用与渲染」，真实链路另有联调验证。
 */
vi.mock('../api/consultations', () => ({ consultationsApi: {
  create: vi.fn(), send: vi.fn(), stream: vi.fn(), get: vi.fn(), messages: vi.fn(), list: vi.fn(), remove: vi.fn(),
} }))
vi.mock('../api/models', () => ({ modelsApi: { list: vi.fn() } }))
vi.mock('../api/voice', () => ({ voiceApi: { transcribe: vi.fn() } }))
vi.mock('../api/attachments', () => ({ attachmentsApi: {
  upload: vi.fn(), uploadImage: vi.fn(), content: vi.fn(), list: vi.fn(), remove: vi.fn(),
} }))
vi.mock('../api/imageGenerations', () => ({
  // 说明版本是契约固定值，必须与真实模块一致，否则请求体会带上错的版本而被服务端 422。
  IMAGE_GENERATION_NOTICE_VERSION: 'image-generation-v1',
  imageGenerationsApi: {
    create: vi.fn(), get: vi.fn(), list: vi.fn(), content: vi.fn(), remove: vi.fn(),
  },
}))
vi.mock('../composables/useVoiceRecorder', async () => {
  const { ref } = await import('vue')
  return { useVoiceRecorder: () => ({
    state: ref('idle'), seconds: ref(0), error: ref(''), supported: false,
    start: vi.fn(), stop: vi.fn(), cancel: vi.fn(), reset: vi.fn(),
  }) }
})

const conversation = { id: 'c1', title: '头痛', messageCount: 1, createdAt: '2026-09-25', updatedAt: '2026-09-25' }
/** 命中意图的用户消息：服务端已经判定 true（判定规则见 image_generation_intent.py）。 */
const intentMessage: Message = {
  id: 'u9', role: 'user', content: '帮我生成一张关于人体结构的图片', sequence: 3,
  imageGenerationIntent: true, createdAt: '2026-09-25T10:00:00Z',
}
/** 同一句话但服务端判定 false（例如「帮我生成一张风景图片」）。 */
const plainMessage: Message = {
  ...intentMessage, id: 'u8', content: '帮我生成一张风景图片', imageGenerationIntent: false,
}
const assistantAnswer: Message = {
  id: 'a1', role: 'assistant', content: '人体结构包括……', sequence: 2,
  generationStatus: 'completed', medicalContent: true, createdAt: '2026-09-25T09:00:00Z',
}
const activeTask: ImageGeneration = {
  id: 'g1', sourceMessageId: 'u9', status: 'submitted',
  style: 'medical_illustration', aspectRatio: '4:3', model: 'wan2.6-t2i',
  imageAvailable: false, imageExpiresAt: null,
  createdAt: '2026-09-25T10:00:00Z', updatedAt: '2026-09-25T10:00:00Z',
}
const completedTask: ImageGeneration = {
  ...activeTask, status: 'completed', imageAvailable: true,
  imageExpiresAt: '2026-12-24T10:00:00Z',
}

async function setup(path = '/app/chat', messages?: Message[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = { id: 'u1', username: 'tester', realName: '测试', gender: 'private', role: 'user', registeredAt: '2026-09-25' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app/chat', component: HomeView },
      { path: '/app/consultations/:id', name: 'consultation', component: HomeView },
    ],
  })
  await router.push(path)
  // 只有显式传入消息时才覆盖这个 mock：否则会把用例里已经排好的历史消息清空。
  if (messages) {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: messages, hasMore: false })
  }
  const wrapper = mount({ template: '<router-view :key="$route.fullPath" />' }, {
    attachTo: document.body, global: { plugins: [pinia, router, ElementPlus] },
  })
  await flushPromises()
  // 会话详情装载、历史消息渲染和 `loadHistory` 是三条并行的异步链：
  // 断言 DOM 之前要多冲一次，否则任务卡还没挂上去。
  await flushPromises()
  return { wrapper, router }
}

/** 在输入区输入并按 Enter 提交（等价于点发送按钮）。 */
async function sendMessage(wrapper: VueWrapper, text: string) {
  await wrapper.get('textarea').setValue(text)
  await wrapper.get('form.composer').trigger('submit')
  await flushPromises()
}

function dialogConfirmButton() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('.image-generation-dialog button'))
    .find(button => button.textContent?.includes('同意并生成'))
}

function agreeDialog() {
  document.querySelector<HTMLInputElement>('.image-generation-dialog input[type="checkbox"]')?.click()
}

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  vi.mocked(consultationsApi.create).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.send).mockResolvedValue(intentMessage)
  vi.mocked(consultationsApi.stream).mockResolvedValue(assistantAnswer)
  vi.mocked(consultationsApi.get).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [], hasMore: false })
  vi.mocked(consultationsApi.list).mockResolvedValue({ items: [conversation], hasMore: false })
  vi.mocked(modelsApi.list).mockResolvedValue([
    { id: 'glm-4.7-flash', name: '智谱 GLM-4.7 Flash', provider: 'zhipuai', providerName: '智谱 AI', description: '', isDefault: true, keySource: 'server' },
  ])
  vi.mocked(attachmentsApi.list).mockResolvedValue([])
  vi.mocked(imageGenerationsApi.list).mockResolvedValue([])
  vi.mocked(imageGenerationsApi.create).mockResolvedValue(activeTask)
  vi.mocked(imageGenerationsApi.content).mockResolvedValue(new Blob(['webp'], { type: 'image/webp' }))
  vi.mocked(imageGenerationsApi.remove).mockResolvedValue(undefined)
  // jsdom 没有 Object URL；判定用的仍是真实的创建与释放调用。
  Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:generated'), configurable: true })
  Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), configurable: true })
  HTMLElement.prototype.scrollTo = vi.fn()
})

afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('自然语言触发', () => {
  it('命中意图时跳过 /stream，以该用户消息为来源直接创建任务，卡片挂在该消息下', async () => {
    localStorage.setItem(IMAGE_GENERATION_NOTICE_STORAGE_KEY, IMAGE_GENERATION_NOTICE_VERSION)
    const { wrapper } = await setup()

    await sendMessage(wrapper, '帮我生成一张关于人体结构的图片')

    expect(consultationsApi.stream).not.toHaveBeenCalled()
    expect(imageGenerationsApi.create).toHaveBeenCalledTimes(1)
    const [cid, payload] = vi.mocked(imageGenerationsApi.create).mock.calls[0]
    expect(cid).toBe('c1')
    expect(payload.sourceMessageId).toBe('u9')
    expect(payload.prompt).toBe('帮我生成一张关于人体结构的图片')
    expect(payload.noticeAccepted).toBe(true)
    expect(payload.noticeVersion).toBe('image-generation-v1')
    // 风格/比例交给服务端默认值，前端不再提供选择。
    expect('style' in payload).toBe(false)
    expect('aspectRatio' in payload).toBe(false)

    expect(document.querySelector('.user-message')?.textContent).toContain('人体结构')
    expect(document.querySelector('.generated-image-card__status')?.textContent).toContain('等待生成')
  })

  it('未命中（普通文生图/普通提问）照常走 /stream，不创建任何任务', async () => {
    const { wrapper } = await setup()
    vi.mocked(consultationsApi.send).mockResolvedValue(plainMessage)

    await sendMessage(wrapper, '帮我生成一张风景图片')

    expect(consultationsApi.stream).toHaveBeenCalledTimes(1)
    expect(imageGenerationsApi.create).not.toHaveBeenCalled()
    expect(document.querySelector('.generated-image-card')).toBeNull()
  })
})

describe('首次使用的一次性协议', () => {
  it('首次命中自动弹出协议，未勾选不能生成；确认后提交并记住协议版本', async () => {
    const { wrapper } = await setup()
    expect(localStorage.getItem(IMAGE_GENERATION_NOTICE_STORAGE_KEY)).toBeNull()

    await sendMessage(wrapper, '帮我生成一张关于人体结构的图片')

    expect(document.querySelector('.image-generation-dialog')).not.toBeNull()
    expect(imageGenerationsApi.create).not.toHaveBeenCalled()
    expect(dialogConfirmButton()?.disabled).toBe(true)

    agreeDialog()
    await flushPromises()
    expect(dialogConfirmButton()?.disabled).toBe(false)
    dialogConfirmButton()?.click()
    await flushPromises()

    expect(imageGenerationsApi.create).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(IMAGE_GENERATION_NOTICE_STORAGE_KEY)).toBe(IMAGE_GENERATION_NOTICE_VERSION)
  })

  it('记录的是协议版本：旧版本不算已确认，会再弹一次', async () => {
    localStorage.setItem(IMAGE_GENERATION_NOTICE_STORAGE_KEY, 'image-generation-v0')
    const { wrapper } = await setup()

    await sendMessage(wrapper, '帮我生成一张关于人体结构的图片')

    expect(document.querySelector('.image-generation-dialog')).not.toBeNull()
    expect(imageGenerationsApi.create).not.toHaveBeenCalled()
  })

  it('提交被拒时把受控原因显示在弹窗里，且不回退聊天模型', async () => {
    const { wrapper } = await setup()
    vi.mocked(imageGenerationsApi.create).mockRejectedValue(
      new ApiError('图片生成次数已达限制，请稍后再试', 'IMAGE_GENERATION_RATE_LIMITED', 429),
    )

    await sendMessage(wrapper, '帮我生成一张关于人体结构的图片')
    agreeDialog()
    await flushPromises()
    dialogConfirmButton()?.click()
    await flushPromises()

    expect(document.querySelector('.image-generation-dialog__error')?.textContent)
      .toContain('生成次数已达上限')
    expect(consultationsApi.stream).not.toHaveBeenCalled()
  })
})

describe('任务卡与历史恢复', () => {
  it('刷新后按 sourceMessageId 恢复任务，取回成品并显示免责声明与固定下载名', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(imageGenerationsApi.list).mockResolvedValue([completedTask])

    await setup('/app/consultations/c1')

    expect(imageGenerationsApi.list).toHaveBeenCalledWith('c1')
    expect(imageGenerationsApi.content).toHaveBeenCalledWith('g1')
    expect(document.querySelector('.generated-image-card__image')?.getAttribute('src')).toBe('blob:generated')
    expect(document.querySelector('.generated-image-card__disclaimer')?.textContent)
      .toContain(IMAGE_GENERATION_DISCLAIMER)
    expect(document.querySelector<HTMLAnchorElement>('.generated-image-card__download')?.getAttribute('download'))
      .toBe('AI科普配图-20260925.webp')
  })

  it('成品已过期（410）时按过期展示，且不再给下载入口', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(imageGenerationsApi.list).mockResolvedValue([completedTask])
    vi.mocked(imageGenerationsApi.content).mockRejectedValue(
      new ApiError('已过期', 'GENERATED_IMAGE_EXPIRED', 410),
    )

    await setup('/app/consultations/c1')

    expect(document.querySelector('.generated-image-card__status')?.textContent).toContain('已过期')
    expect(document.querySelector('.generated-image-card__notice')?.textContent).toContain('90 天保留期')
    expect(document.querySelector('.generated-image-card__download')).toBeNull()
  })

  it('轮询失败只给提示，不把任务改写成失败（服务端才是状态的事实来源）', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(imageGenerationsApi.list).mockResolvedValue([activeTask])

    await setup('/app/consultations/c1')
    vi.mocked(imageGenerationsApi.get).mockRejectedValue(
      new ApiError('服务暂时不可用', 'IMAGE_GENERATION_PROVIDER_UNAVAILABLE', 503),
    )
    // 历史恢复时排的是**真实**计时器（退避首档 2 秒），所以等它跑完一轮再断言。
    await new Promise(resolve => setTimeout(resolve, 2_100))
    await flushPromises()

    expect(document.querySelector('.generated-image-card__status')?.textContent).toContain('等待生成')
    expect(document.querySelector('.generated-image-card__notice')?.textContent)
      .toContain('图片生成服务暂时不可用')
  })
})