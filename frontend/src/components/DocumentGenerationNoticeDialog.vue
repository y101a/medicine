<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  DOCUMENT_GENERATION_NOTICE_TEXT,
  DOCUMENT_GENERATION_RETENTION_DAYS,
  DOCUMENT_GENERATION_SHORT_NOTICE_TEXT,
  DOCUMENT_TEMPLATE_ACCEPT,
  DOCUMENT_TEMPLATE_MAX_BYTES,
  DOCUMENT_TEMPLATE_NOTICE_TEXT,
} from '../types/documentGenerations'
import { formatAttachmentSize } from '../composables/useAttachments'

/**
 * PPT/Word 文档生成的确认弹窗（方案 §8.1、§8.2；PPT 模板见契约 §3.3）。
 *
 * 没有主题/格式表单：主题与格式来自用户自己那条消息，服务端重新解析原文
 * （契约 §5.1：前端不得另传隐藏 prompt 或格式覆盖值）。这个弹窗负责三件事：
 *
 * 1. **首次**（`alreadyAccepted=false`）：把「AI 生成、可能出错、仅作科普、可能产生费用、
 *    到期删除」逐项讲清，必须勾选才能生成；
 * 2. **之后**（`alreadyAccepted=true`，用户 2026-09-28 决定）：只给一句短提示、不再要求勾选——
 *    这样每次生成前仍确认一次费用，同时让下面的模板入口**随时可达**（否则老用户没有入口）；
 * 3. **可选模板**：两种形态下都在。用户主动选了 `.pptx` 才要求单独勾选模板说明
 *    （对应 multipart 里的 `templateNoticeAccepted`，契约 §3.3 第 3 条）。
 *
 * 取消的语义在父组件：不发请求、不记版本、不伪造助手回答（方案 §8.2）。
 */
const props = defineProps<{
  modelValue: boolean
  submitting?: boolean
  /** 受控中文短句：限额、边界拒绝、资料不足等，都来自服务端受控错误码。 */
  error?: string
  /** 这个浏览器已经确认过说明版本：只显示短提示，不再要求勾选。 */
  alreadyAccepted?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'confirm', payload: { templateFile: File | null }): void
}>()

const agreed = ref(false)
/** 模板说明的单独勾选：只有选了文件才需要（契约 §3.3）。 */
const templateAgreed = ref(false)
const templateFile = ref<File | null>(null)
/** 本地预检文案（扩展名、体积）；结构、页数这些只有服务端能判。 */
const templateError = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const requiresConsent = computed(() => !props.alreadyAccepted)
const canConfirm = computed(() => {
  if (props.submitting) return false
  if (requiresConsent.value && !agreed.value) return false
  // 本地拦下过模板（格式/体积）：先别让用户生成——否则会静默变成默认版式，
  // 而用户以为用的是自己的模板。要生成必须显式点「不用模板，直接生成」。
  if (templateError.value) return false
  if (templateFile.value && !templateAgreed.value) return false
  return true
})
const templateSizeText = computed(() => (
  templateFile.value ? formatAttachmentSize(templateFile.value.size) : ''
))

// 每次打开都重置：勾选、模板与本地错误都不跨次保留（取消或失败后要重新走一遍）。
watch(
  () => props.modelValue,
  (opened) => {
    if (!opened) return
    agreed.value = false
    templateAgreed.value = false
    templateFile.value = null
    templateError.value = ''
    if (fileInput.value) fileInput.value.value = ''
  },
)

function resetPickedFile() {
  templateFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

/**
 * 本地只拦扩展名与体积（`.pptx`、≤10 MiB，契约 §3.3）。
 * **不数页数**：那要解析 OOXML，前端不干这活，交给服务端回受控错误码。
 */
function onTemplatePicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  templateError.value = ''
  if (!file) {
    templateFile.value = null
    return
  }
  if (!file.name.toLowerCase().endsWith('.pptx')) {
    resetPickedFile()
    templateError.value = '只支持 .pptx 模板：请用 PowerPoint 或 WPS 另存为 .pptx 再选'
    return
  }
  if (file.size > DOCUMENT_TEMPLATE_MAX_BYTES) {
    resetPickedFile()
    templateError.value = `模板不能超过 ${formatAttachmentSize(DOCUMENT_TEMPLATE_MAX_BYTES)}，请压缩或换一个文件`
    return
  }
  templateFile.value = file
  templateAgreed.value = false
}

function clearTemplate() {
  resetPickedFile()
  templateAgreed.value = false
  templateError.value = ''
}

function onConfirm() {
  if (!canConfirm.value) return
  emit('confirm', { templateFile: templateFile.value })
}
</script>

<template>
  <el-dialog
    v-model="visible"
    class="document-generation-dialog"
    title="生成科普文档前请确认"
    width="min(560px, 92vw)"
    append-to-body
    :close-on-click-modal="false"
  >
    <p class="document-generation-dialog__lead">
      你的这条消息会被识别为「生成科普文档」请求。文档只使用这条消息里写明的主题和格式，
      不会读取你的健康记录、上传的病历、图片或此前的聊天记录。
    </p>

    <div class="document-generation-dialog__consent">
      <p v-if="requiresConsent" class="document-generation-dialog__consent-text">
        {{ DOCUMENT_GENERATION_NOTICE_TEXT }}
      </p>
      <p v-else class="document-generation-dialog__consent-text">
        {{ DOCUMENT_GENERATION_SHORT_NOTICE_TEXT }}
      </p>
      <p v-if="requiresConsent" class="document-generation-dialog__consent-text">
        文件由 AI 生成并带有「AI 生成的健康科普资料」标识，不能作为医院或医生签发的文书使用；
        请勿据此自行用药或停药。保留 {{ DOCUMENT_GENERATION_RETENTION_DAYS }} 天内你可以在任务卡上永久删除。
      </p>
      <el-checkbox v-if="requiresConsent" v-model="agreed" :disabled="submitting">
        我已阅读并同意上述说明
      </el-checkbox>
    </div>

    <div class="document-generation-dialog__template">
      <p class="document-generation-dialog__template-title">可选：用你自己的 PPT 模板</p>
      <p class="document-generation-dialog__template-text">
        在 PowerPoint 或 WPS 里做一个 .pptx（第一页封面、第二页正文，每页放标题和正文文字框），
        在这里选上它，生成的 PPT 就会沿用你的背景、图片与版式，内容仍由 AI 按科普结构填。
        不超过 10 MiB、2–20 页；<strong>只在你这句消息要求 PPT 时生效</strong>——同时要 Word 时，Word 仍用默认版式。
      </p>
      <p class="document-generation-dialog__template-text">{{ DOCUMENT_TEMPLATE_NOTICE_TEXT }}</p>
      <input
        ref="fileInput"
        class="document-generation-dialog__file-input"
        type="file"
        :accept="DOCUMENT_TEMPLATE_ACCEPT"
        @change="onTemplatePicked"
      >
      <div class="document-generation-dialog__template-actions">
        <el-button size="small" plain :disabled="submitting" @click="fileInput?.click()">
          {{ templateFile ? '换一个模板' : '选择 .pptx 模板' }}
        </el-button>
        <span v-if="templateFile" class="document-generation-dialog__template-file">
          {{ templateFile.name }}（{{ templateSizeText }}）
        </span>
        <el-button v-if="templateFile || templateError" size="small" text :disabled="submitting" @click="clearTemplate">
          {{ templateFile ? '不用模板' : '不用模板，直接生成' }}
        </el-button>
      </div>
      <el-checkbox v-if="templateFile" v-model="templateAgreed" :disabled="submitting">
        我已了解模板原件的保存与使用范围
      </el-checkbox>
      <p v-if="templateError" class="document-generation-dialog__template-error">{{ templateError }}</p>
    </div>

    <el-alert v-if="error" class="document-generation-dialog__error" type="warning" show-icon
      :closable="false" :title="error" />

    <template #footer>
      <el-button text :disabled="submitting" @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!canConfirm" :loading="submitting" @click="onConfirm">
        同意并生成
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.document-generation-dialog__lead { margin: 0 0 10px; color: var(--text-main); line-height: 1.7; }
.document-generation-dialog__consent { margin-top: 12px; padding: 10px 12px; border: 1px solid #e6eef6; border-radius: 8px; background: #fbfdff; }
.document-generation-dialog__consent-text { margin: 0 0 8px; color: var(--text-secondary); font-size: 12px; line-height: 1.9; }
.document-generation-dialog__template { margin-top: 12px; padding: 10px 12px; border: 1px dashed #d9e6f2; border-radius: 8px; background: #fff; }
.document-generation-dialog__template-title { margin: 0 0 6px; color: var(--text-main); font-size: 13px; font-weight: 600; }
.document-generation-dialog__template-text { margin: 0 0 6px; color: var(--text-secondary); font-size: 12px; line-height: 1.8; }
.document-generation-dialog__file-input { display: none; }
.document-generation-dialog__template-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.document-generation-dialog__template-file { color: #2f5876; font-size: 12px; word-break: break-all; }
.document-generation-dialog__template-error { margin: 6px 0 0; color: #b26a00; font-size: 12px; }
.document-generation-dialog__error { margin-top: 10px; }
</style>

<style>
/*
 * 弹窗挂在 body 上（`append-to-body`），加上模板区之后内容比窄屏（375px×720px）更高。
 * 让正文区自己滚动，保证「同意并生成」按钮始终可达。用类名前缀限域，不影响别的弹窗。
 */
.document-generation-dialog .el-dialog__body { max-height: 58vh; overflow-y: auto; }
</style>