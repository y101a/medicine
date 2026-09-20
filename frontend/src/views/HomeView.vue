<script setup lang="ts">
import { computed, nextTick, ref, onMounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { consultationsApi, type RetrievalProgress } from '../api/consultations'
import { modelsApi } from '../api/models'
import { useConsultationsStore } from '../stores/consultations'
import { useAuthStore } from '../stores/auth'
import { useHealthRecordsStore } from '../stores/healthRecords'
import { ApiError, getApiErrorMessage } from '../api/http'
import type { AiModel, AnswerFormat, FollowUpAnswers, FollowUpCard, Message } from '../types/consultations'
import { Top, ChatDotRound, Compass, Document, CloseBold } from '@element-plus/icons-vue'
import medicalAiAvatar from '../assets/medical-ai-avatar.png'
import AssistantAnswerCard from '../components/AssistantAnswerCard.vue'
import StructuredFollowUpCard from '../components/StructuredFollowUpCard.vue'
import EmergencyTriageCard from '../components/EmergencyTriageCard.vue'
import ReferenceSources from '../components/ReferenceSources.vue'
import HospitalNavigator from '../components/HospitalNavigator.vue'
import PathologyCardOffer from '../components/PathologyCardOffer.vue'
import { readRetrievalNotice, rememberRetrievalNotice } from '../stores/retrievalNotices'
import { readVoiceTipSeen, rememberVoiceTipSeen } from '../stores/composerHints'

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
const nearDraftLimit = computed(() => draft.value.length >= DRAFT_NEAR_LIMIT)
function dismissVoiceTip() {
  voiceTipSeen.value = true
  rememberVoiceTipSeen()
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
  if (!content || content.length > 2000 || saving.value || generating.value || loading.value || !ready.value) return
  if (!pending || pending.content !== content) pending = { content, id: crypto.randomUUID() }
  const userId = auth.user?.id
  saving.value = true
  error.value = ''
  try {
    if (!cid) cid = (await consultationsApi.create(createRequestId)).id
    const message = await consultationsApi.send(cid, pending.content, pending.id)
    if (auth.user?.id !== userId) return
    if (!messages.value.some(item => item.id === message.id)) messages.value.push(message)
    if (clearDraft) draft.value = ''
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
  await sendContent(draft.value.trim(), true)
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
            <EmergencyTriageCard v-if="message.triage" :triage="message.triage" />
          </template>
          <div v-else class="assistant-message">
            <img class="assistant-avatar" :src="medicalAiAvatar" alt="医疗 AI 助手" />
            <div class="assistant-body">
              <strong>科普助手<span v-if="modelName(message)" class="answer-model">{{ modelName(message) }}</span></strong>
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
      <form class="composer" @submit.prevent="send">
        <el-alert v-if="modelsError" class="model-error" :title="modelsError" type="warning" :closable="false" />
        <el-alert v-if="!voiceTipSeen" class="voice-tip" type="info" show-icon
          title="可用输入法上的麦克风语音输入（如豆包输入法）。语音识别可能出错，发送前请核对文字；请不要在对话中提供姓名、身份证号、住院号或手机号。"
          @close="dismissVoiceTip" />
        <label class="sr-only" for="symptom-input">症状或健康问题</label>
        <textarea id="symptom-input" ref="input" v-model="draft" :maxlength="DRAFT_LIMIT" rows="3" :disabled="saving || generating || !ready"
          placeholder="描述您的症状或健康疑问，例如：什么时候开始、持续多久……" @keydown="keydown"></textarea>
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
            <button v-if="generating" class="stop-button" type="button" aria-label="停止生成" title="停止生成" @click="stopGeneration"><el-icon :size="15"><CloseBold /></el-icon></button>
            <button v-else class="send-button" type="submit" :disabled="!draft.trim() || saving || loading || modelsLoading || !ready" aria-label="发送消息" title="发送消息"><el-icon :size="20"><Top /></el-icon></button>
          </div>
        </div>
      </form>
      <div class="composer-meta"><span>仅提供健康科普与就医分流，不作确诊，不替代医生。</span><span>可用输入法语音输入（如豆包输入法） · Enter 发送 · Shift + Enter 换行</span></div>
    </div>
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
.model-error, .voice-tip { margin-bottom: 12px; }
.preview, .send-area > span { color: #9aa7b3; font-size: 11px; }
.send-area > .limit-hint { color: #bf7a15; }
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
