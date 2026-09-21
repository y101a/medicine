<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  IMAGE_CATEGORY_LABELS,
  IMAGE_CATEGORY_NOTICES,
  IMAGE_CONSENT_NOTICE,
  type ImageCategory,
} from '../composables/imagePrep'
import { formatAttachmentSize } from '../composables/useAttachments'

/**
 * 图片上传前的确认：选类别 + 首次的敏感信息与外发说明。
 *
 * 这里是产品边界的落点——三类图片都不做疾病判断，所以每选一类就把该类的能力边界与
 * 「该看什么」讲清楚；用户不勾选同意就不能上传（服务端也会校验 `noticeAccepted`）。
 */
const props = defineProps<{
  modelValue: boolean
  files: File[]
  /** 本机是否已经同意过这份说明；同意过就不再重复勾选。 */
  consentSeen: boolean
  uploading?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'confirm', category: ImageCategory): void
}>()

const CATEGORY_OPTIONS: { value: ImageCategory; label: string }[] = [
  { value: 'report', label: IMAGE_CATEGORY_LABELS.report },
  { value: 'medical_imaging', label: IMAGE_CATEGORY_LABELS.medical_imaging },
  { value: 'body_photo', label: IMAGE_CATEGORY_LABELS.body_photo },
]

const category = ref<ImageCategory | ''>('')
const agreed = ref(false)

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const notice = computed(() => (category.value ? IMAGE_CATEGORY_NOTICES[category.value] : ''))
const canConfirm = computed(
  () => Boolean(category.value) && agreed.value && props.files.length > 0,
)

// 每次打开都重置选择；已经同意过的用户不必再勾一次，但仍要看到边界文案。
watch(
  () => props.modelValue,
  (opened) => {
    if (!opened) return
    category.value = ''
    agreed.value = props.consentSeen
  },
)

function onConfirm() {
  if (!canConfirm.value || !category.value) return
  emit('confirm', category.value)
}
</script>

<template>
  <el-dialog
    v-model="visible"
    class="image-upload"
    title="上传图片"
    width="min(560px, 92vw)"
    append-to-body
    :close-on-click-modal="false"
  >
    <p class="image-upload__lead">
      先确认这些图片属于哪一类——会做什么、不会做什么随之不同。本次选入的
      {{ files.length }} 张图片按同一类处理，暂不上传原图。
    </p>

    <ul class="image-upload__files">
      <li v-for="file in files" :key="file.name">
        <span class="image-upload__name">{{ file.name }}</span>
        <span class="image-upload__size">{{ formatAttachmentSize(file.size) }}</span>
      </li>
    </ul>

    <el-radio-group v-model="category" class="image-upload__category">
      <el-radio-button v-for="option in CATEGORY_OPTIONS" :key="option.value" :value="option.value">
        {{ option.label }}
      </el-radio-button>
    </el-radio-group>

    <p v-if="notice" class="image-upload__notice">{{ notice }}</p>

    <div v-if="!consentSeen" class="image-upload__consent">
      <p class="image-upload__consent-text">{{ IMAGE_CONSENT_NOTICE }}</p>
      <el-checkbox v-model="agreed">我已阅读并同意上述说明</el-checkbox>
    </div>
    <p v-else class="image-upload__consent-hint">
      提醒：画面上的姓名、住院号、条码无法自动去除，建议先遮挡再上传。
    </p>

    <template #footer>
      <el-button text @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!canConfirm" :loading="uploading" @click="onConfirm">
        上传并识别
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

.image-upload__category {
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.image-upload__notice {
  margin: 0 0 12px;
  padding: 9px 12px;
  border-radius: 8px;
  background: #f6faff;
  color: #4b7ea6;
  font-size: 12px;
  line-height: 1.8;
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

.image-upload__consent-hint {
  margin: 0;
  color: #8798a8;
  font-size: 12px;
  line-height: 1.8;
}
</style>