<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  IMAGE_GENERATION_ASPECT_RATIO_LABELS,
  IMAGE_GENERATION_PROMPT_MAX_LENGTH,
  IMAGE_GENERATION_STYLE_LABELS,
  type ImageGenerationAspectRatio,
  type ImageGenerationStyle,
} from '../types/imageGenerations'

/**
 * 生成前的确认弹窗（方案 §7.1/§7.2）。
 *
 * 三条硬要求都落在这里：
 * 1. **不自动生成、不默认收费**：用户必须自己写/改一段描述、勾选说明，再点确认。
 * 2. 模型、数量、分辨率、水印、反向提示词**都不在弹窗里**——那些由服务端固定，前端不给开关。
 * 3. 说明里必须写明「AI 生成 / 只作科普示意 / 可能出错 / 不作诊断依据 / 可能产生费用」，
 *    并按用户 2026-09-24 选定的水印策略（《标识办法》第九条：图内无标识）写明**用户转发时的声明义务**。
 */
const props = defineProps<{
  modelValue: boolean
  submitting?: boolean
  /** 提交失败时由父组件塞进来的受控中文短句。 */
  error?: string
  initialPrompt?: string
  initialStyle?: ImageGenerationStyle
  initialAspectRatio?: ImageGenerationAspectRatio
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'submit', draft: {
    prompt: string
    style: ImageGenerationStyle
    aspectRatio: ImageGenerationAspectRatio
  }): void
}>()

const STYLE_ORDER: ImageGenerationStyle[] = [
  'medical_illustration',
  'flat_illustration',
  'friendly_cartoon',
]
const RATIO_ORDER: ImageGenerationAspectRatio[] = ['1:1', '4:3', '3:4', '16:9']

const prompt = ref('')
const style = ref<ImageGenerationStyle>('medical_illustration')
const aspectRatio = ref<ImageGenerationAspectRatio>('4:3')
const agreed = ref(false)

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const trimmedPrompt = computed(() => prompt.value.trim())
const remaining = computed(() => IMAGE_GENERATION_PROMPT_MAX_LENGTH - trimmedPrompt.value.length)
const canSubmit = computed(
  () => agreed.value && trimmedPrompt.value.length > 0 && remaining.value >= 0 && !props.submitting,
)

// 每次打开都重置：勾选状态与提示词都回到调用方给的初始值，避免沿用上一次的确认。
watch(
  () => props.modelValue,
  (opened) => {
    if (!opened) return
    prompt.value = props.initialPrompt || ''
    style.value = props.initialStyle || 'medical_illustration'
    aspectRatio.value = props.initialAspectRatio || '4:3'
    agreed.value = false
  },
)

function onSubmit() {
  if (!canSubmit.value) return
  emit('submit', {
    prompt: trimmedPrompt.value,
    style: style.value,
    aspectRatio: aspectRatio.value,
  })
}
</script>

<template>
  <el-dialog
    v-model="visible"
    class="image-generation-dialog"
    title="生成医学科普配图"
    width="min(560px, 92vw)"
    append-to-body
    :close-on-click-modal="false"
  >
    <p class="image-generation-dialog__lead">
      描述你想科普的内容（例如「呼吸道与肺部关系的示意」）。只发送这段描述，
      不会读取你的病历、上传的图片或完整对话。
    </p>

    <el-input
      v-model="prompt"
      class="image-generation-dialog__prompt"
      type="textarea"
      :rows="3"
      :maxlength="IMAGE_GENERATION_PROMPT_MAX_LENGTH"
      show-word-limit
      placeholder="例：一张展示呼吸道与肺部关系的友好医学科普插画"
    />

    <div class="image-generation-dialog__row">
      <span class="image-generation-dialog__label">风格</span>
      <el-radio-group v-model="style" :disabled="submitting">
        <el-radio-button v-for="item in STYLE_ORDER" :key="item" :value="item">
          {{ IMAGE_GENERATION_STYLE_LABELS[item] }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <div class="image-generation-dialog__row">
      <span class="image-generation-dialog__label">比例</span>
      <el-radio-group v-model="aspectRatio" :disabled="submitting">
        <el-radio-button v-for="item in RATIO_ORDER" :key="item" :value="item">
          {{ IMAGE_GENERATION_ASPECT_RATIO_LABELS[item] }}
        </el-radio-button>
      </el-radio-group>
    </div>

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
      <el-button type="primary" :disabled="!canSubmit" :loading="submitting" @click="onSubmit">
        确认生成
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.image-generation-dialog__lead { margin: 0 0 10px; color: var(--text-main); line-height: 1.7; }
.image-generation-dialog__prompt { margin-bottom: 12px; }
.image-generation-dialog__row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.image-generation-dialog__label { flex: none; width: 32px; color: var(--text-secondary); font-size: 13px; }
.image-generation-dialog__consent { margin-top: 12px; padding: 10px 12px; border: 1px solid #e6eef6; border-radius: 8px; background: #fbfdff; }
.image-generation-dialog__consent-text { margin: 0 0 8px; color: var(--text-secondary); font-size: 12px; line-height: 1.9; }
.image-generation-dialog__error { margin-top: 10px; }
</style>