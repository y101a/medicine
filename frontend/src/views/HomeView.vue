<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { consultationsApi, type RetrievalProgress } from '../api/consultations'
import { modelsApi } from '../api/models'
import { useConsultationsStore } from '../stores/consultations'
import { useAuthStore } from '../stores/auth'
import { useHealthRecordsStore } from '../stores/healthRecords'
import { ApiError, getApiErrorMessage } from '../api/http'
import type { AiModel, AnswerFormat, FollowUpAnswers, FollowUpCard, Message } from '../types/consultations'
import { Top, ChatDotRound, Compass, Document, CloseBold, Microphone, Paperclip, Picture } from '@element-plus/icons-vue'
import medicalAiAvatar from '../assets/medical-ai-avatar.png'
import AssistantAnswerCard from '../components/AssistantAnswerCard.vue'
import StructuredFollowUpCard from '../components/StructuredFollowUpCard.vue'
import EmergencyTriageCard from '../components/EmergencyTriageCard.vue'
import ReferenceSources from '../components/ReferenceSources.vue'
import MessageAttachments from '../components/MessageAttachments.vue'
import HospitalNavigator from '../components/HospitalNavigator.vue'
import PathologyCardOffer from '../components/PathologyCardOffer.vue'
import { readRetrievalNotice, rememberRetrievalNotice } from '../stores/retrievalNotices'
import {
  readVoiceTipSeen, rememberVoiceTipSeen, readVoiceConsentSeen, rememberVoiceConsentSeen,
  readDocumentNoticeSeen, rememberDocumentNoticeSeen, readImageConsentSeen, rememberImageConsentSeen,
} from '../stores/composerHints'
import { useVoiceRecorder } from '../composables/useVoiceRecorder'
import { useAttachments, formatAttachmentSize, ATTACHMENT_LIMIT, IMAGE_LIMIT } from '../composables/useAttachments'
import { isUndecodableImage, type ImageCategory } from '../composables/imagePrep'
import ImageUploadDialog from '../components/ImageUploadDialog.vue'
import { voiceApi } from '../api/voice'

const route = useRoute()
const router = useRouter()
const recent = useConsultationsStore()
const auth = useAuthStore()
const healthRecords = useHealthRecordsStore()
const draft = ref(typeof route.query.prompt === 'string' && !route.params.id ? route.query.prompt : '')
const messages = ref<Message[]>([])
const loading = ref(false)
const saving = ref(false)
const generating = ref(false)
const error = ref('')
const retrievalNotice = ref('')
const voiceTipSeen = ref(readVoiceTipSeen())
const ready = ref(!route.params.id)
const hasOlder = ref(false)
const title = ref('')
const models = ref<AiModel[]>([])
const modelsLoading = ref(true)
const modelsError = ref('')
const selectedModelId = ref('')
const cardGeneratingSourceId = ref('')
let cid = typeof route.params.id === 'string' ? route.params.id : ''
const createRequestId = crypto.randomUUID()
let pending: { content: string; id: string } | null = null
let generationController: AbortController | undefined
const input = ref<HTMLTextAreaElement>()
const messageList = ref<HTMLElement>()
const suggestions = [
  { title: '了解症状', text: '身体有些不舒服，想了解可能原因', icon: ChatDotRound, prompt: '我想了解这些症状的可能原因：' },
  { title: '就医指引', text: '不知道该挂哪个科，先聊一聊', icon: Compass, prompt: '我想了解应该去哪个科室就诊。我的情况是：' },
  { title: '读懂术语', text: '把陌生的医学名词讲明白', icon: Document, prompt: '请用通俗的语言解释这个医学术语：' },
]
// 与后端 `schemas/consultations.py` 的 content max_length 保持一致。
const DRAFT_LIMIT = 2000
// 语音输入多为连续长句，容易不知不觉逼近上限；接近时提醒用户分次发送。
const DRAFT_NEAR_LIMIT = 1800
const DEFAULT_ATTACHMENT_PROMPT = '请帮我解读上传的病历文档，解释其中的医学术语和指标，并在必要时给出就医分流建议；不要作出确诊。'
// 只传图片时的默认提问：仍然只要「整理可见信息 + 下一步看什么科」，不要疾病判断。
const IMAGE_ATTACHMENT_PROMPT = '请根据我上传的图片，帮我整理能读到的信息（报告上的指标，或片子和照片上肉眼可见、非诊断性的情况），并说明下一步该看什么科；不要作出确诊，也不要判读影像。'
const VOICE_TIP_AUTO_HIDE_MS = 8_000
const VOICE_NOTICE_AUTO_HIDE_MS = 5_000
let voiceTipTimer: ReturnType<typeof setTimeout> | undefined
const nearDraftLimit = computed(() => draft.value.length >= DRAFT_NEAR_LIMIT)
function dismissVoiceTip() {
  if (voiceTipTimer !== undefined) clearTimeout(voiceTipTimer)
  voiceTipTimer = undefined
  voiceTipSeen.value = true
  rememberVoiceTipSeen()
}
const voiceConsentSeen = ref(readVoiceConsentSeen())
const voiceNotice = ref('')
const {
  state: voiceState,
  seconds: voiceSeconds,
  error: voiceError,
  supported: voiceSupported,
  start: startRecorder,
  stop: stopRecorder,
  cancel: cancelRecorder,
  reset: resetRecorder,
} = useVoiceRecorder()

const displayedVoiceNotice = computed(() => voiceNotice.value || voiceError.value)
const voiceNoticeVisible = ref(false)
let voiceNoticeTimer: ReturnType<typeof setTimeout> | undefined

function dismissVoiceNotice() {
  if (voiceNoticeTimer !== undefined) clearTimeout(voiceNoticeTimer)
  voiceNoticeTimer = undefined
  voiceNoticeVisible.value = false
}

watch(displayedVoiceNotice, (message) => {
  dismissVoiceNotice()
  if (!message) return
  voiceNoticeVisible.value = true
  voiceNoticeTimer = setTimeout(dismissVoiceNotice, VOICE_NOTICE_AUTO_HIDE_MS)
}, { immediate: true })

async function startRecording() {
  voiceNotice.value = ''
  if (!voiceConsentSeen.value) {
    try {
      await ElMessageBox.confirm(
        '录音会发送到语音识别服务转成文字，识别完成后不保存音频。请勿说出姓名、身份证号、住院号或手机号。',
        '开始语音输入',
        { confirmButtonText: '开始录音', cancelButtonText: '取消', type: 'info' },
      )
    } catch {
      return
    }
    voiceConsentSeen.value = true
    rememberVoiceConsentSeen()
  }
  await startRecorder()
}

/** 转写文本只追加到草稿，不覆盖用户已经输入的内容；超长按上限截断。 */
function appendTranscript(text: string) {
  const spoken = text.trim()
  if (!spoken) {
    voiceNotice.value = '没有听清，请再说一次'
    return
  }
  const merged = draft.value ? `${draft.value}${spoken}` : spoken
  if (merged.length > DRAFT_LIMIT) {
    draft.value = merged.slice(0, DRAFT_LIMIT)
    voiceNotice.value = `语音内容超过 ${DRAFT_LIMIT} 字上限，已截断，请分多次发送`
    return
  }
  draft.value = merged
  voiceNotice.value = ''
}

async function finishRecording() {
  const audio = await stopRecorder()
  if (!audio) {
    resetRecorder()
    return
  }
  try {
    appendTranscript((await voiceApi.transcribe(audio)).text)
  } catch (cause) {
    voiceNotice.value = getApiErrorMessage(cause)
  } finally {
    resetRecorder()
  }
}

function cancelRecording() {
  cancelRecorder()
  voiceNotice.value = ''
}

function toggleRecording() {
  if (voiceState.value === 'recording') void finishRecording()
  else void startRecording()
}

const voiceTitle = computed(() => {
  if (!voiceSupported) return '当前浏览器不支持录音，请改用输入法语音输入'
  if (voiceState.value === 'recording') return '停止录音并转写'
  return '语音输入：录一段语音转成文字'
})

const documentNoticeSeen = ref(readDocumentNoticeSeen())
const imageConsentSeen = ref(readImageConsentSeen())
const fileInput = ref<HTMLInputElement>()
const imageInput = ref<HTMLInputElement>()
const dragging = ref(false)
const imageDialogVisible = ref(false)
/** 已选入、等待用户在弹窗里确认类别的图片（还没上传任何字节）。 */
const pendingImageFiles = ref<File[]>([])
const {
  items: attachments,
  previews: attachmentPreviews,
  imageCount,
  pendingName: attachmentPendingName,
  uploading: attachmentUploading,
  error: attachmentError,
  addFiles: addAttachments,
  addImages: addImageAttachments,
  load: loadAttachments,
  remove: removeAttachment,
  reset: resetAttachments,
  releasePreviews: releaseAttachmentPreviews,
} = useAttachments()

const attachTitle = computed(() => attachments.value.length >= ATTACHMENT_LIMIT
  ? `一次最多带上 ${ATTACHMENT_LIMIT} 份附件`
  : '添加病历文档：解析成文字后随问题一起交给模型')
const imageTitle = computed(() => imageCount.value >= IMAGE_LIMIT
  ? `一次最多带上 ${IMAGE_LIMIT} 张图片`
  : '添加图片：报告单、片子或患处照片，识别出的内容会随问题一起交给模型')
const composerPlaceholder = computed(() => attachments.value.length
  ? '可直接发送文档或图片，或补充你希望重点了解的问题……'
  : '描述您的症状或健康疑问，例如：什么时候开始、持续多久……')


function chooseFiles() {
  if (!attachmentUploading.value) fileInput.value?.click()
}

function chooseImages() {
  if (!attachmentUploading.value) imageInput.value?.click()
}

/**
 * 附件上传挂在会话下（`POST /consultations/{id}/attachments`），而首页在发出第一条消息前
 * 还没有会话。按已确认的做法：选中文档时**先静默创建会话**——不产生任何消息，也不进入问答链路。
 */
async function ensureConsultation(): Promise<string> {
  if (cid) return cid
  cid = (await consultationsApi.create(createRequestId)).id
  return cid
}

async function handleFiles(files: File[]) {
  if (!files.length) return
  if (!documentNoticeSeen.value) {
    try {
      await ElMessageBox.confirm(
        '文档会在本站解析成文字并加密保存，原件不保存；点发送时，解析出的文字会随问题一起交给模型。请勿上传他人的病历。',
        '上传病历文档',
        { confirmButtonText: '我知道了，继续上传', cancelButtonText: '取消', type: 'info' },
      )
    } catch {
      return
    }
    documentNoticeSeen.value = true
    rememberDocumentNoticeSeen()
  }
  await addAttachments(files, ensureConsultation)
}

function onFilePicked(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  target.value = ''
  void handleFiles(files)
}

/** 拖进来的可能是文档也可能是图片，也可能是 HEIC（浏览器解不开，要单独给说法）。 */
function looksLikeImage(file: File) {
  return file.type.startsWith('image/') || isUndecodableImage(file)
}

function openImageDialog(files: File[]) {
  if (!files.length) return
  pendingImageFiles.value = files
  imageDialogVisible.value = true
}

function onImagePicked(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  target.value = ''
  openImageDialog(files)
}

/**
 * 类别由用户在弹窗里选；首次上传还要勾选敏感信息与外发说明（服务端也会校验 `noticeAccepted`）。
 * 选完只上传、不发送——识别结果要用户自己核对后再点发送。
 */
async function confirmImages(category: ImageCategory) {
  imageDialogVisible.value = false
  const files = pendingImageFiles.value
  pendingImageFiles.value = []
  if (!imageConsentSeen.value) {
    imageConsentSeen.value = true
    rememberImageConsentSeen()
  }
  await addImageAttachments(files, category, ensureConsultation)
}

function onDrop(event: DragEvent) {
  dragging.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  const images = files.filter(looksLikeImage)
  if (images.length) openImageDialog(images)
  void handleFiles(files.filter(file => !looksLikeImage(file)))
}
function modelName(message: Message) {
  if (message.modelName) return message.modelName
  if (!message.modelId) return ''
  return models.value.find(model => model.id === message.modelId)?.name || message.modelId
}
function generationStatus(message: Message) {
  if (message.generationStatus === 'stopped') return '已停止'
  if (message.generationStatus === 'failed') return '生成中断'
  if (message.generationStatus === 'completed') return '生成完成'
  return '已保存'
}
function explainRetrieval(progress: RetrievalProgress): string {
  if (progress.gateReason !== 'medical_content') return ''
  if (progress.status === 'completed') {
    if (!progress.coverageLimited) return ''
    return progress.webSearchStatus === 'failed'
      ? '现有资料只覆盖部分相关疾病，官网搜索未成功；下面的回答不能视为完整清单。'
      : '参考资料只覆盖部分相关疾病，下面的回答不能视为完整清单。'
  }
  if (progress.status === 'failed') {
    return '本地医学资料暂时无法检索。本轮回答没有可核验的参考资料，请勿将其作为诊断依据。'
  }
  if (progress.status !== 'empty') return ''
  if (progress.webSearchStatus === 'failed') {
    const reason = progress.webSearchErrorCode === 'WEB_SEARCH_TIMEOUT'
      ? '官网搜索超时'
      : '官网搜索暂时不可用'
    return `本地资料不足，且${reason}。本轮回答没有可核验的参考资料，请勿将其作为诊断依据。`
  }
  if (progress.webSearchStatus === 'empty') {
    return '本地资料和官网搜索均未找到可引用的相关资料。本轮回答仅供一般科普，不能据此判断具体病情。'
  }
  return '本地资料暂未找到相关证据，且未进行官网搜索。本轮回答没有可核验的参考资料。'
}
async function loadModels() {
  modelsLoading.value = true
  modelsError.value = ''
  try {
    models.value = await modelsApi.list()
    const preferred = models.value.find(model => model.isDefault) || models.value[0]
    if (!models.value.some(model => model.id === selectedModelId.value)) {
      selectedModelId.value = preferred?.id || ''
    }
    if (!models.value.length) modelsError.value = '暂无可用模型；紧急症状预检仍可使用，普通问题将先保存但不能生成回答'
  } catch (e) {
    modelsError.value = getApiErrorMessage(e)
  } finally {
    modelsLoading.value = false
  }
}
function pick(prompt: string) { draft.value = prompt; input.value?.focus() }
function scrollBottom(behavior: ScrollBehavior = 'smooth') {
  void nextTick(() => messageList.value?.scrollTo({
    top: messageList.value.scrollHeight,
    behavior,
  }))
}
async function load(older = false) {
  if (!cid || loading.value) return
  const userId = auth.user?.id
  loading.value = true
  error.value = ''
  try {
    const [conversation, page] = await Promise.all([
      consultationsApi.get(cid),
      consultationsApi.messages(cid, older ? messages.value[0]?.sequence : undefined),
    ])
    if (auth.user?.id !== userId) return
    if (!older) retrievalNotice.value = readRetrievalNotice(auth.user?.id, cid)
    title.value = conversation.title
    if (!older) void loadAttachments(cid)
    messages.value = older ? [...page.items, ...messages.value] : page.items
    hasOlder.value = page.hasMore
    ready.value = true
    if (!older) {
      await nextTick()
      messageList.value?.scrollTo({ top: messageList.value.scrollHeight })
    }
  } catch (e) { error.value = getApiErrorMessage(e) }
  finally { loading.value = false }
}
onMounted(() => {
  void loadModels()
  if (cid) void load()
  else if (draft.value) nextTick(() => input.value?.focus())
  if (!voiceTipSeen.value) {
    voiceTipTimer = setTimeout(dismissVoiceTip, VOICE_TIP_AUTO_HIDE_MS)
  }
})
onBeforeUnmount(() => {
  if (voiceTipTimer !== undefined) clearTimeout(voiceTipTimer)
  if (voiceNoticeTimer !== undefined) clearTimeout(voiceNoticeTimer)
  // 本地缩略图是内存里的 Object URL，卸载时必须释放。
  releaseAttachmentPreviews()
})
const retryableModelErrors = new Set([
  'AI_PROVIDER_TIMEOUT',
  'AI_PROVIDER_UNAVAILABLE',
  'AI_PROVIDER_ERROR',
  'AI_PROVIDER_BUSY',
  'AI_EMPTY_RESPONSE',
  'AI_INVALID_STRUCTURED_RESPONSE',
  'STREAM_INCOMPLETE',
])
function nextBackupModel(attempted: Set<string>) {
  return models.value.find(model => !attempted.has(model.id))
}
async function generateAnswer(
  userMessage: Message,
  modelId: string,
  answerFormat: AnswerFormat,
  attempted = new Set<string>(),
) {
  retrievalNotice.value = ''
  rememberRetrievalNotice(auth.user?.id, cid, '')
  attempted.add(modelId)
  const requestId = crypto.randomUUID()
  const requestedModel = models.value.find(model => model.id === modelId)
  const placeholder: Message = {
    id: `stream-${requestId}`,
    role: 'assistant',
    content: '',
    sequence: userMessage.sequence + 1,
    provider: requestedModel?.provider,
    modelId,
    modelName: requestedModel?.name,
    createdAt: new Date().toISOString(),
  }
  messages.value.push(placeholder)
  generationController = new AbortController()
  generating.value = true
  scrollBottom()
  try {
    const completed = await consultationsApi.stream(
      cid,
      requestId,
      modelId,
      answerFormat,
      generationController.signal,
      (chunk) => {
        placeholder.content += chunk
        scrollBottom()
      },
      (progress) => {
        retrievalNotice.value = explainRetrieval(progress)
        rememberRetrievalNotice(auth.user?.id, cid, retrievalNotice.value)
        scrollBottom()
      },
    )
    const index = messages.value.findIndex(item => item.id === placeholder.id)
    if (index >= 0) messages.value[index] = completed
    generating.value = false
    generationController = undefined
    void recent.load()
    // 回答完成后按本轮助手回答触发健康记录增量更新：医疗内容判定记在助手消息上，
    // 后端会回溯对应的用户提问再抽取，失败也不影响对话。
    void healthRecords.syncFromMessage(cid, completed.id)
    if (route.params.id !== cid) {
      await router.replace({ name: 'consultation', params: { id: cid } })
    } else {
      scrollBottom()
    }
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === 'AbortError') {
      if (placeholder.content && !placeholder.content.includes('（回答已停止生成）')) {
        placeholder.content += '\n\n（回答已停止生成）'
      }
      return
    }

    const message = getApiErrorMessage(caught)
    const hasPartialAnswer = Boolean(placeholder.content)
    if (!hasPartialAnswer) {
      messages.value = messages.value.filter(item => item.id !== placeholder.id)
    }
    const canTryBackup = caught instanceof ApiError
      && retryableModelErrors.has(caught.code)
      && !hasPartialAnswer
    const backup = canTryBackup ? nextBackupModel(attempted) : undefined
    if (!backup) {
      error.value = hasPartialAnswer
        ? `${message}；已保留生成的部分内容，可切换模型后重新提问。`
        : message
      return
    }

    error.value = `${message}；可以切换至 ${backup.name} 继续生成。`
    let confirmed = false
    try {
      await ElMessageBox.confirm(
        `当前模型未能返回回答，是否切换至“${backup.name}”重试？不会重复保存您的问题。`,
        '切换备用模型',
        {
          confirmButtonText: '切换并重试',
          cancelButtonText: '暂不切换',
          type: 'warning',
        },
      )
      confirmed = true
    } catch {
      confirmed = false
    }
    if (confirmed) {
      selectedModelId.value = backup.id
      error.value = ''
      ElMessage.info(`已切换至 ${backup.name}，正在重新生成`)
      await generateAnswer(userMessage, backup.id, answerFormat, attempted)
    }
  } finally {
    generating.value = false
    generationController = undefined
    input.value?.focus()
  }
}
function followUpAnswered(message: Message) {
  return messages.value.some(item => item.role === 'user' && item.sequence > message.sequence)
}
function formatFollowUpAnswers(card: FollowUpCard, answers: FollowUpAnswers) {
  const lines = card.questions.map((question) => {
    const raw = answers[question.id]
    const values = Array.isArray(raw) ? raw : [raw]
    const labels = values.map((value) => {
      const option = question.options.find(item => item.value === value)
      return option?.label || String(value)
    })
    return `- ${question.label}：${labels.join('、')}`
  })
  return `补充信息：\n${lines.join('\n')}`
}
async function sendContent(content: string, clearDraft = false) {
  // 录音、转写与文档上传期间都不接受发送：转写文字和文档解析结果都必须先让用户核对。
  if (voiceState.value !== 'idle' || attachmentUploading.value) return
  if (!content || content.length > 2000 || saving.value || generating.value || loading.value || !ready.value) return
  if (!pending || pending.content !== content) pending = { content, id: crypto.randomUUID() }
  const userId = auth.user?.id
  saving.value = true
  error.value = ''
  try {
    if (!cid) cid = (await consultationsApi.create(createRequestId)).id
    // 附件只在主发送时带上：追问与卡片生成不重复引用同一份文档。
    const attachmentIds = clearDraft ? attachments.value.map(item => item.id) : []
    const message = await consultationsApi.send(cid, pending.content, pending.id, attachmentIds)
    if (auth.user?.id !== userId) return
    if (!messages.value.some(item => item.id === message.id)) messages.value.push(message)
    if (clearDraft) {
      draft.value = ''
      // 文档已经挂在消息上，草稿区不再重复显示，避免下次发送误带旧文档。
      resetAttachments()
    }
    pending = null
    void recent.load()
    saving.value = false
    if (message.triage?.level === 'emergency') {
      if (route.params.id !== cid) {
        await router.replace({ name: 'consultation', params: { id: cid } })
      } else {
        scrollBottom()
      }
      return
    }
    if (!selectedModelId.value) {
      error.value = '问题已保存，但当前没有可用模型，暂时无法生成科普回答。'
      return
    }
    await generateAnswer(message, selectedModelId.value, 'plain')
  } catch (e) { error.value = getApiErrorMessage(e) }
  finally { saving.value = false }
}
async function send() {
  // 没写文字时按附件类型给默认提问：图片不能被当成病历文档解读（反之亦然）。
  const fallback = attachments.value.some(item => item.kind === 'image')
    ? IMAGE_ATTACHMENT_PROMPT
    : DEFAULT_ATTACHMENT_PROMPT
  const content = draft.value.trim() || (attachments.value.length ? fallback : '')
  await sendContent(content, true)
}
async function submitFollowUp(message: Message, answers: FollowUpAnswers) {
  if (!message.followUp || followUpAnswered(message)) return
  await sendContent(formatFollowUpAnswers(message.followUp, answers))
}
function stopGeneration() {
  generationController?.abort()
}

function canOfferPathologyCard(message: Message) {
  return message.role === 'assistant'
    && (message.answerFormat || 'plain') === 'plain'
    && message.medicalContent === true
    && message.generationStatus === 'completed'
    && !message.followUp
    && !messages.value.some(
      item => item.sourceMessageId === message.id
        && item.generationStatus === 'completed'
        && !item.id.startsWith('stream-'),
    )
}

async function generatePathologyCard(source: Message) {
  if (!cid || generating.value || saving.value || !selectedModelId.value) return
  const requestId = crypto.randomUUID()
  const requestedModel = models.value.find(model => model.id === selectedModelId.value)
  const placeholder: Message = {
    id: `stream-${requestId}`,
    role: 'assistant',
    content: '',
    sequence: Math.max(0, ...messages.value.map(item => item.sequence)) + 1,
    provider: requestedModel?.provider,
    modelId: selectedModelId.value,
    modelName: requestedModel?.name,
    generationStatus: 'completed',
    answerFormat: 'card',
    medicalContent: true,
    sourceMessageId: source.id,
    createdAt: new Date().toISOString(),
  }
  messages.value.push(placeholder)
  generationController = new AbortController()
  generating.value = true
  cardGeneratingSourceId.value = source.id
  error.value = ''
  scrollBottom()
  try {
    const completed = await consultationsApi.stream(
      cid,
      requestId,
      selectedModelId.value,
      'card',
      generationController.signal,
      (chunk) => {
        placeholder.content += chunk
        scrollBottom()
      },
      () => undefined,
      source.id,
    )
    const index = messages.value.findIndex(item => item.id === placeholder.id)
    if (index >= 0) messages.value[index] = completed
    void recent.load()
    scrollBottom()
  } catch (caught) {
    const hasPartialAnswer = Boolean(placeholder.content)
    if (!hasPartialAnswer) {
      messages.value = messages.value.filter(item => item.id !== placeholder.id)
    }
    if (caught instanceof DOMException && caught.name === 'AbortError') {
      if (hasPartialAnswer) placeholder.content += '\n\n（卡片已停止生成）'
    } else {
      error.value = getApiErrorMessage(caught)
    }
  } finally {
    generating.value = false
    generationController = undefined
    cardGeneratingSourceId.value = ''
  }
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}
async function canLeave() {
  if (!auth.isAuthenticated) {
    generationController?.abort()
    return true
  }
  if (generating.value) {
    try {
      await ElMessageBox.confirm('AI 回答仍在生成，离开将停止本次生成。确定离开吗？', '停止生成', {
        confirmButtonText: '停止并离开', cancelButtonText: '继续等待',
      })
      generationController?.abort()
      return true
    } catch { return false }
  }
  if (attachmentUploading.value) {
    try {
      await ElMessageBox.confirm('附件正在上传解析，离开会中断本次上传。确定离开吗？', '中断上传', {
        confirmButtonText: '中断并离开', cancelButtonText: '继续等待',
      })
      return true
    } catch { return false }
  }
  if (saving.value) return false
  if (!draft.value.trim()) return true
  try {
    await ElMessageBox.confirm('输入的消息尚未保存，确定离开吗？', '离开咨询', {
      confirmButtonText: '离开', cancelButtonText: '继续编辑',
    })
    return true
  } catch { return false }
}
onBeforeRouteLeave(canLeave)
onBeforeRouteUpdate(canLeave)
</script>

<template>
  <main class="chat-page">
    <div ref="messageList" class="conversation">
      <p v-if="loading" role="status">正在加载消息…</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <el-button v-if="!ready && error" @click="load()">重新加载</el-button>
      <el-button v-if="hasOlder" :loading="loading" @click="load(true)">加载更早的消息</el-button>
      <section v-if="ready && !messages.length" class="welcome">
        <div class="welcome-mark" aria-hidden="true">✦</div>
        <p class="eyebrow">关于健康，我们慢慢聊</p>
        <h1>今天，有什么想了解的？</h1>
        <p class="intro">从身体的一个小变化开始，<br />一起把症状、疑问和下一步理清楚。</p>
        <div class="suggestions">
          <button v-for="item in suggestions" :key="item.title" @click="pick(item.prompt)">
            <el-icon :size="20"><component :is="item.icon" /></el-icon>
            <strong>{{ item.title }}</strong><span>{{ item.text }}</span>
          </button>
        </div>
      </section>
      <section v-else-if="ready" class="messages" aria-label="咨询消息" aria-live="polite">
        <p class="saved-heading">{{ title || '当前咨询' }}</p>
        <div v-for="message in messages" :key="message.id" class="message-pair">
          <template v-if="message.role === 'user'">
            <div class="user-message">{{ message.content }}</div>
            <div v-if="message.attachments?.length" class="user-attachments">
              <MessageAttachments :items="message.attachments" />
            </div>
            <EmergencyTriageCard v-if="message.triage" :triage="message.triage" />
          </template>
          <div v-else class="assistant-message">
            <img class="assistant-avatar" :src="medicalAiAvatar" alt="医疗 AI 助手" />
            <div class="assistant-body">
              <strong>科普助手<span v-if="modelName(message)" class="answer-model">{{ modelName(message) }}</span></strong>
              <MessageAttachments :items="message.attachments || []" label="本次回答参考了：" />
              <StructuredFollowUpCard v-if="message.followUp" :card="message.followUp"
                :disabled="saving || generating" :answered="followUpAnswered(message)"
                @submit="submitFollowUp(message, $event)" />
              <AssistantAnswerCard v-else :content="message.content" :streaming="generating && message.id.startsWith('stream-')" />
              <ReferenceSources
                v-if="!message.followUp && message.citations?.length"
                :citations="message.citations"
              />
              <PathologyCardOffer
                v-if="canOfferPathologyCard(message)"
                :loading="cardGeneratingSourceId === message.id"
                @generate="generatePathologyCard(message)"
              />
            </div>
          </div>
          <p class="saved-at" :class="{ assistant: message.role === 'assistant' }">
            {{ message.id.startsWith('stream-') ? (generating ? '正在生成' : '本次回答') : generationStatus(message) }} · {{ new Date(message.createdAt).toLocaleString('zh-CN') }}
          </p>
        </div>
        <el-alert v-if="retrievalNotice" class="retrieval-notice" :title="retrievalNotice" type="warning" :closable="false" show-icon />
      </section>
    </div>
    <div class="composer-area">
      <form class="composer" :class="{ dragging }" @submit.prevent="send"
        @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
        <el-alert v-if="modelsError" class="model-error" :title="modelsError" type="warning" :closable="false" />
        <el-alert v-if="!voiceTipSeen" class="voice-tip" type="info" show-icon
          title="可用输入法上的麦克风语音输入（如豆包输入法），也可以点发送键左侧的麦克风按钮直接录音。语音识别可能出错，发送前请核对文字；请不要在对话中提供姓名、身份证号、住院号或手机号。"
          @close="dismissVoiceTip" />
        <el-alert v-if="voiceNoticeVisible && displayedVoiceNotice" class="voice-notice" type="warning" show-icon
          :title="displayedVoiceNotice" @close="dismissVoiceNotice" />
        <el-alert v-if="attachmentError" class="attachment-notice" type="warning" show-icon
          :title="attachmentError" :closable="false" />
        <div v-if="attachments.length || attachmentUploading" class="attachment-tray">
          <span v-for="item in attachments" :key="item.id" class="attachment-item">
            <img v-if="item.kind === 'image' && attachmentPreviews[item.id]" class="attachment-thumb"
              :src="attachmentPreviews[item.id]" :alt="`待上传图片：${item.displayName}`" />
            <span class="attachment-name">{{ item.displayName }}</span>
            <span class="attachment-meta">
              <template v-if="item.kind === 'image'">{{ formatAttachmentSize(item.byteSize) }}<template v-if="item.width && item.height"> · {{ item.width }}×{{ item.height }}</template> · {{ item.charCount }} 字</template>
              <template v-else>{{ formatAttachmentSize(item.byteSize) }} · {{ item.charCount }} 字<template v-if="item.pageCount"> · {{ item.pageCount }} 页</template></template>
            </span>
            <button type="button" class="attachment-remove" :aria-label="`移除 ${item.displayName}`" title="移除" @click="removeAttachment(item.id)">移除</button>
          </span>
          <span v-if="attachmentUploading" class="attachment-item pending">正在解析 {{ attachmentPendingName }}…</span>
        </div>
        <input ref="fileInput" class="sr-only" type="file" multiple accept=".pdf,.docx,.pptx,.txt,.md" @change="onFilePicked" />
        <input ref="imageInput" class="sr-only" type="file" multiple
          accept="image/jpeg,image/png,image/webp" @change="onImagePicked" />
        <label class="sr-only" for="symptom-input">症状或健康问题</label>
        <textarea id="symptom-input" ref="input" v-model="draft" :maxlength="DRAFT_LIMIT" rows="3" :disabled="saving || generating || !ready"
          :placeholder="composerPlaceholder" @keydown="keydown"></textarea>
        <div class="composer-bottom">
          <HospitalNavigator />
          <div class="send-area">
            <el-select
              v-model="selectedModelId"
              class="model-select"
              aria-label="选择回答模型"
              :disabled="modelsLoading || saving || generating"
              :loading="modelsLoading"
              placeholder="选择模型"
            >
              <el-option
                v-for="model in models"
                :key="model.id"
                :label="model.name"
                :value="model.id"
              >
                <div class="model-option"><span>{{ model.name }}</span><small>{{ model.providerName }}</small></div>
              </el-option>
            </el-select>
            <span>{{ draft.length }}/{{ DRAFT_LIMIT }}</span>
            <span v-if="nearDraftLimit" class="limit-hint">已接近 {{ DRAFT_LIMIT }} 字上限，可分多次发送</span>
            <span v-if="voiceState === 'requesting'" class="voice-status">等待麦克风授权…</span>
            <span v-else-if="voiceState === 'recording'" class="voice-status">录音中 {{ voiceSeconds }}s</span>
            <span v-else-if="voiceState === 'transcribing'" class="voice-status">正在识别…</span>
            <button v-if="voiceState === 'recording'" class="voice-cancel" type="button" @click="cancelRecording">取消</button>
            <button
              class="attach-button"
              type="button"
              :disabled="attachmentUploading || saving || generating || !ready || attachments.length >= ATTACHMENT_LIMIT || imageCount >= IMAGE_LIMIT"
              aria-label="添加图片"
              :title="imageTitle"
              @click="chooseImages"
            ><el-icon :size="18"><Picture /></el-icon></button>
            <button
              class="attach-button"
              type="button"
              :disabled="attachmentUploading || saving || generating || !ready || attachments.length >= ATTACHMENT_LIMIT"
              aria-label="添加病历文档"
              :title="attachTitle"
              @click="chooseFiles"
            ><el-icon :size="18"><Paperclip /></el-icon></button>
            <button
              class="voice-button"
              :class="{ recording: voiceState === 'recording' }"
              type="button"
              :disabled="!voiceSupported || voiceState === 'requesting' || voiceState === 'transcribing' || saving || generating || !ready"
              :aria-label="voiceState === 'recording' ? '停止录音并转写' : '语音输入'"
              :aria-pressed="voiceState === 'recording'"
              :title="voiceTitle"
              @click="toggleRecording"
            ><el-icon :size="18"><Microphone /></el-icon></button>
            <button v-if="generating" class="stop-button" type="button" aria-label="停止生成" title="停止生成" @click="stopGeneration"><el-icon :size="15"><CloseBold /></el-icon></button>
            <button v-else class="send-button" type="submit" :disabled="(!draft.trim() && !attachments.length) || saving || loading || modelsLoading || !ready || voiceState !== 'idle' || attachmentUploading" aria-label="发送消息" title="发送消息"><el-icon :size="20"><Top /></el-icon></button>
          </div>
        </div>
      </form>
      <div class="composer-meta"><span>仅提供健康科普与就医分流，不作确诊，不替代医生；上传的文档不会被用来下诊断。</span><span>可用输入法语音输入（如豆包输入法） · 也可点麦克风录音 · 回形针上传病历文档 · 图片按钮上传报告、片子或患处照片 · Enter 发送 · Shift + Enter 换行</span></div>
    </div>
    <ImageUploadDialog
      v-model="imageDialogVisible"
      :files="pendingImageFiles"
      :consent-seen="imageConsentSeen"
      :uploading="attachmentUploading"
      @confirm="confirmImages"
    />
  </main>
</template>

<style scoped>
.chat-page { height: 100%; display: flex; flex-direction: column; }
.conversation { flex: 1; min-height: 0; overflow-y: auto; padding: 32px 40px; }
.welcome { max-width: 800px; margin: auto; padding: clamp(16px, 6vh, 90px) 0 24px; text-align: center; }
.welcome-mark { color: #237ac2; font-size: 44px; margin-bottom: 22px; }
.eyebrow { color: #8a9aaa; font-size: 13px; letter-spacing: 2px; margin: 0 0 14px; }
h1 { font-size: 34px; font-weight: 600; letter-spacing: 1px; color: #253c52; margin: 0; }
.intro { color: #8393a3; font-size: 14px; line-height: 1.9; margin: 18px 0 35px; }
.suggestions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; text-align: left; }
.suggestions button { display: flex; flex-direction: column; align-items: flex-start; border: 1px solid #e5ebf1; border-radius: 13px; background: #fff; padding: 21px 18px; cursor: pointer; transition: background .15s, border-color .15s; }
.suggestions button:hover { background: #f6faff; border-color: #abcdea; }
.suggestions .el-icon { color: #4885b6; margin-bottom: 17px; }
.suggestions strong { font-size: 14px; color: #3d556b; font-weight: 550; }
.suggestions span { color: #8b99a7; font-size: 11px; margin-top: 8px; line-height: 1.7; }
.composer-area { width: min(880px, calc(100% - 80px)); margin: 0 auto; padding: 16px 0 22px; }
.composer { padding: 18px 20px 12px; border: 1px solid #dce5ed; border-radius: 18px; box-shadow: 0 5px 24px rgb(34 67 97 / 5%); background: #fff; }
.composer:focus-within { border-color: #8cb9de; box-shadow: 0 0 0 3px #f1f7fc; }
textarea { display: block; width: 100%; min-height: 70px; max-height: 200px; resize: vertical; border: none; outline: none; font: inherit; font-size: 14px; line-height: 1.8; color: #324e67; background: transparent; }
textarea::placeholder { color: #99a5b0; }
.composer-bottom, .send-area { display: flex; align-items: center; gap: 12px; }
.composer-bottom { justify-content: space-between; }
.send-area { justify-content: flex-end; }
.model-select { width: 190px; }
.model-option { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.model-option small { color: #93a1ae; }
.model-error, .voice-tip, .voice-notice { margin-bottom: 12px; }
.preview, .send-area > span { color: #9aa7b3; font-size: 11px; }
.send-area > .limit-hint, .send-area > .voice-status { color: #bf7a15; }
.voice-button { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid #d7e3ee; border-radius: 10px; background: #fff; color: #4b7ea6; cursor: pointer; }
.voice-button:hover:not(:disabled) { border-color: #9cc3e0; background: #f4faff; }
.voice-button:disabled { border-color: #e6ecf2; background: #f3f6f9; color: #b3c1cd; cursor: default; }
.voice-button.recording { border-color: #e2b1ab; background: #fdf1f0; color: #c0492f; }
.voice-cancel { border: none; padding: 0; background: transparent; color: #8798a8; font-size: 11px; cursor: pointer; }
.voice-cancel:hover { color: #52697d; }
.attach-button { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid #d7e3ee; border-radius: 10px; background: #fff; color: #4b7ea6; cursor: pointer; }
.attach-button:hover:not(:disabled) { border-color: #9cc3e0; background: #f4faff; }
.attach-button:disabled { border-color: #e6ecf2; background: #f3f6f9; color: #b3c1cd; cursor: default; }
.attachment-notice { margin-bottom: 12px; }
.attachment-tray { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.attachment-item { display: inline-flex; align-items: center; gap: 8px; padding: 6px 10px; border: 1px solid #dbe7f1; border-radius: 10px; background: #f7fbff; color: #4b6480; font-size: 11px; }
.attachment-item.pending { border-style: dashed; color: #bf7a15; }
.attachment-name { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attachment-thumb { width: 28px; height: 28px; border-radius: 6px; object-fit: cover; background: #eaf2f9; }
.attachment-meta { color: #90a0ae; }
.attachment-remove { border: none; padding: 0; background: transparent; color: #8798a8; font-size: 11px; cursor: pointer; }
.attachment-remove:hover { color: #c0492f; }
.composer.dragging { border-color: #8cb9de; background: #f7fbff; }
.user-attachments { display: flex; justify-content: flex-end; }
.send-button { display: grid; place-items: center; width: 34px; height: 34px; border: none; border-radius: 10px; background: #237ac2; color: white; cursor: pointer; }
.send-button:disabled { background: #e8eef4; color: #a2b3c3; cursor: default; }
.composer-meta { display: flex; justify-content: space-between; gap: 12px; margin-top: 12px; color: #9ba7b3; font-size: 10px; line-height: 1.7; }
.messages { max-width: 800px; margin: 0 auto; }
.retrieval-notice { margin: 12px 0 20px; }
.saved-heading { font-size: 13px; color: #718396; }
.saved-at { text-align: right; font-size: 11px; color: #8a99a8; }
.saved-at.assistant { text-align: left; margin-left: 38px; }
.message-pair { margin: 12px 0 40px; }
.user-message { max-width: 80%; width: fit-content; margin-left: auto; padding: 14px 20px; border-radius: 17px 17px 4px 17px; background: #edf4fb; color: #344e65; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
.assistant-message { display: flex; gap: 15px; margin-top: 28px; font-size: 14px; line-height: 1.9; color: #40566b; }
.assistant-message strong { color: #40566c; font-size: 13px; }
.answer-model { margin-left: 9px; padding: 2px 7px; border-radius: 999px; background: #eef5fb; color: #5f86a5; font-size: 10px; font-weight: 500; }
.assistant-avatar { width: 34px; height: 34px; flex: 0 0 34px; border: 1px solid #d9e8f3;
  border-radius: 50%; object-fit: cover; background: #edf7fd; }
.assistant-body { min-width: 0; flex: 1; }
.stop-button { display: grid; place-items: center; width: 34px; height: 34px; border: none; border-radius: 10px; background: #52697d; color: #fff; cursor: pointer; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
button:focus-visible { outline: 2px solid #398ad0; outline-offset: 3px; }
</style>
