import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import HomeView from './HomeView.vue'
import { useAuthStore } from '../stores/auth'
import { consultationsApi } from '../api/consultations'
import { modelsApi } from '../api/models'
import { attachmentsApi } from '../api/attachments'
import { imageGenerationsApi } from '../api/imageGenerations'
import { ApiError } from '../api/http'
import { IMAGE_GENERATION_DISCLAIMER } from '../types/imageGenerations'
import type { ImageGeneration } from '../types/imageGenerations'
import type { Message } from '../types/consultations'

/**
 * AI 科普配图前端的视图级验证（方案 `IMAGE_GENERATION_PLAN.md` §8.2）。
 *
 * **后端尚未落地**：这里全部走接口桩，验证的是「前端是否按契约调用、是否按契约展示」，
 * 不代表真实链路可用。真实联调必须等 Codex 冻结接口后再做。
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
  // 说明版本是契约固定值，必须与真实模块一致，否则请求体会带上 undefined。
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

const conversation = { id: 'c1', title: '头痛', messageCount: 1, createdAt: '2026-09-24', updatedAt: '2026-09-24' }
const userMessage: Message = { id: 'm1', role: 'user', content: '帮我看看', sequence: 1, createdAt: '2026-09-24' }

/** 合格来源：已完成 + 医疗类 + 无追问卡 + 非紧急分流。 */
const medicalAnswer: Message = {
  id: 'a1', role: 'assistant', content: '科普回答', sequence: 2,
  generationStatus: 'completed', medicalContent: true, createdAt: '2026-09-24T10:00:00Z',
}
/** 普通闲聊：`medicalContent` 不为 true，不给入口。 */
const chitChat: Message = { ...medicalAnswer, id: 'a2', medicalContent: false }
/** 追问卡：不给入口（用户还没补充信息）。 */
const followUpAnswer: Message = {
  ...medicalAnswer, id: 'a3',
  followUp: { intro: '', questions: [] },
}
/** 生成中断：不给入口。 */
const interrupted: Message = { ...medicalAnswer, id: 'a4', generationStatus: 'failed' }
/** 紧急分流：不给入口（此时最该做的是就医）。 */
const triageAnswer: Message = {
  ...medicalAnswer, id: 'a5',
  triage: {
    level: 'emergency', title: '需要马上就医', summary: 's', reasons: [], actions: [],
    ruleIds: [], assessedAt: '2026-09-24T10:00:00Z',
  },
}

const activeTask: ImageGeneration = {
  id: 'g1', sourceMessageId: 'a1', status: 'submitted',
  style: 'medical_illustration', aspectRatio: '4:3', model: 'wan2.6-t2i',
  imageAvailable: false, imageExpiresAt: null,
  createdAt: '2026-09-24T10:00:00Z', updatedAt: '2026-09-24T10:00:00Z',
}
const completedTask: ImageGeneration = {
  ...activeTask, status: 'completed', imageAvailable: true,
  imageExpiresAt: '2026-12-23T10:00:00Z',
}

async function setup(messages: Message[] = [userMessage, medicalAnswer]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = { id: 'u1', username: 'tester', realName: '测试', gender: 'private', role: 'user', registeredAt: '2026-09-24' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app/chat', component: HomeView },
      { path: '/app/consultations/:id', name: 'consultation', component: HomeView },
    ],
  })
  await router.push('/app/consultations/c1')
  vi.mocked(consultationsApi.messages).mockResolvedValue({ items: messages, hasMore: false })
  const wrapper = mount({ template: '<router-view :key="$route.fullPath" />' }, {
    attachTo: document.body, global: { plugins: [pinia, router, ElementPlus] },
  })
  await flushPromises()
  return { wrapper, router }
}

function offerButton() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('.image-generation-offer button'))
    .find(button => button.textContent?.includes('生成科普配图'))
}

function dialogButton(label: string) {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('.image-generation-dialog button'))
    .find(button => button.textContent?.includes(label))
}

function agreeDialogNotice() {
  document.querySelector<HTMLInputElement>('.image-generation-dialog input[type="checkbox"]')?.click()
}

async function fillPrompt(text = '一张展示呼吸道与肺部关系的医学科普插画') {
  const textarea = document.querySelector<HTMLTextAreaElement>('.image-generation-dialog textarea')
  if (!textarea) throw new Error('生成弹窗没有渲染出描述输入框')
  textarea.value = text
  textarea.dispatchEvent(new Event('input'))
  await flushPromises()
}

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  vi.mocked(consultationsApi.create).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.get).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [userMessage], hasMore: false })
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

describe('生成入口的显示条件（方案 §3.2）', () => {
  it('只在已完成的医疗类回答下方出现，追问卡/中断/紧急分流/闲聊都不出现', async () => {
    await setup([userMessage, medicalAnswer, chitChat, followUpAnswer, interrupted, triageAnswer])
    const offers = document.querySelectorAll('.image-generation-offer')
    expect(offers).toHaveLength(1)
    expect(offers[0].textContent).toContain('每次生成可能产生费用')
  })

  it('点入口只打开确认弹窗，不发任何请求（不自动生成、不默认计费）', async () => {
    await setup()
    offerButton()?.click()
    await flushPromises()
    expect(document.querySelector('.image-generation-dialog')).not.toBeNull()
    expect(imageGenerationsApi.create).not.toHaveBeenCalled()
  })
})

describe('确认弹窗', () => {
  it('未勾选说明、没写描述时不能提交，也不会创建任务', async () => {
    await setup()
    offerButton()?.click()
    await flushPromises()
    await fillPrompt()
    expect(dialogButton('确认生成')?.disabled).toBe(true)
    dialogButton('确认生成')?.click()
    await flushPromises()
    expect(imageGenerationsApi.create).not.toHaveBeenCalled()

    agreeDialogNotice()
    await flushPromises()
    expect(dialogButton('确认生成')?.disabled).toBe(false)
  })

  it('提交后按契约发一次请求：幂等键、说明版本、来源回答、风格与比例', async () => {
    await setup()
    offerButton()?.click()
    await flushPromises()
    await fillPrompt('  一张呼吸道示意图  ')
    agreeDialogNotice()
    await flushPromises()
    dialogButton('确认生成')?.click()
    await flushPromises()

    expect(imageGenerationsApi.create).toHaveBeenCalledTimes(1)
    const [cid, payload] = vi.mocked(imageGenerationsApi.create).mock.calls[0]
    expect(cid).toBe('c1')
    expect(payload.clientRequestId).toMatch(/[0-9a-f-]{36}/)
    expect(payload.sourceMessageId).toBe('a1')
    expect(payload.noticeAccepted).toBe(true)
    expect(payload.noticeVersion).toBe('image-generation-v1')
    expect(payload.prompt).toBe('一张呼吸道示意图')
    expect(payload.style).toBe('medical_illustration')
    expect(payload.aspectRatio).toBe('4:3')
    // 弹窗关闭、卡片进入「等待生成」
    expect(document.querySelector('.generated-image-card__status')?.textContent).toContain('等待生成')
  })

  it('重复点击不会重复创建任务（幂等键只在这一次提交里用）', async () => {
    await setup()
    offerButton()?.click()
    await flushPromises()
    await fillPrompt()
    agreeDialogNotice()
    await flushPromises()
    dialogButton('确认生成')?.click()
    dialogButton('确认生成')?.click()
    await flushPromises()
    expect(imageGenerationsApi.create).toHaveBeenCalledTimes(1)
  })
})

describe('任务状态与成品', () => {
  it('轮询到完成后取回成品，显示免责声明与固定下载文件名', async () => {
    await setup()
    offerButton()?.click()
    await flushPromises()
    await fillPrompt()
    agreeDialogNotice()
    await flushPromises()

    vi.useFakeTimers()
    dialogButton('确认生成')?.click()
    await vi.advanceTimersByTimeAsync(0)
    // 退避首档 2 秒，之后按契约上限 5 秒。
    vi.mocked(imageGenerationsApi.get).mockResolvedValue(completedTask)
    await vi.advanceTimersByTimeAsync(2_000)

    expect(imageGenerationsApi.get).toHaveBeenCalledWith('g1')
    expect(imageGenerationsApi.content).toHaveBeenCalledWith('g1')
    const image = document.querySelector<HTMLImageElement>('.generated-image-card__image')
    expect(image?.getAttribute('src')).toBe('blob:generated')
    expect(document.querySelector('.generated-image-card__disclaimer')?.textContent)
      .toContain(IMAGE_GENERATION_DISCLAIMER)
    const link = document.querySelector<HTMLAnchorElement>('.generated-image-card__download')
    expect(link?.getAttribute('download')).toBe('AI科普配图-20260924.webp')
  })

  it('成品已过期（410）时按过期展示，且不再给出下载入口', async () => {
    vi.mocked(imageGenerationsApi.list).mockResolvedValue([completedTask])
    vi.mocked(imageGenerationsApi.content).mockRejectedValue(
      new ApiError('已过期', 'GENERATED_IMAGE_EXPIRED', 410),
    )
    await setup()

    expect(imageGenerationsApi.content).toHaveBeenCalledWith('g1')
    expect(document.querySelector('.generated-image-card__status')?.textContent).toContain('已过期')
    expect(document.querySelector('.generated-image-card__notice')?.textContent).toContain('90 天保留期')
    expect(document.querySelector('.generated-image-card__download')).toBeNull()
    expect(document.querySelector('.generated-image-card__image')).toBeNull()
  })

  it('轮询失败只给提示，不把任务改写成失败（服务端才是状态的事实来源）', async () => {
    await setup()
    offerButton()?.click()
    await flushPromises()
    await fillPrompt()
    agreeDialogNotice()
    await flushPromises()

    vi.useFakeTimers()
    dialogButton('确认生成')?.click()
    await vi.advanceTimersByTimeAsync(0)
    vi.mocked(imageGenerationsApi.get).mockRejectedValue(
      new ApiError('服务暂时不可用', 'IMAGE_GENERATION_PROVIDER_UNAVAILABLE', 503),
    )
    await vi.advanceTimersByTimeAsync(2_000)

    expect(document.querySelector('.generated-image-card__status')?.textContent).toContain('等待生成')
    expect(document.querySelector('.generated-image-card__notice')?.textContent)
      .toContain('图片生成服务暂时不可用')
  })
})