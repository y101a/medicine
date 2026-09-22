<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { IMAGE_CONSENT_NOTICE } from '../composables/imagePrep'
import { formatAttachmentSize } from '../composables/useAttachments'

/**
 * 首次上传图片的一次性隐私确认（契约 `backend/docs/MEDICAL_IMAGES.md` 第 10 节）。
 *
 * 2026-09-22 起这里**不再选类别**：图片属于哪一类由服务端固定的视觉模型自动判断，前端只使用
 * 响应里的 `imageCategory` 展示能力边界。组件保留下来的是用户已经确认过的那三件事——
 * 敏感信息、90 天保留、阿里云外发；首次同意后本机记住，之后的图片直接上传，不再弹这个窗。
 */
const props = defineProps<{
  modelValue: boolean
  files: File[]
  uploading?: boolean
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

const canConfirm = computed(() => agreed.value && props.files.length > 0)

// 每次打开都重置勾选：用户取消后再次选图，仍要重新确认一次。
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
    class="image-upload"
    title="上传图片前请确认"
    width="min(560px, 92vw)"
    append-to-body
    :close-on-click-modal="false"
  >
    <p class="image-upload__lead">
      本次将上传 {{ files.length }} 张图片。图片属于哪一类——报告 / 检查单、X 光与 CT/MRI 片子、
      患处或身体照片——由服务端自动判断，你不需要选择；三类都不作疾病判断。
    </p>

    <ul class="image-upload__files">
      <li v-for="file in files" :key="file.name">
        <span class="image-upload__name">{{ file.name }}</span>
        <span class="image-upload__size">{{ formatAttachmentSize(file.size) }}</span>
      </li>
    </ul>

    <div class="image-upload__consent">
      <p class="image-upload__consent-text">{{ IMAGE_CONSENT_NOTICE }}</p>
      <el-checkbox v-model="agreed">我已阅读并同意上述说明</el-checkbox>
    </div>

    <template #footer>
      <el-button text @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!canConfirm" :loading="uploading" @click="onConfirm">
        同意并上传
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.image-upload__lead {
  margin: 0 0 10px;
  color: var(--text-main);
  line-height: 1.7;
}

.image-upload__files {
  margin: 0 0 14px;
  padding-left: 18px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.9;
}

.image-upload__name {
  margin-right: 8px;
}

.image-upload__size {
  color: #90a0ae;
}

.image-upload__consent {
  padding: 10px 12px;
  border: 1px solid #e6eef6;
  border-radius: 8px;
  background: #fbfdff;
}

.image-upload__consent-text {
  margin: 0 0 8px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.9;
}
</style>