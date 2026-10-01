<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  PRIVATE_KNOWLEDGE_NOTICE_ITEMS,
  PRIVATE_KNOWLEDGE_NOTICE_TITLE,
} from '../types/privateKnowledgeUi'

/**
 * 「我的知识库」上传前的首次说明弹窗（方案 §8.1、§9；K2/K3/K5）。
 *
 * 与 PPT/Word 文档生成的弹窗同构，但只负责**一次**同意：说明版本记在本机
 * （`stores/composerHints.ts`），确认过之后不再弹，只在上传区留一句短提示。
 *
 * 弹窗本身**不发请求、不写版本号**——确认由父组件负责：上传成功或失败时是否记版本、
 * 取消时不记，都由页面的上传流程决定（方案 §8.2「取消不记版本」的同一条原则）。
 * 这里只讲清楚四件事：加密保存、不保存原件、脱敏的边界、删除即清理；外加一条最容易
 * 被误解的作用域——**它不会自动用于所有对话**。
 */
const props = defineProps<{
  modelValue: boolean
  /** 待上传的文件名，用于让用户确认选对了文件（只显示文件名，不显示路径或内容）。 */
  fileName?: string
  submitting?: boolean
  /** 受控中文短句：本地预检或服务端错误码映射后的文案。 */
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

const canConfirm = computed(() => !props.submitting && agreed.value)

// 每次打开都重置勾选：取消或失败后要重新走一遍同意。
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
    class="private-knowledge-notice-dialog"
    :title="PRIVATE_KNOWLEDGE_NOTICE_TITLE"
    width="560px"
    append-to-body
  >
    <p v-if="fileName" class="private-knowledge-notice-dialog__file">
      待上传：<strong>{{ fileName }}</strong>
    </p>
    <ul class="private-knowledge-notice-dialog__items">
      <li v-for="item in PRIVATE_KNOWLEDGE_NOTICE_ITEMS" :key="item">{{ item }}</li>
    </ul>
    <p class="private-knowledge-notice-dialog__boundary">
      这是你自己的资料，不会被当成经过医学审核的公共资料；查找结果只用于科普与就诊分流，
      不用于确诊、开药或调整用药，也不能替代医生。
    </p>
    <el-checkbox v-model="agreed" class="private-knowledge-notice-dialog__agree">
      我已阅读并同意以上说明
    </el-checkbox>
    <el-alert
      v-if="error"
      class="private-knowledge-notice-dialog__error"
      :title="error"
      type="error"
      :closable="false"
    />
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canConfirm" @click="onConfirm">
        同意并上传
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.private-knowledge-notice-dialog__file { margin: 0 0 10px; color: #4b6277; font-size: 13px; word-break: break-all; }
.private-knowledge-notice-dialog__items { margin: 0; padding-left: 18px; color: #4b6277; font-size: 13px; line-height: 1.9; }
.private-knowledge-notice-dialog__boundary { margin: 12px 0 0; color: #8a99a8; font-size: 12px; line-height: 1.8; }
.private-knowledge-notice-dialog__agree { margin-top: 12px; }
.private-knowledge-notice-dialog__error { margin-top: 10px; }
</style>

<style>
/* 弹窗挂在 body 上，窄屏（375px）要让正文自己滚动，保证按钮始终可达。类名限域。 */
.private-knowledge-notice-dialog .el-dialog__body { max-height: 58vh; overflow-y: auto; }
</style>