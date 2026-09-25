<script setup lang="ts">
import { computed, ref, watch } from 'vue'

/**
 * AI 科普配图的**一次性协议**（方案 §7.1「收窄为首次使用自动弹出的费用、标识和用途协议」）。
 *
 * 2026-09-25 起不再有回答底部按钮：用户在对话里直接说「帮我生成一张关于人体结构的图片」，
 * 服务端消息响应给 `imageGenerationIntent=true`，前端跳过 `/stream` 直接生成。
 * 所以这个弹窗只负责**首次**把费用与标识讲清楚，确认后按协议版本记忆，之后明确请求直接生成。
 *
 * 没有提示词/风格/比例输入：主题来自用户自己那条消息，其余参数由服务端固定
 * （`watermark=false`、模型、分辨率、反向提示词前端都不可覆盖）。
 */
const props = defineProps<{
  modelValue: boolean
  submitting?: boolean
  /** 受控中文短句：限额、来源不合规、未配置等，都来自服务端受控错误码。 */
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

// 每次打开都重置勾选：取消或失败后再次生成，仍要重新确认一次。
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
    class="image-generation-dialog"
    title="生成 AI 科普配图前请确认"
    width="min(560px, 92vw)"
    append-to-body
    :close-on-click-modal="false"
  >
    <p class="image-generation-dialog__lead">
      你的这条消息会被识别为「生成科普配图」请求。图片只使用这条消息里的主题，
      不会读取你的病历、上传的图片、健康记录或完整对话。
    </p>

    <div class="image-generation-dialog__consent">
      <p class="image-generation-dialog__consent-text">
        图片由 AI 生成，仅作科普示意，可能存在结构或文字错误，<strong>不作为诊断、检查或治疗依据</strong>；
        每次生成可能产生费用。按你的选择，图片内不含水印标识，因此你转发或发布时需主动声明这是 AI 生成内容。
      </p>
      <el-checkbox v-model="agreed" :disabled="submitting">我已阅读并同意上述说明</el-checkbox>
    </div>

    <el-alert v-if="error" class="image-generation-dialog__error" type="warning" show-icon
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
.image-generation-dialog__lead { margin: 0 0 10px; color: var(--text-main); line-height: 1.7; }
.image-generation-dialog__consent { margin-top: 12px; padding: 10px 12px; border: 1px solid #e6eef6; border-radius: 8px; background: #fbfdff; }
.image-generation-dialog__consent-text { margin: 0 0 8px; color: var(--text-secondary); font-size: 12px; line-height: 1.9; }
.image-generation-dialog__error { margin-top: 10px; }
</style>