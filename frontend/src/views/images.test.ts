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
import { IMAGE_CONSENT_STORAGE_KEY } from '../stores/composerHints'
import { ImagePrepError } from '../composables/imagePrep'
import { IMAGE_LIMIT } from '../composables/useAttachments'
import type { Attachment, MessageAttachment } from '../types/consultations'

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
const imageAttachment: Attachment = {
  id: 'i1', displayName: '检查单.jpg', kind: 'image', byteSize: 234567, charCount: 860,
  preview: '白细胞计数 6.2', status: 'ready', createdAt: '2026-09-21',
  imageCategory: 'report', mimeType: 'image/webp', width: 1600, height: 1200,
  imageAvailable: true, imageExpiresAt: '2026-12-20T10:00:00Z',
}
const aiModels = [
  { id: 'glm-4.7-flash', name: '智谱 GLM-4.7 Flash', provider: 'zhipuai', providerName: '智谱 AI', description: '', isDefault: true, keySource: 'server' as const },
]

function imageFile(name = 'IMG_1234.jpg', type = 'image/jpeg'): File {
  return new File([new Uint8Array(16)], name, { type })
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

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  vi.mocked(consultationsApi.create).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.send).mockResolvedValue(userMessage)
  vi.mocked(consultationsApi.get).mockResolvedValue(conversation)
  vi.mocked(consultationsApi.messages).mockResolvedValue({ items: [userMessage], hasMore: false })
  vi.mocked(consultationsApi.list).mockResolvedValue({ items: [conversation], hasMore: false })
  vi.mocked(modelsApi.list).mockResolvedValue(aiModels)
  vi.mocked(attachmentsApi.list).mockResolvedValue([])
  vi.mocked(attachmentsApi.uploadImage).mockImplementation(async (_cid, file, category) => ({
    ...imageAttachment,
    id: `i-${file.name}`,
    displayName: file.name,
    imageCategory: category,
  }))
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

function pickImages(wrapper: VueWrapper, files: File[]) {
  const input = wrapper.get('input[type="file"][accept*="image/jpeg"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  return input.trigger('change')
}

function dialogButton(label: string) {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('.image-upload button'))
    .find(button => button.textContent?.includes(label))
}

async function chooseCategory(value: string) {
  document.querySelector<HTMLInputElement>(`.image-upload input[type="radio"][value="${value}"]`)?.click()
  await flushPromises()
}

async function agreeConsent() {
  document.querySelector<HTMLInputElement>('.image-upload input[type="checkbox"]')?.click()
  await flushPromises()
}

/** 走完「选图 → 选类别 →（必要时）同意 → 上传」这条主路径。 */
async function uploadImage(
  wrapper: VueWrapper,
  files: File[] = [imageFile()],
  category = 'report',
  agree = true,
) {
  await pickImages(wrapper, files)
  await flushPromises()
  await chooseCategory(category)
  if (agree) await agreeConsent()
  dialogButton('上传并识别')?.click()
  await flushPromises()
}

describe('图片上传与识别（前端）', () => {
  it('图片按钮在回形针左侧，并带无障碍标签', async () => {
    const { wrapper } = await setup()
    const labels = wrapper.findAll('.send-area > button').map(button => button.attributes('aria-label'))
    expect(labels).toContain('添加图片')
    expect(labels[labels.indexOf('添加病历文档') - 1]).toBe('添加图片')
    wrapper.unmount()
  })

  it('选图后先确认类别；没选类别或没同意就传不出去', async () => {
    const { wrapper } = await setup()
    await pickImages(wrapper, [imageFile('血常规.jpg')])
    await flushPromises()

    expect(document.body.textContent).toContain('上传图片')
    expect(document.body.textContent).toContain('血常规.jpg')
    expect(dialogButton('上传并识别')?.disabled).toBe(true)

    await chooseCategory('report')
    // 未同意敏感信息与外发说明时仍不可上传
    expect(dialogButton('上传并识别')?.disabled).toBe(true)
    expect(document.body.textContent).toContain('阿里云视觉模型')
    expect(document.body.textContent).toContain('建议先遮挡')

    await agreeConsent()
    expect(dialogButton('上传并识别')?.disabled).toBe(false)
    dialogButton('上传并识别')?.click()
    await flushPromises()

    expect(attachmentsApi.uploadImage).toHaveBeenCalledWith('c1', expect.any(File), 'report')
    expect(wrapper.text()).toContain('血常规.jpg')
    wrapper.unmount()
  })

  it('取消弹窗不上传、也不建会话', async () => {
    const { wrapper } = await setup()
    await pickImages(wrapper, [imageFile()])
    await flushPromises()
    await chooseCategory('report')
    await agreeConsent()
    dialogButton('取消')?.click()
    await flushPromises()

    expect(attachmentsApi.uploadImage).not.toHaveBeenCalled()
    expect(consultationsApi.create).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('三类各自显示不同的能力边界文案，都不给疾病判断', async () => {
    const { wrapper } = await setup()
    await pickImages(wrapper, [imageFile()])
    await flushPromises()

    await chooseCategory('medical_imaging')
    expect(document.body.textContent).toContain('不判断病灶')

    await chooseCategory('body_photo')
    expect(document.body.textContent).toContain('不判断是什么病')
    expect(document.body.textContent).toContain('120')

    await chooseCategory('report')
    expect(document.body.textContent).toContain('以纸质报告为准')
    wrapper.unmount()
  })

  it('已同意过的用户不再勾选，但仍会看到提醒', async () => {
    localStorage.setItem(IMAGE_CONSENT_STORAGE_KEY, 'true')
    const { wrapper } = await setup()
    await pickImages(wrapper, [imageFile()])
    await flushPromises()

    expect(document.querySelector('.image-upload input[type="checkbox"]')).toBeNull()
    expect(document.body.textContent).toContain('建议先遮挡')
    await chooseCategory('report')
    expect(dialogButton('上传并识别')?.disabled).toBe(false)
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

  it('刷新已有会话时，服务端返回的图片附件照常出现在草稿区', async () => {
    vi.mocked(attachmentsApi.list).mockResolvedValue([imageAttachment])
    const { wrapper } = await setup('/app/consultations/c1')
    await flushPromises()

    expect(wrapper.text()).toContain('检查单.jpg')
    expect(wrapper.text()).toContain('1600×1200')
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