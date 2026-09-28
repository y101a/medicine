import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import HomeView from './HomeView.vue'
import GeneratedDocumentCard from '../components/GeneratedDocumentCard.vue'
import { useAuthStore } from '../stores/auth'
import { consultationsApi } from '../api/consultations'
import { modelsApi } from '../api/models'
import { attachmentsApi } from '../api/attachments'
import { documentGenerationsApi, DOCUMENT_GENERATION_NOTICE_VERSION } from '../api/documentGenerations'
import { imageGenerationsApi } from '../api/imageGenerations'
import { ApiError } from '../api/http'
import { DOCUMENT_GENERATION_NOTICE_STORAGE_KEY } from '../stores/composerHints'
import {
  DOCUMENT_GENERATION_DISCLAIMER,
  DOCUMENT_GENERATION_STAGE_HINTS,
  DOCUMENT_GENERATION_STAGES,
  DOCUMENT_GENERATION_STATUS_LABELS,
  documentGenerationStageIndex,
  formatDocumentWait,
  type DocumentGeneration,
  type DocumentGenerationFile,
  type DocumentGenerationStatus,
} from '../types/documentGenerations'
import type { Message } from '../types/consultations'

/**
 * 自然语言触发的 PPT/Word 科普文档生成（方案 `PPT_WORD_PLAN.md` §8、§9.2）。
 *
 * 与配图同一套触发方式：用户在对话里说「帮我生成一份高血压预防的 PPT」，服务端 `/messages`
 * 响应给 `documentGenerationIntent=true`，前端**跳过 `/stream`** 直接创建任务，任务卡渲染在
 * 该用户消息下；首次使用先过一遍说明，确认后按说明版本记忆。
 *
 * 全部走接口桩：这里证明的是「前端按契约调用与渲染」，真实链路要等后端落地后才能验。
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
  IMAGE_GENERATION_NOTICE_VERSION: 'image-generation-v1',
  imageGenerationsApi: {
    create: vi.fn(), get: vi.fn(), list: vi.fn(), content: vi.fn(), remove: vi.fn(),
  },
}))
vi.mock('../api/documentGenerations', () => ({
  // 说明版本是契约固定值，必须与真实模块一致，否则请求体带上错版本会被服务端 422。
  DOCUMENT_GENERATION_NOTICE_VERSION: 'document-generation-v1',
  documentGenerationsApi: {
    create: vi.fn(), createWithTemplate: vi.fn(), get: vi.fn(), list: vi.fn(), content: vi.fn(), remove: vi.fn(),
  },
}))
vi.mock('../composables/useVoiceRecorder', async () => {
  const { ref } = await import('vue')
  return { useVoiceRecorder: () => ({
    state: ref('idle'), seconds: ref(0), error: ref(''), supported: false,
    start: vi.fn(), stop: vi.fn(), cancel: vi.fn(), reset: vi.fn(),
  }) }
})

const conversation = { id: 'c1', title: '高血压预防', messageCount: 1, createdAt: '2026-09-27', updatedAt: '2026-09-27' }
/** 命中意图的用户消息：服务端已经判定 true（规则见 `document_generation_intent.py`）。 */
const intentMessage: Message = {
  id: 'u9', role: 'user', content: '帮我生成一份高血压预防的 PPT', sequence: 3,
  documentGenerationIntent: true, createdAt: '2026-09-27T10:00:00Z',
}
/** 同一句话但服务端判定 false（例如没写格式、或主题不是医学内容）。 */
const plainMessage: Message = {
  ...intentMessage, id: 'u8', content: '帮我生成一份风景介绍的 PPT', documentGenerationIntent: false,
}

const docxFile: DocumentGenerationFile = {
  id: 'f1', format: 'docx',
  mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  byteSize: 84_211, pageCount: 5, available: true,
}
const pptxFile: DocumentGenerationFile = {
  id: 'f2', format: 'pptx',
  mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  byteSize: 132_000, pageCount: 9, available: true,
}
const queuedTask: DocumentGeneration = {
  id: 'd1', sourceMessageId: 'u9', status: 'queued', formats: ['pptx'], title: null,
  model: 'glm-4.7-flash', files: [], sourceCount: 0, errorCode: null,
  expiresAt: null, createdAt: '2026-09-27T10:00:00Z', updatedAt: '2026-09-27T10:00:00Z',
}
/** 一次「PPT + Word」请求完成后仍是**一个任务**、两个下载项（方案 §8.2）。 */
const completedTask: DocumentGeneration = {
  ...queuedTask, status: 'completed', formats: ['docx', 'pptx'], title: '高血压预防科普',
  files: [docxFile, pptxFile], sourceCount: 6, expiresAt: '2026-10-27T10:00:00Z',
}

async function setup(path = '/app/chat', messages?: Message[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = {
    id: 'u1', username: 'tester', realName: '测试', gender: 'private', role: 'user',
    phoneVerified: true, registeredAt: '2026-09-27',
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app/chat', component: HomeView },
      { path: '/app/consultations/:id', name: 'consultation', component: HomeView },
    ],
  })
  await router.push(path)
  if (messages) {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: messages, hasMore: false })
  }
  const wrapper = mount({ template: '<router-view :key="$route.fullPath" />' }, {
    attachTo: document.body, global: { plugins: [pinia, router, ElementPlus] },
  })
  await flushPromises()
  await flushPromises()
  return { wrapper, router }
}

/** 在输入区输入并按 Enter 提交（等价于点发送按钮）。 */
async function sendMessage(wrapper: VueWrapper, text: string) {
  await wrapper.get('textarea').setValue(text)
  await wrapper.get('form.composer').trigger('submit')
  await flushPromises()
}

function dialogButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('.document-generation-dialog button'))
}
function dialogConfirmButton() {
  return dialogButtons().find(button => button.textContent?.includes('同意并生成'))
}
function dialogCancelButton() {
  return dialogButtons().find(button => button.textContent?.includes('取消'))
}
function agreeDialog() {
  document.querySelector<HTMLInputElement>('.document-generation-dialog input[type="checkbox"]')?.click()
}

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  vi.mocked(consultationsApi.create).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.send).mockResolvedValue(intentMessage)
  vi.mocked(consultationsApi.stream).mockResolvedValue({
    id: 'a1', role: 'assistant', content: '高血压……', sequence: 4,
    generationStatus: 'completed', createdAt: '2026-09-27T10:00:10Z',
  })
  vi.mocked(consultationsApi.get).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [], hasMore: false })
  vi.mocked(consultationsApi.list).mockResolvedValue({ items: [conversation], hasMore: false })
  vi.mocked(modelsApi.list).mockResolvedValue([
    { id: 'glm-4.7-flash', name: '智谱 GLM-4.7 Flash', provider: 'zhipuai', providerName: '智谱 AI', description: '', isDefault: true, keySource: 'server' },
  ])
  vi.mocked(attachmentsApi.list).mockResolvedValue([])
  // 配图链路与文档链路共用同一个会话镜像，两边都要能正常恢复（否则 HomeView 会打印恢复失败告警）。
  vi.mocked(imageGenerationsApi.list).mockResolvedValue([])
  vi.mocked(documentGenerationsApi.list).mockResolvedValue([])
  vi.mocked(documentGenerationsApi.create).mockResolvedValue(queuedTask)
  // 带模板创建返回同一个任务对象，只是 `templateMode` 为 uploaded（契约 §3.3）。
  vi.mocked(documentGenerationsApi.createWithTemplate).mockResolvedValue({
    ...queuedTask, templateMode: 'uploaded',
  })
  vi.mocked(documentGenerationsApi.content).mockResolvedValue(new Blob(['docx'], { type: 'application/zip' }))
  vi.mocked(documentGenerationsApi.remove).mockResolvedValue(undefined)
  // jsdom 没有 Object URL；判定用的仍是真实的创建与释放调用。
  Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:document'), configurable: true })
  Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), configurable: true })
  HTMLElement.prototype.scrollTo = vi.fn()
})

afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('自然语言触发（方案 §8.2：不新增任何生成按钮）', () => {
  it('命中意图时跳过 /stream，以该用户消息为来源创建任务，卡片挂在该消息下', async () => {
    localStorage.setItem(DOCUMENT_GENERATION_NOTICE_STORAGE_KEY, DOCUMENT_GENERATION_NOTICE_VERSION)
    const { wrapper } = await setup()

    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')

    // 2026-09-28 起每次生成都先弹确认弹窗：已确认过说明时是短版，直接确认（短版没有勾选框）。
    expect(document.querySelector('.document-generation-dialog')).not.toBeNull()
    dialogConfirmButton()?.click()
    await flushPromises()

    expect(consultationsApi.stream).not.toHaveBeenCalled()
    expect(documentGenerationsApi.create).toHaveBeenCalledTimes(1)
    const [cid, payload] = vi.mocked(documentGenerationsApi.create).mock.calls[0]
    expect(cid).toBe('c1')
    expect(payload.sourceMessageId).toBe('u9')
    expect(payload.noticeAccepted).toBe(true)
    expect(payload.noticeVersion).toBe('document-generation-v1')
    expect(payload.clientRequestId).toBeTruthy()
    // 主题与格式只能由服务端从原文解析：前端不传 prompt、不传格式覆盖值、不传来源列表。
    expect('prompt' in payload).toBe(false)
    expect('formats' in payload).toBe(false)
    expect('sourceIds' in payload).toBe(false)

    expect(document.querySelector('.user-message')?.textContent).toContain('高血压预防')
    expect(document.querySelector('.generated-document-card__status')?.textContent).toContain('已排队')
    // 界面上不能出现任何「生成文档」按钮：触发只能是用户那句话。
    expect(Array.from(document.querySelectorAll('button')).some(
      button => button.textContent?.includes('生成文档') || button.textContent?.includes('生成 PPT'),
    )).toBe(false)
  })

  it('未命中（非医学主题 / 缺格式）照常走 /stream，不创建任何任务', async () => {
    const { wrapper } = await setup()
    vi.mocked(consultationsApi.send).mockResolvedValue(plainMessage)

    await sendMessage(wrapper, '帮我生成一份风景介绍的 PPT')

    expect(consultationsApi.stream).toHaveBeenCalledTimes(1)
    expect(documentGenerationsApi.create).not.toHaveBeenCalled()
    expect(document.querySelector('.generated-document-card')).toBeNull()
  })

  it('生成期间不锁输入框：用户仍可以继续发别的消息', async () => {
    localStorage.setItem(DOCUMENT_GENERATION_NOTICE_STORAGE_KEY, DOCUMENT_GENERATION_NOTICE_VERSION)
    const { wrapper } = await setup()

    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')

    // 短版弹窗没有勾选框，确认按钮直接就绪。
    dialogConfirmButton()?.click()
    await flushPromises()

    expect(wrapper.get('textarea').attributes('disabled')).toBeUndefined()
    expect(document.querySelector('.generated-document-card__pending')?.textContent)
      .toContain('离开页面不会取消这次生成')
  })
})

describe('首次使用的一次性说明', () => {
  it('首次命中自动弹说明，未勾选不能生成；确认后提交并记住说明版本', async () => {
    const { wrapper } = await setup()
    expect(localStorage.getItem(DOCUMENT_GENERATION_NOTICE_STORAGE_KEY)).toBeNull()

    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')

    expect(document.querySelector('.document-generation-dialog')).not.toBeNull()
    expect(documentGenerationsApi.create).not.toHaveBeenCalled()
    // 方案 §8.2 要求的要点必须逐项在说明里出现。
    const text = document.querySelector('.document-generation-dialog')?.textContent || ''
    expect(text).toContain('内容由 AI 根据当前知识库生成')
    expect(text).toContain('仅作健康科普，不作诊断、处方或治疗依据')
    expect(text).toContain('生成可能产生模型费用')
    expect(text).toContain('30 天后自动删除')
    expect(dialogConfirmButton()?.disabled).toBe(true)

    agreeDialog()
    await flushPromises()
    expect(dialogConfirmButton()?.disabled).toBe(false)
    dialogConfirmButton()?.click()
    await flushPromises()

    expect(documentGenerationsApi.create).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(DOCUMENT_GENERATION_NOTICE_STORAGE_KEY))
      .toBe(DOCUMENT_GENERATION_NOTICE_VERSION)
  })

  it('记录的是说明版本：旧版本不算已确认，会再弹一次', async () => {
    localStorage.setItem(DOCUMENT_GENERATION_NOTICE_STORAGE_KEY, 'document-generation-v0')
    const { wrapper } = await setup()

    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')

    expect(document.querySelector('.document-generation-dialog')).not.toBeNull()
    expect(documentGenerationsApi.create).not.toHaveBeenCalled()
  })

  it('取消说明：不发创建请求、不记版本、给出可关闭提示，再说一次会重新弹说明', async () => {
    const { wrapper } = await setup()
    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')
    expect(document.querySelector('.document-generation-dialog')).not.toBeNull()

    expect(dialogCancelButton(), '说明弹窗应有「取消」按钮').toBeTruthy()
    dialogCancelButton()?.click()
    await flushPromises()
    await flushPromises()

    // 方案 §8.2：用户取消不发请求、不记版本、不伪造助手回答。
    expect(documentGenerationsApi.create).not.toHaveBeenCalled()
    expect(localStorage.getItem(DOCUMENT_GENERATION_NOTICE_STORAGE_KEY)).toBeNull()
    expect(consultationsApi.stream).not.toHaveBeenCalled()
    expect(document.querySelector('.generation-cancel-notice')?.textContent)
      .toContain('没有创建任务，也不会产生费用')
    expect(document.querySelector('.generated-document-card')).toBeNull()

    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')
    expect(document.querySelector('.document-generation-dialog')).not.toBeNull()
    expect(documentGenerationsApi.create).not.toHaveBeenCalled()
  })

  it('重复点击「同意并生成」只产生一次创建请求', async () => {
    const { wrapper } = await setup()
    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')
    agreeDialog()
    await flushPromises()

    const confirm = dialogConfirmButton()
    confirm?.click()
    confirm?.click()
    await flushPromises()

    // 收费保护：同一次确认即便被点两下，也只有一个请求（composable 内有 submitting 兜底）。
    expect(documentGenerationsApi.create).toHaveBeenCalledTimes(1)
  })

  it('失败后再次确认复用同一个 clientRequestId（幂等，不重复计费）', async () => {
    const { wrapper } = await setup()
    vi.mocked(documentGenerationsApi.create).mockRejectedValueOnce(
      new ApiError('内容生成服务暂时不可用', 'DOCUMENT_MODEL_UNAVAILABLE', 502),
    )

    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')
    agreeDialog()
    await flushPromises()
    dialogConfirmButton()?.click()
    await flushPromises()

    expect(document.querySelector('.document-generation-dialog__error')?.textContent)
      .toContain('内容生成服务暂时不可用')
    expect(consultationsApi.stream).not.toHaveBeenCalled()

    dialogConfirmButton()?.click()
    await flushPromises()

    const calls = vi.mocked(documentGenerationsApi.create).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[1][1].clientRequestId).toBe(calls[0][1].clientRequestId)
  })
})

describe('任务卡：状态、双格式、下载与删除', () => {
  it('同时要 PPT 和 Word 时只有一个任务卡、两个下载项（文件名与元数据正确）', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([completedTask])

    await setup('/app/consultations/c1')

    expect(documentGenerationsApi.list).toHaveBeenCalledWith('c1')
    expect(document.querySelectorAll('.generated-document-card')).toHaveLength(1)
    const files = Array.from(document.querySelectorAll('.generated-document-card__file'))
    expect(files).toHaveLength(2)
    expect(files[0].textContent).toContain('Word 文档')
    expect(files[0].textContent).toContain('5 页')
    expect(files[1].textContent).toContain('PPT 演示文稿')
    expect(files[1].textContent).toContain('9 页幻灯片')
    // 卡片必须显示 AI 生成边界，并且**不提供在线预览**。
    expect(document.querySelector('.generated-document-card__disclaimer')?.textContent)
      .toContain(DOCUMENT_GENERATION_DISCLAIMER)
    expect(document.querySelector('.generated-document-card__hint')?.textContent)
      .toContain('不提供在线预览')
    expect(document.querySelector('.generated-document-card__meta')?.textContent)
      .toContain('参考 6 条来源')
    // 状态用 aria-live 播报，键盘与读屏可用。
    expect(document.querySelector('.generated-document-card__status')?.getAttribute('aria-live')).toBe('polite')
  })

  const statusCases: Array<[DocumentGenerationStatus, string]> = [
    ['queued', '已排队'],
    ['generating', '正在整理内容'],
    ['rendering', '正在排版文件'],
    ['completed', '已生成'],
    ['failed', '生成失败'],
    ['cancelled', '已取消'],
    ['expired', '已过期'],
  ]

  it.each(statusCases)('状态 %s 渲染成「%s」', async (status, label) => {
    expect(DOCUMENT_GENERATION_STATUS_LABELS[status]).toBe(label)
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([{ ...queuedTask, status }])

    await setup('/app/consultations/c1')

    expect(document.querySelector('.generated-document-card__status')?.textContent).toContain(label)
  })

  it('刷新恢复：失败任务用服务端受控错误码还原成中文原因，内部原文不直出', async () => {
    const rawDetail = '{"detail":"DOCUMENT_MODEL_INVALID_RESPONSE at content.py:412 traceback"}'
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([
      { ...queuedTask, status: 'failed', errorCode: 'DOCUMENT_EVIDENCE_INSUFFICIENT' },
    ])

    await setup('/app/consultations/c1')

    const notice = document.querySelector('.generated-document-card__notice')?.textContent || ''
    expect(notice).toContain('知识库没有足够的可引用资料')
    expect(notice).not.toContain(rawDetail)
    expect(document.querySelectorAll('.generated-document-card__file')).toHaveLength(0)
  })

  it('未识别的错误码走受控兜底文案，不把 JSON/HTML 错误体直出', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([
      { ...queuedTask, status: 'failed', errorCode: 'SOMETHING_NEW' },
    ])
    vi.mocked(documentGenerationsApi.get).mockRejectedValue(
      new Error('{"detail":"Internal Server Error","stack":"at render()"}'),
    )

    await setup('/app/consultations/c1')
    await new Promise(resolve => setTimeout(resolve, 2_100))
    await flushPromises()

    const notice = document.querySelector('.generated-document-card__notice')?.textContent || ''
    expect(notice).not.toContain('{"detail"')
    expect(notice).not.toContain('stack')
  })

  it('下载走鉴权字节并按固定文件名触发，触发后回收 Object URL', async () => {
    const clicked: HTMLAnchorElement[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this)
    })
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([completedTask])

    await setup('/app/consultations/c1')

    const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>('.generated-document-card__file button'))
    expect(buttons).toHaveLength(2)
    buttons[0].click()
    await flushPromises()

    // 内容接口带 (任务 id, 文件 id)；文件名固定，不含用户主题。
    expect(documentGenerationsApi.content).toHaveBeenCalledWith('d1', 'f1')
    expect(clicked).toHaveLength(1)
    expect(clicked[0].download).toBe('AI医学科普-20260927.docx')
    expect(clicked[0].href).toBe('blob:document')
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)

    // 方案 §8.2：Object URL 触发后及时回收（延后一拍，避免浏览器还没读就失效）。
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
    await new Promise(resolve => setTimeout(resolve, 1_100))
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:document')
  })

  it('下载遇到 410：按过期展示并给出保留期说明，不再提供下载入口', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([completedTask])
    vi.mocked(documentGenerationsApi.content).mockRejectedValue(
      new ApiError('已过期', 'GENERATED_DOCUMENT_EXPIRED', 410),
    )

    await setup('/app/consultations/c1')
    Array.from(document.querySelectorAll<HTMLButtonElement>('.generated-document-card__file button'))[0].click()
    await flushPromises()

    expect(document.querySelector('.generated-document-card__status')?.textContent).toContain('已过期')
    expect(document.querySelector('.generated-document-card__notice')?.textContent).toContain('30 天保留期')
  })

  it('删除已完成任务：调用删除接口后卡片消失', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([completedTask])

    const { wrapper } = await setup('/app/consultations/c1')
    expect(document.querySelector('.generated-document-card')).not.toBeNull()
    // 卡片上确有「删除」入口（真实点击路径由 e2e 覆盖：Element Plus 的 popconfirm 气泡
    // 在 jsdom 里点开也查不到按钮，本轮实测）。
    expect(Array.from(document.querySelectorAll('.generated-document-card__actions button'))
      .some(button => button.textContent?.includes('删除'))).toBe(true)

    wrapper.findAllComponents(GeneratedDocumentCard)[0].vm.$emit('remove')
    await flushPromises()
    await flushPromises()

    expect(documentGenerationsApi.remove).toHaveBeenCalledWith('d1')
    expect(document.querySelector('.generated-document-card')).toBeNull()
  })

  it('删除未完成任务：只标记为已取消，不声称撤销模型费用', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([{ ...queuedTask, status: 'generating' }])

    const { wrapper } = await setup('/app/consultations/c1')
    wrapper.findAllComponents(GeneratedDocumentCard)[0].vm.$emit('remove')
    await flushPromises()
    await flushPromises()

    expect(documentGenerationsApi.remove).toHaveBeenCalledWith('d1')
    expect(document.querySelector('.generated-document-card__status')?.textContent).toContain('已取消')
  })

  it('轮询失败只给提示，不把任务改写成失败（服务端才是状态的事实来源）', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([{ ...queuedTask, status: 'generating' }])

    await setup('/app/consultations/c1')
    vi.mocked(documentGenerationsApi.get).mockRejectedValue(
      new ApiError('服务暂时不可用', 'DOCUMENT_MODEL_UNAVAILABLE', 502),
    )
    // 历史恢复时排的是**真实**计时器（退避首档 2 秒），等它跑完一轮再断言。
    await new Promise(resolve => setTimeout(resolve, 2_100))
    await flushPromises()

    expect(document.querySelector('.generated-document-card__status')?.textContent).toContain('正在整理内容')
    expect(document.querySelector('.generated-document-card__notice')?.textContent)
      .toContain('内容生成服务暂时不可用')
  })

  it('轮询到完成状态后自动切换到完成态并给出下载项', async () => {
    vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [intentMessage], hasMore: false })
    vi.mocked(documentGenerationsApi.list).mockResolvedValue([{ ...queuedTask, status: 'rendering' }])

    await setup('/app/consultations/c1')
    vi.mocked(documentGenerationsApi.get).mockResolvedValue(completedTask)
    await new Promise(resolve => setTimeout(resolve, 2_100))
    await flushPromises()

    expect(document.querySelector('.generated-document-card__status')?.textContent).toContain('已生成')
    expect(document.querySelectorAll('.generated-document-card__file')).toHaveLength(2)
    // 没有预览：完成的卡片只给下载与说明，没有 img/iframe。
    expect(document.querySelector('.generated-document-card img')).toBeNull()
    expect(document.querySelector('.generated-document-card iframe')).toBeNull()
  })
})

/**
 * 等待体验（用户 2026-09-27 要求：生成后要排队，但界面不告诉他要等多久）。
 *
 * 这里守两条线：①「走到第几步」只能来自服务端状态（`queued`/`generating`/`rendering` 的 1:1 映射），
 * ②**只报已经等了多久，不预测还要多久**——服务端没有剩余时间这个事实，编出来就是假承诺。
 * 计时用假时钟 + 固定 `createdAt`，文案因此是确定的，不依赖真实时间流逝。
 */
describe('等待体验：真实阶段 + 已等待时长（不编进度）', () => {
  const BASE_TIME = new Date('2026-09-27T10:00:00Z').getTime()

  function mountCard(task: DocumentGeneration) {
    return mount(GeneratedDocumentCard, {
      props: { task },
      global: { plugins: [ElementPlus] },
    })
  }

  /** 已经等了 `secondsWaited` 秒的任务：`createdAt` 由服务端给，前端只用它算差值。 */
  function pendingTask(secondsWaited: number, status: DocumentGenerationStatus = 'queued'): DocumentGeneration {
    return {
      ...queuedTask,
      status,
      createdAt: new Date(BASE_TIME - secondsWaited * 1_000).toISOString(),
    }
  }

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(BASE_TIME)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('排队中：有思考动效，显示真实阶段与「已等待」时长，并如实给出处理上限', () => {
    const wrapper = mountCard(pendingTask(83))

    expect(wrapper.find('.generated-document-card__thinking').exists(), '等待态应有思考动效').toBe(true)
    expect(wrapper.find('.generated-document-card__pending-hint').text())
      .toBe(DOCUMENT_GENERATION_STAGE_HINTS.queued)
    expect(wrapper.find('.generated-document-card__waited').text()).toBe('已等待 1 分 23 秒')
    // 三个阶段全部列出、当前这个高亮：这是服务端状态的 1:1 映射，不是前端估的进度。
    const steps = wrapper.findAll('.generated-document-card__step')
    expect(steps.map(step => step.text())).toEqual(DOCUMENT_GENERATION_STAGES.map(stage => stage.label))
    expect(steps[0].classes()).toContain('is-active')
    expect(steps[1].classes()).not.toContain('is-active')
    expect(wrapper.text()).toContain('最长处理约 5 分钟')
    wrapper.unmount()
  })

  it('阶段随服务端状态推进，走过的阶段标成已完成', async () => {
    const wrapper = mountCard(pendingTask(10, 'generating'))

    let steps = wrapper.findAll('.generated-document-card__step')
    expect(steps[0].classes()).toContain('is-done')
    expect(steps[1].classes()).toContain('is-active')
    expect(wrapper.find('.generated-document-card__pending-hint').text())
      .toBe(DOCUMENT_GENERATION_STAGE_HINTS.generating)

    await wrapper.setProps({ task: pendingTask(20, 'rendering') })
    steps = wrapper.findAll('.generated-document-card__step')
    expect(steps[0].classes()).toContain('is-done')
    expect(steps[1].classes()).toContain('is-done')
    expect(steps[2].classes()).toContain('is-active')
    expect(wrapper.find('.generated-document-card__status').text()).toBe('正在排版文件')
    wrapper.unmount()
  })

  it('已等待时长每秒刷新，且按服务的 createdAt 重算（标签页挂起回来不走偏）', async () => {
    const wrapper = mountCard(pendingTask(5))
    expect(wrapper.find('.generated-document-card__waited').text()).toBe('已等待 5 秒')

    vi.advanceTimersByTime(3_000)
    await nextTick()
    expect(wrapper.find('.generated-document-card__waited').text()).toBe('已等待 8 秒')

    // 时钟往前跳 62 秒、随后只 tick 一秒（合计 63 秒）：必须重算，而不是每次 +1。
    vi.setSystemTime(BASE_TIME + 62_000)
    vi.advanceTimersByTime(1_000)
    await nextTick()
    expect(wrapper.find('.generated-document-card__waited').text()).toBe('已等待 1 分 8 秒')
    wrapper.unmount()
  })

  it('进入终态后不再显示等待区，并停掉计时器', async () => {
    const wrapper = mountCard(pendingTask(5))
    expect(vi.getTimerCount(), '等待态应挂着计时器').toBeGreaterThan(0)

    await wrapper.setProps({ task: { ...completedTask } })
    expect(wrapper.find('.generated-document-card__pending').exists()).toBe(false)
    expect(wrapper.find('.generated-document-card__waited').exists()).toBe(false)
    expect(vi.getTimerCount(), '终态不能留空转的定时器').toBe(0)
    wrapper.unmount()
  })

  it('卡片上不出现任何编造的进度百分比或预计剩余时间', () => {
    const wrapper = mountCard(pendingTask(30, 'rendering'))
    const text = wrapper.text()

    expect(text).not.toContain('%')
    expect(text).not.toMatch(/剩余|还需|预计/)
    wrapper.unmount()
  })

  it('formatDocumentWait 只报已经过去的时长', () => {
    expect(formatDocumentWait(0)).toBe('0 秒')
    expect(formatDocumentWait(59)).toBe('59 秒')
    expect(formatDocumentWait(60)).toBe('1 分钟')
    expect(formatDocumentWait(83)).toBe('1 分 23 秒')
    expect(formatDocumentWait(-5)).toBe('0 秒')
  })

  it('documentGenerationStageIndex 只认三个等待态，终态返回 -1', () => {
    expect(documentGenerationStageIndex('queued')).toBe(0)
    expect(documentGenerationStageIndex('generating')).toBe(1)
    expect(documentGenerationStageIndex('rendering')).toBe(2)
    expect(documentGenerationStageIndex('completed')).toBe(-1)
  })
})

/**
 * 上传 PPTX 模板（契约 `PPT_WORD_PLAN.md` §3.3；Codex §6 第 175 行交接，2026-09-28）。
 *
 * 三条硬约束：
 * 1. 模板**只从确认弹窗里选**——不进病历附件入口、也不作为聊天内容发给模型；
 * 2. 选了文件才要求单独勾选模板说明（`templateNoticeAccepted`），未勾选不得提交；
 * 3. 本地只拦扩展名与体积；页数、结构、可用性一律以服务端受控错误码为准（前端不解析 OOXML）。
 *
 * 另有用户 2026-09-28 的决定：**每次生成都弹确认弹窗**，已确认过说明时用短版——否则模板入口
 * 对老用户不可达（原来「记住版本就直接生成」）。
 */
describe('上传 PPTX 模板', () => {
  function templateInput(): HTMLInputElement {
    const input = document.querySelector<HTMLInputElement>('.document-generation-dialog input[type="file"]')
    expect(input, '确认弹窗里应有模板文件选择器').not.toBeNull()
    return input as HTMLInputElement
  }
  function pickFiles(files: File[]) {
    const input = templateInput()
    Object.defineProperty(input, 'files', { value: files, configurable: true })
    input.dispatchEvent(new Event('change'))
  }
  function agreeBoxes(): HTMLElement[] {
    return Array.from(document.querySelectorAll<HTMLElement>('.document-generation-dialog .el-checkbox'))
  }
  function clickTemplateAgree() {
    const box = agreeBoxes().find(item => item.textContent?.includes('模板原件'))
    expect(box, '选了模板应出现模板说明勾选框').toBeTruthy()
    box?.querySelector<HTMLInputElement>('input')?.click()
  }
  function pptxFile(name = 'my-template.pptx', bytes = 2_048) {
    return new File([new Uint8Array(bytes)], name, {
      type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    })
  }

  it('已确认过说明时仍弹窗（短版），模板入口可达', async () => {
    localStorage.setItem(DOCUMENT_GENERATION_NOTICE_STORAGE_KEY, DOCUMENT_GENERATION_NOTICE_VERSION)
    const { wrapper } = await setup()

    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')

    const dialog = document.querySelector('.document-generation-dialog')
    expect(dialog, '已确认过说明也要弹窗，否则模板没有入口').not.toBeNull()
    expect(dialog?.textContent).toContain('说明已经确认过')
    // 短版不再要求勾选说明，但模板选择器必须在。
    expect(agreeBoxes().some(box => box.textContent?.includes('我已阅读并同意上述说明'))).toBe(false)
    expect(dialogConfirmButton()?.disabled).toBe(false)
    expect(templateInput()).toBeTruthy()
    expect(documentGenerationsApi.create).not.toHaveBeenCalled()
  })

  it('选了 .pptx 走带模板接口并带全字段；未勾模板说明不能提交', async () => {
    const { wrapper } = await setup()
    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')
    agreeDialog()
    await flushPromises()

    const file = pptxFile()
    pickFiles([file])
    await flushPromises()

    expect(document.querySelector('.document-generation-dialog')?.textContent).toContain('my-template.pptx')
    // 契约 §3.3：勾了模板就必须单独确认模板说明，否则服务端 422 PPT_TEMPLATE_NOTICE_REQUIRED。
    expect(dialogConfirmButton()?.disabled, '未勾模板说明不得提交').toBe(true)
    clickTemplateAgree()
    await flushPromises()
    expect(dialogConfirmButton()?.disabled).toBe(false)

    dialogConfirmButton()?.click()
    await flushPromises()

    expect(documentGenerationsApi.create, '带模板时不得再走原 JSON 接口').not.toHaveBeenCalled()
    expect(documentGenerationsApi.createWithTemplate).toHaveBeenCalledTimes(1)
    const [consultationId, payload, sent] = vi.mocked(documentGenerationsApi.createWithTemplate).mock.calls[0]
    expect(consultationId).toBe('c1')
    expect(sent).toBe(file)
    expect(payload.sourceMessageId).toBe('u9')
    expect(payload.noticeAccepted).toBe(true)
    expect(payload.noticeVersion).toBe('document-generation-v1')
    expect(payload.clientRequestId).toBeTruthy()
    // 任务卡显示服务端给的实际模板类型。
    expect(document.querySelector('.generated-document-card__meta')?.textContent).toContain('你上传的模板')
  })

  it('本地拦住非 .pptx 与超过 10 MiB 的文件，且不发任何请求', async () => {
    const { wrapper } = await setup()
    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')
    agreeDialog()
    await flushPromises()

    pickFiles([new File(['x'], 'template.doc')])
    await flushPromises()
    expect(document.querySelector('.document-generation-dialog__template-error')?.textContent)
      .toContain('只支持 .pptx')

    pickFiles([new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'big.pptx')])
    await flushPromises()
    expect(document.querySelector('.document-generation-dialog__template-error')?.textContent)
      .toContain('不能超过')

    // 拦下之后不得静默丢模板去生成默认版式：确认先停住，用户明确「不用模板」才继续。
    expect(dialogConfirmButton()?.disabled, '有非法模板时不得直接生成').toBe(true)
    dialogConfirmButton()?.click()
    await flushPromises()
    expect(documentGenerationsApi.createWithTemplate).not.toHaveBeenCalled()
    expect(documentGenerationsApi.create).not.toHaveBeenCalled()

    const clearButton = Array.from(
      document.querySelectorAll<HTMLElement>('.document-generation-dialog button'),
    ).find(button => button.textContent?.includes('不用模板'))
    expect(clearButton, '拦下后要给一个明确的出口').toBeTruthy()
    clearButton?.click()
    await flushPromises()
    expect(document.querySelector('.document-generation-dialog__template-error')).toBeNull()
    expect(dialogConfirmButton()?.disabled).toBe(false)

    dialogConfirmButton()?.click()
    await flushPromises()
    expect(documentGenerationsApi.create, '明确不用模板后仍走原 JSON 接口').toHaveBeenCalledTimes(1)
  })

  it('服务端的模板拒绝码显示成受控中文，不透传内部文案', async () => {
    vi.mocked(documentGenerationsApi.createWithTemplate).mockRejectedValueOnce(
      new ApiError('template zip boom', 'PPT_TEMPLATE_INVALID', 422),
    )
    const { wrapper } = await setup()
    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')
    agreeDialog()
    await flushPromises()

    pickFiles([pptxFile()])
    await flushPromises()
    clickTemplateAgree()
    await flushPromises()
    dialogConfirmButton()?.click()
    await flushPromises()

    const error = document.querySelector('.document-generation-dialog__error')?.textContent || ''
    expect(error).toContain('这个模板打不开或结构不被支持')
    expect(error, '不得透传内部原文或错误码').not.toContain('template zip boom')
    expect(error).not.toContain('PPT_TEMPLATE_INVALID')
  })

  it('取消后重新发起不会保留上次选的模板', async () => {
    const { wrapper } = await setup()
    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')
    agreeDialog()
    await flushPromises()

    pickFiles([pptxFile()])
    await flushPromises()
    expect(document.querySelector('.document-generation-dialog')?.textContent).toContain('my-template.pptx')

    dialogCancelButton()?.click()
    await flushPromises()
    await flushPromises()

    await sendMessage(wrapper, '帮我生成一份高血压预防的 PPT')
    await flushPromises()

    const text = document.querySelector('.document-generation-dialog')?.textContent || ''
    expect(text, '新一次确认不应带着上次的文件').not.toContain('my-template.pptx')
    expect(agreeBoxes().some(box => box.textContent?.includes('模板原件')), '没有文件就不该有模板勾选框').toBe(false)
    expect(documentGenerationsApi.createWithTemplate).not.toHaveBeenCalled()
  })

  it('任务卡显示的模板类型来自服务端，刷新恢复也一样', async () => {
    const uploaded = mount(GeneratedDocumentCard, {
      props: { task: { ...completedTask, templateMode: 'uploaded' as const } },
      global: { plugins: [ElementPlus] },
    })
    expect(uploaded.find('.generated-document-card__meta').text()).toContain('你上传的模板')
    await uploaded.setProps({ task: { ...completedTask, templateMode: 'builtin' as const } })
    expect(uploaded.find('.generated-document-card__meta').text()).toContain('内置模板')
    await uploaded.setProps({ task: { ...completedTask, templateMode: 'default' as const } })
    expect(uploaded.find('.generated-document-card__meta').text()).toContain('默认版式')
    await uploaded.setProps({ task: { ...completedTask, templateMode: undefined } })
    expect(uploaded.find('.generated-document-card__meta').text()).not.toContain('版式')
    uploaded.unmount()
  })
})