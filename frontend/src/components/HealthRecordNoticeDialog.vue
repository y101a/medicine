<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getApiErrorMessage } from '../api/http'
import { useHealthRecordsStore } from '../stores/healthRecords'
import type { OnboardingStatus } from '../types/healthRecords'

const store = useHealthRecordsStore()
const status = ref<OnboardingStatus>('fair')
const note = ref('')
const localError = ref('')

const statusOptions: { value: OnboardingStatus; label: string }[] = [
  { value: 'good', label: '还不错' },
  { value: 'fair', label: '一般' },
  { value: 'poor', label: '不太好' },
  { value: 'unsure', label: '说不清' },
]

const visible = computed({
  get: () => store.noticeVisible,
  set: (value: boolean) => {
    if (!value) store.closeNotice()
  },
})

async function onSubmit() {
  localError.value = ''
  try {
    await store.submitOnboarding(status.value, note.value.trim() || undefined)
    ElMessage.success('已记录，可随时在“健康记录”里修改或删除')
  } catch (caught) {
    localError.value = getApiErrorMessage(caught)
  }
}

async function onSkip() {
  localError.value = ''
  try {
    await store.skipNotice()
  } catch (caught) {
    localError.value = getApiErrorMessage(caught)
  }
}

async function onDisable() {
  localError.value = ''
  try {
    await store.disableCollection()
    ElMessage.info('已关闭自动记录，可随时在“健康记录”里重新开启')
  } catch (caught) {
    localError.value = getApiErrorMessage(caught)
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    class="health-notice"
    title="关于健康记录"
    width="560px"
    append-to-body
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
  >
    <p class="health-notice__lead">
      为了在后续对话中少重复询问、让科普更贴合你的情况，产品会记录你在对话里
      <strong>自己说过的</strong>健康信息。
    </p>

    <ul class="health-notice__rules">
      <li>只记录你明确说过的内容，不写入任何推测或诊断结论；</li>
      <li>内容加密保存，你可以在“健康记录”里查看、修改、删除；</li>
      <li>自动记录默认开启；关闭后立即停止，已有记录仍可自行删除；</li>
      <li>健康记录不参与紧急症状判断，出现胸痛、呼吸困难等情况仍会优先提示就医。</li>
    </ul>

    <p class="health-notice__question">顺便选一下你最近的身体状态（也可以跳过）：</p>
    <el-radio-group v-model="status" class="health-notice__status">
      <el-radio-button
        v-for="option in statusOptions"
        :key="option.value"
        :value="option.value"
      >
        {{ option.label }}
      </el-radio-button>
    </el-radio-group>
    <el-input
      v-model="note"
      class="health-notice__note"
      maxlength="200"
      show-word-limit
      placeholder="可补充一句，例如“最近睡得少”（选填）"
    />

    <p v-if="localError" class="health-notice__error">{{ localError }}</p>

    <template #footer>
      <div class="health-notice__actions">
        <el-button text class="health-notice__skip" @click="onSkip">跳过</el-button>
        <el-button text class="health-notice__disable" @click="onDisable">关闭采集</el-button>
        <el-button
          type="primary"
          class="health-notice__submit"
          :loading="store.saving"
          @click="onSubmit"
        >
          保存
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.health-notice__lead {
  margin: 0 0 12px;
  color: var(--text-main);
  line-height: 1.7;
}

.health-notice__rules {
  margin: 0 0 18px;
  padding-left: 18px;
  color: var(--text-secondary);
  line-height: 1.9;
  font-size: 13px;
}

.health-notice__question {
  margin: 0 0 10px;
  color: var(--text-main);
}

.health-notice__status {
  margin-bottom: 12px;
}

.health-notice__note {
  margin-bottom: 4px;
}

.health-notice__error {
  margin: 10px 0 0;
  color: var(--medical-red);
  font-size: 13px;
}

.health-notice__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}
</style>