import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import HomeView from './HomeView.vue'
import MessageAttachments from '../components/MessageAttachments.vue'
import { useAuthStore } from '../stores/auth'
import { consultationsApi } from '../api/consultations'
import { modelsApi } from '../api/models'
import { attachmentsApi } from '../api/attachments'
import { ApiError } from '../api/http'
import { DOCUMENT_NOTICE_STORAGE_KEY, IMAGE_CONSENT_STORAGE_KEY } from '../stores/composerHints'
import { ImagePrepError } from '../composables/imagePrep'
import { IMAGE_LIMIT } from '../composables/useAttachments'
import type { Attachment, ImageCategory, Message, MessageAttachment } from '../types/consultations'

vi.mock('../api/consultations', () => ({ consultationsApi: {
  create: vi.fn(), send: vi.fn(), stream: vi.fn(), get: vi.fn(), messages: vi.fn(), list: vi.fn(), remove: vi.fn(),
} }))
vi.mock('../api/models', () => ({ modelsApi: { list: vi.fn() } }))
vi.mock('../api/voice', () => ({ voiceApi: { transcribe: vi.fn() } }))
vi.mock('../api/attachments', () => ({ attachmentsApi: {
  upload: vi.fn(), uploadImage: vi.fn(), content: vi.fn(), list: vi.fn(), remove: vi.fn(),
} }))
vi.mock('../composables/useVoiceRecorder', async () => {
  const { ref } = await import('vue')
  return { useVoiceRecorder: () => ({
    state: ref('idle'), seconds: ref(0), error: ref(''), supported: false,
    start: vi.fn(), stop: vi.fn(), cancel: vi.fn(), reset: vi.fn(),
  }) }
})
/**
 * 本地预处理有自己 13 项单测；这里只替换掉 `createImageBitmap`/canvas 这一步，
 * 其余导出（类别文案、错误类）保持真实，视图测试才能验证真实的文案与流程。
 */
const prep = vi.hoisted(() => ({ prepare: vi.fn() }))
vi.mock('../composables/imagePrep', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../composables/imagePrep')>()
  return { ...actual, prepareImageForUpload: prep.prepare }
})

const conversation = { id: 'c1', title: '头痛', messageCount: 1, createdAt: '2026-09-06', updatedAt: '2026-09-06' }
const userMessage = { id: 'm1', role: 'user' as const, content: '帮我看下', sequence: 1, createdAt: '2026-09-06' }
const assistantMessage: Message = { id: 'a1', role: 'assistant', content: '建议先到内科就诊', sequence: 2, createdAt: '2026-09-06' }
const imageAttachment: Attachment = {
  id: 'i1', displayName: '检查单.jpg', kind: 'image', byteSize: 234567, charCount: 860,
  preview: '白细胞计数 6.2', status: 'ready', createdAt: '2026-09-21',
  imageCategory: 'report', mimeType: 'image/webp', width: 1600, height: 1200,
  imageAvailable: true, imageExpiresAt: '2026-12-20T10:00:00Z',
}
const documentAttachment: Attachment = {
  id: 'd1', displayName: '血常规报告.pdf', kind: 'pdf', byteSize: 20480, pageCount: 2,
  charCount: 860, preview: '白细胞计数 6.2', status: 'ready', createdAt: '2026-09-22',
}
const aiModels = [
  { id: 'glm-4.7-flash', name: '智谱 GLM-4.7 Flash', provider: 'zhipuai', providerName: '智谱 AI', description: '', isDefault: true, keySource: 'server' as const },
]

function imageFile(name = 'IMG_1234.jpg', type = 'image/jpeg'): File {
  return new File([new Uint8Array(16)], name, { type })
}

function docxFile(name = '检查报告.docx', bytes = 2048): File {
  return new File([new Uint8Array(bytes)], name)
}

async function setup(path = '/app/chat') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = { id: 'u1', username: 'tester', realName: '测试', gender: 'private', role: 'user', registeredAt: '2026-09-06' }
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
  return { wrapper, router }
}

/** 让下一次上传返回服务端「自动分类」的结果——类别只能来自响应，前端不再自己选。 */
function mockUploadedCategory(category: ImageCategory) {
  vi.mocked(attachmentsApi.uploadImage).mockImplementation(async (_cid, file) => ({
    ...imageAttachment, id: `i-${file.name}`, displayName: file.name, imageCategory: category,
  }))
}

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  vi.mocked(consultationsApi.create).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.send).mockResolvedValue(userMessage)
  // stream 必须给一个真实消息：HomeView 会把它写回 messages[index]，返回 undefined 会在渲染时炸。
  vi.mocked(consultationsApi.stream).mockResolvedValue(assistantMessage)
  vi.mocked(consultationsApi.get).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [userMessage], hasMore: false })
  vi.mocked(consultationsApi.list).mockResolvedValue({ items: [conversation], hasMore: false })
  vi.mocked(modelsApi.list).mockResolvedValue(aiModels)
  vi.mocked(attachmentsApi.list).mockResolvedValue([])
  vi.mocked(attachmentsApi.upload).mockImplementation(async (_cid, file) => ({
    ...documentAttachment, id: `d-${file.name}`, displayName: file.name,
  }))
  mockUploadedCategory('report')
  vi.mocked(attachmentsApi.content).mockResolvedValue(new Blob(['webp'], { type: 'image/webp' }))
  vi.mocked(attachmentsApi.remove).mockResolvedValue(undefined)
  prep.prepare.mockImplementation(async (file: File) => new File(['x'], `${file.name}.jpg`, { type: 'image/jpeg' }))
  // jsdom 没有 Object URL，缩略图这一步必须打桩；判定用的仍是真实的调用与释放。
  Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:preview'), configurable: true })
  Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), configurable: true })
  HTMLElement.prototype.scrollTo = vi.fn()
})

afterEach(() => {
  document.body.innerHTML = ''
})

function pickFiles(wrapper: VueWrapper, files: File[]) {
  const input = wrapper.get('input[type="file"][accept*="image/jpeg"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  return input.trigger('change')
}

function dialogButton(label: string) {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('.image-upload button'))
    .find(button => button.textContent?.includes(label))
}

async function agreeConsent() {
  document.querySelector<HTMLInputElement>('.image-upload input[type="checkbox"]')?.click()
  await flushPromises()
}

/** el-dialog 关闭后 overlay 仍留在 DOM 里、只是 display:none；jsdom 没有布局，只能看内联样式。 */
function dialogVisible() {
  const overlay = document.querySelector<HTMLElement>('.image-upload')?.closest<HTMLElement>('.el-overlay')
  return Boolean(overlay) && overlay?.style.display !== 'none'
}

/** 走完「选图 →（首次）同意 → 上传」。没有类别选择这一步。 */
async function uploadImage(wrapper: VueWrapper, files: File[] = [imageFile()], agree = true) {
  await pickFiles(wrapper, files)
  await flushPromises()
  if (agree) await agreeConsent()
  dialogButton('同意并上传')?.click()
  await flushPromises()
}

/** 本机已同意过的用户：必须在 `setup()` **之前**写标记，组件初始化时才会读到。文档与图片都设上。 */
async function setupConsented(path = '/app/chat') {
  localStorage.setItem(IMAGE_CONSENT_STORAGE_KEY, 'true')
  localStorage.setItem(DOCUMENT_NOTICE_STORAGE_KEY, 'true')
  return setup(path)
}

/** 已同意过的用户选图后直接上传，不经过任何弹窗。 */
async function uploadImageDirect(wrapper: VueWrapper, files: File[] = [imageFile()]) {
  await pickFiles(wrapper, files)
  await flushPromises()
}

describe('图片上传与识别（前端）', () => {
  it('只有一个附件按钮，位于麦克风左侧，并带无障碍标签', async () => {
    const { wrapper } = await setup()
    const labels = wrapper.findAll('.send-area button').map(button => button.attributes('aria-label'))
    expect(labels.filter(label => label === '添加附件')).toHaveLength(1)
    expect(labels).not.toContain('添加图片')
    expect(labels[labels.indexOf('语音输入') - 1]).toBe('添加附件')
    wrapper.unmount()
  })

  it('点附件按钮直接打开本机文件选择器，一个选择器同时收文档与图片', async () => {
    const { wrapper } = await setup()
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, 'click')
    await wrapper.get('button[aria-label="添加附件"]').trigger('click')

    const clickedInput = clickSpy.mock.instances[0] as HTMLInputElement | undefined
    expect(clickedInput, '按钮应直接触发本机文件选择器').toBeDefined()
    const accept = clickedInput?.getAttribute('accept') || ''
    expect(accept).toContain('.pdf')
    expect(accept).toContain('.docx')
    expect(accept).toContain('image/jpeg')
    expect(accept).toContain('image/png')
    // 只剩一个文件入口，因此也不该再有菜单
    expect(wrapper.findAll('input[type="file"]')).toHaveLength(1)
    expect(document.querySelector('.el-dropdown-menu')).toBeNull()
    wrapper.unmount()
  })

  it('混合选中时按类型分流：文档先走 /attachments，图片再走 /images', async () => {
    const { wrapper } = await setupConsented()
    await pickFiles(wrapper, [docxFile(), imageFile('报告.jpg')])
    await flushPromises()

    expect(attachmentsApi.upload).toHaveBeenCalledWith('c1', expect.any(File))
    expect(attachmentsApi.uploadImage).toHaveBeenCalledWith('c1', expect.any(File))
    expect(vi.mocked(attachmentsApi.upload).mock.invocationCallOrder[0],
      '两次上传不能同时跑，顺序固定为先文档后图片')
      .toBeLessThan(vi.mocked(attachmentsApi.uploadImage).mock.invocationCallOrder[0])
    wrapper.unmount()
  })

  it('首次上传必须先勾选隐私说明；未同意传不出去，且请求里没有类别字段', async () => {
    const { wrapper } = await setup()
    await pickFiles(wrapper, [imageFile('血常规.jpg')])
    await flushPromises()

    expect(document.body.textContent).toContain('血常规.jpg')
    expect(document.body.textContent).toContain('阿里云视觉模型')
    expect(document.body.textContent).toContain('建议先遮挡')
    // 类别由服务端判断，弹窗里不该再出现任何类别选项。
    expect(document.querySelector('.image-upload .el-radio-group')).toBeNull()
    expect(dialogButton('同意并上传')?.disabled).toBe(true)

    await agreeConsent()
    expect(dialogButton('同意并上传')?.disabled).toBe(false)
    dialogButton('同意并上传')?.click()
    await flushPromises()

    // 只传会话 id 与文件：契约第 10.2 节已删除 imageCategory。
    expect(attachmentsApi.uploadImage).toHaveBeenCalledWith('c1', expect.any(File))
    expect(wrapper.text()).toContain('血常规.jpg')
    wrapper.unmount()
  })

  it('取消弹窗不上传、也不建会话', async () => {
    const { wrapper } = await setup()
    await pickFiles(wrapper, [imageFile()])
    await flushPromises()
    await agreeConsent()
    dialogButton('取消')?.click()
    await flushPromises()

    expect(attachmentsApi.uploadImage).not.toHaveBeenCalled()
    expect(consultationsApi.create).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('已同意过的用户不再弹窗，选图后直接上传', async () => {
    const { wrapper } = await setupConsented()
    await uploadImageDirect(wrapper, [imageFile('报告.jpg')])

    expect(dialogVisible()).toBe(false)
    expect(attachmentsApi.uploadImage).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('报告.jpg')
    wrapper.unmount()
  })

  it('四类自动分类结果各自显示不同的能力边界文案，都不给疾病判断', async () => {
    const cases: { category: ImageCategory; label: string; notice: string }[] = [
      { category: 'report', label: '报告 / 检查单', notice: '以纸质报告为准' },
      { category: 'medical_imaging', label: 'X 光 / CT / MRI 片子', notice: '不判断病灶' },
      { category: 'body_photo', label: '患处或身体照片', notice: '不判断是什么病' },
      // 第四类：普通图片是**成功附件**（后端 `82dd68c` + 迁移 `20260922_0019`），不再报错。
      { category: 'unrelated', label: '普通图片', notice: '未检测到医疗健康相关内容' },
    ]

    for (const item of cases) {
      mockUploadedCategory(item.category)
      const { wrapper } = await setupConsented()
      await uploadImageDirect(wrapper, [imageFile(`${item.category}.jpg`)])
      expect(wrapper.text()).toContain(item.label)
      expect(wrapper.text()).toContain(item.notice)
      wrapper.unmount()
    }
  })

  it('被判为看不清的图片不进待发送列表，只给一句短提示', async () => {
    vi.mocked(attachmentsApi.uploadImage)
      .mockRejectedValueOnce(new ApiError('无法判断图片类别', 'IMAGE_CATEGORY_UNCLEAR', 422))

    const { wrapper } = await setupConsented()
    await uploadImageDirect(wrapper, [imageFile('糊了.jpg')])
    expect(wrapper.text()).toContain('看不清内容')
    expect(wrapper.findAll('.attachment-item')).toHaveLength(0)
    expect(wrapper.find('.attachment-notice .el-alert__close-btn').exists(), '提示要可关闭').toBe(true)
    wrapper.unmount()
  })

  /**
   * 2026-09-22 契约变更：`unrelated` 从 422 拒绝改为第四种**成功**附件。
   * 旧断言「普通图片不生成卡片 + 提示 IMAGE_UNRELATED」已作废并删除，这里改测成功卡片、标签、
   * 边界文案与「可以发送」。
   */
  it('被判为普通图片的照常是成功附件：显示「普通图片」标签与边界，且能发送', async () => {
    mockUploadedCategory('unrelated')
    const { wrapper } = await setupConsented()
    await uploadImageDirect(wrapper, [imageFile('风景.jpg')])

    expect(wrapper.text()).toContain('风景.jpg')
    expect(wrapper.text()).toContain('普通图片')
    expect(wrapper.text()).toContain('未检测到医疗健康相关内容')
    expect(wrapper.text(), '普通图片不该再出现「没有上传」这种失败文案').not.toContain('没有上传')
    expect(wrapper.findAll('.attachment-item')).toHaveLength(1)

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const [, , , attachmentIds] = vi.mocked(consultationsApi.send).mock.calls[0]
    expect(attachmentIds, '普通图片必须能作为附件发出去').toHaveLength(1)
    wrapper.unmount()
  })

  it('同一批里被判看不清的那张不影响其它图片上传', async () => {
    vi.mocked(attachmentsApi.uploadImage)
      .mockRejectedValueOnce(new ApiError('无法判断图片类别', 'IMAGE_CATEGORY_UNCLEAR', 422))
      .mockImplementation(async (_cid, file) => ({
        ...imageAttachment, id: `i-${file.name}`, displayName: file.name,
      }))
    const { wrapper } = await setupConsented()
    await uploadImageDirect(wrapper, [imageFile('糊了.jpg'), imageFile('报告.jpg')])

    expect(attachmentsApi.uploadImage).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('看不清内容')
    expect(wrapper.text()).toContain('报告.jpg')
    expect(wrapper.text()).not.toContain('糊了.jpg')
    wrapper.unmount()
  })

  it('上传成功只挂附件、不自动发送；仅图片也能发送，且用图片版的默认提问', async () => {
    const { wrapper } = await setup()
    await uploadImage(wrapper)

    expect(consultationsApi.send).not.toHaveBeenCalled()
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    const [, content, , attachmentIds] = vi.mocked(consultationsApi.send).mock.calls[0]
    expect(content).toContain('不要判读影像')
    expect(attachmentIds).toHaveLength(1)
    wrapper.unmount()
  })

  it('本地解不开的 HEIC 不上传，并给出可操作的提示', async () => {
    prep.prepare.mockRejectedValueOnce(new ImagePrepError('undecodable', 'iPhone 的 HEIC 照片浏览器打不开，请先在相册里导出为 JPG 再上传'))
    const { wrapper } = await setup()
    await uploadImage(wrapper, [imageFile('IMG_1.HEIC', 'image/heic')])

    expect(attachmentsApi.uploadImage).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('HEIC')
    wrapper.unmount()
  })

  it('服务端拒绝时显示服务端文案', async () => {
    vi.mocked(attachmentsApi.uploadImage).mockRejectedValue(new ApiError('图片类型不被接受', 'IMAGE_TYPE_NOT_ALLOWED', 415))
    const { wrapper } = await setup()
    await uploadImage(wrapper)

    expect(wrapper.text()).toContain('图片类型不被接受')
    wrapper.unmount()
  })

  it(`一次最多 ${IMAGE_LIMIT} 张图片，多余的在本地就拦下`, async () => {
    const { wrapper } = await setup()
    await uploadImage(wrapper, [
      imageFile('a.jpg'), imageFile('b.jpg'), imageFile('c.jpg'), imageFile('d.jpg'),
    ])

    expect(attachmentsApi.uploadImage).toHaveBeenCalledTimes(IMAGE_LIMIT)
    expect(wrapper.text()).toContain(`一次最多带上 ${IMAGE_LIMIT} 张图片`)
    wrapper.unmount()
  })

  it('刷新已有会话时，尚未随消息发出的图片附件与类别照常出现在草稿区', async () => {
    vi.mocked(attachmentsApi.list).mockResolvedValue([imageAttachment])
    const { wrapper } = await setup('/app/consultations/c1')
    await flushPromises()

    expect(wrapper.text()).toContain('检查单.jpg')
    expect(wrapper.text()).toContain('1600×1200')
    expect(wrapper.text()).toContain('报告 / 检查单')
    wrapper.unmount()
  })

  it('刷新已有会话时，普通图片的类别与边界照常恢复', async () => {
    vi.mocked(attachmentsApi.list).mockResolvedValue([
      { ...imageAttachment, id: 'i-u1', displayName: '风景.jpg', imageCategory: 'unrelated' },
    ])
    const { wrapper } = await setupConsented('/app/consultations/c1')
    await flushPromises()

    expect(wrapper.text()).toContain('风景.jpg')
    expect(wrapper.text()).toContain('普通图片')
    expect(wrapper.text()).toContain('未检测到医疗健康相关内容')
    wrapper.unmount()
  })

  /**
   * 用户 2026-09-22 报告：给 AI 发送图片后，输入框里还留着这张图，每次都要手动点「移除」。
   * 原因是新会话发完第一条消息会 `router.replace` → HomeView 重新挂载 → 服务端把该会话的
   * **全部**附件读回草稿区（后端 `list_attachments` 不排除已绑定消息的行）。修法是草稿区按
   * 「尚未随消息发出」过滤，这里就把重新挂载后的状态钉死。
   */
  it('已随消息发出的图片不再回到草稿区', async () => {
    vi.mocked(attachmentsApi.list).mockResolvedValue([imageAttachment])
    vi.mocked(consultationsApi.messages).mockResolvedValue({
      items: [{
        ...userMessage,
        attachments: [{
          id: 'i1', displayName: '检查单.jpg', kind: 'image', status: 'ready', imageCategory: 'report',
        }],
      }],
      hasMore: false,
    })
    const { wrapper } = await setup('/app/consultations/c1')
    await flushPromises()

    // 历史消息里照常显示这张图，但草稿区不能再有它，也不能再出现「移除」按钮。
    expect(wrapper.text()).toContain('检查单.jpg')
    expect(wrapper.findAll('.attachment-item')).toHaveLength(0)
    expect(wrapper.find('button[aria-label="移除 检查单.jpg"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('已随消息发出的文档同样不再回到草稿区', async () => {
    vi.mocked(attachmentsApi.list).mockResolvedValue([documentAttachment])
    vi.mocked(consultationsApi.messages).mockResolvedValue({
      items: [{
        ...userMessage,
        attachments: [{ id: 'd1', displayName: '血常规报告.pdf', kind: 'pdf', status: 'ready' }],
      }],
      hasMore: false,
    })
    const { wrapper } = await setup('/app/consultations/c1')
    await flushPromises()

    expect(wrapper.findAll('.attachment-item')).toHaveLength(0)
    expect(wrapper.find('button[aria-label="移除 血常规报告.pdf"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('消息里的图片附件', () => {
  function mountAttachments(items: MessageAttachment[]) {
    return mount(MessageAttachments, { props: { items }, global: { plugins: [ElementPlus] } })
  }

  it('走鉴权接口取字节，渲染缩略图并在卸载时释放 Object URL', async () => {
    const wrapper = mountAttachments([
      { id: 'i1', displayName: '检查单.jpg', kind: 'image', status: 'ready', imageAvailable: true },
    ])
    await flushPromises()

    expect(attachmentsApi.content).toHaveBeenCalledWith('i1')
    expect(wrapper.get('img').attributes('src')).toBe('blob:preview')
    wrapper.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview')
  })

  it('图片已到期时显示固定墓碑，不再请求字节', async () => {
    const wrapper = mountAttachments([
      { id: 'i1', displayName: '检查单.jpg', kind: 'image', status: 'ready', imageAvailable: false },
    ])
    await flushPromises()

    expect(wrapper.text()).toContain('图片原件已按保留策略清理')
    expect(attachmentsApi.content).not.toHaveBeenCalled()
    expect(wrapper.find('img').exists()).toBe(false)
    wrapper.unmount()
  })

  it('字节接口返回 410 时按到期处理，其它失败只提示暂时无法显示', async () => {
    vi.mocked(attachmentsApi.content).mockRejectedValue(new ApiError('已清理', 'HTTP_410', 410))
    const expiredWrapper = mountAttachments([
      { id: 'i1', displayName: '检查单.jpg', kind: 'image', status: 'ready' },
    ])
    await flushPromises()
    expect(expiredWrapper.text()).toContain('图片原件已按保留策略清理')
    expiredWrapper.unmount()

    vi.mocked(attachmentsApi.content).mockRejectedValue(new ApiError('服务器暂时无法处理请求', 'HTTP_500', 500))
    const failedWrapper = mountAttachments([
      { id: 'i2', displayName: '检查单.jpg', kind: 'image', status: 'ready' },
    ])
    await flushPromises()
    expect(failedWrapper.text()).toContain('图片暂时无法显示')
    failedWrapper.unmount()
  })

  it('已删除的图片附件显示墓碑，且不请求字节', async () => {
    const wrapper = mountAttachments([
      { id: null, displayName: '检查单.jpg', kind: 'image', status: 'deleted' },
    ])
    await flushPromises()

    expect(wrapper.text()).toContain('检查单.jpg（已删除）')
    expect(attachmentsApi.content).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('文件名与识别内容只作为文本渲染，不进 v-html', async () => {
    const wrapper = mountAttachments([
      { id: 'i1', displayName: '<img src=x onerror=alert(1)>', kind: 'pdf', status: 'ready' },
    ])
    await flushPromises()

    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
    expect(wrapper.find('img').exists()).toBe(false)
    wrapper.unmount()
  })
})