<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  DOCUMENT_GENERATION_NOTICE_TEXT,
  DOCUMENT_GENERATION_RETENTION_DAYS,
} from '../types/documentGenerations'

/**
 * PPT/Word 文档生成的**一次性说明**（方案 §8.1、§8.2）。
 *
 * 没有主题/格式表单：主题与格式来自用户自己那条消息，服务端重新解析原文
 * （契约 §5.1：前端不得另传隐藏 prompt 或格式覆盖值）。这个弹窗只负责首次把
 * 「AI 生成、可能出错、仅作科普、可能产生模型费用、到期删除」讲清楚。
 *
 * 取消的语义在父组件：不发请求、不记版本、不伪造助手回答（方案 §8.2）。
 */
const props = defineProps<{
  modelValue: boolean
  submitting?: boolean
  /** 受控中文短句：限额、边界拒绝、资料不足等，都来自服务端受控错误码。 */
  error?: string
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'confirm'): void
}>()

const agreed = ref(false)

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const canConfirm = computed(() => agreed.value && !props.submitting)

// 每次打开都重置勾选：取消或失败后再次请求，仍要重新确认一次。
watch(
  () => props.modelValue,
  (opened) => {
    if (opened) agreed.value = false
  },
)

function onConfirm() {
  if (!canConfirm.value) return
  emit('confirm')
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
      <p class="document-generation-dialog__consent-text">
        {{ DOCUMENT_GENERATION_NOTICE_TEXT }}
      </p>
      <p class="document-generation-dialog__consent-text">
        文件由 AI 生成并带有「AI 生成的健康科普资料」标识，不能作为医院或医生签发的文书使用；
        请勿据此自行用药或停药。保留 {{ DOCUMENT_GENERATION_RETENTION_DAYS }} 天内你可以在任务卡上永久删除。
      </p>
      <el-checkbox v-model="agreed" :disabled="submitting">我已阅读并同意上述说明</el-checkbox>
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
.document-generation-dialog__error { margin-top: 10px; }
</style>