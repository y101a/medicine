<script setup lang="ts">
import { ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import PrivateKnowledgeSelector from './PrivateKnowledgeSelector.vue'
import type { PrivateKnowledgeCollection } from '../types/privateKnowledge'

/**
 * 输入框**左下角**的「+」入口，收纳两件低频的次要功能：添加附件、私人知识。
 *
 * 用户 2026-10-02 的三条指令依次落地：① 不要把功能按钮都堆进输入框（当时挤了 7 个控件）；
 * ② 选定「收进一个「+」菜单」；③ 随后要求「把语音对话模式从加号中分离，加号放在输入框底部
 * 左边，其余部分放在输入框右边」——于是语音对话模式改为独立入口（`SpeechModeControl.vue`），
 * 这里只剩附件与私人知识。
 *
 * 禁用不再是「点了没反应」：附件项在不可用时**在同一面板里写明原因**
 * （`attachmentsDisabledReason`），这是修掉的第二处缺陷。
 */
defineProps<{
  attachmentsDisabledReason: string
  attachmentCount: number
  attachmentLimit: number
  collections: PrivateKnowledgeCollection[]
  collectionsLoading: boolean
  collectionsError: string
  selectedCollectionIds: string[]
}>()
const emit = defineEmits<{
  'add-attachment': []
  'update:selectedCollectionIds': [value: string[]]
  'retry-collections': []
}>()

const visible = ref(false)

/** 点「选择文档或图片」后立刻收起菜单，把屏幕让给系统的文件选择器。 */
function addAttachment() {
  visible.value = false
  emit('add-attachment')
}
</script>

<template>
  <el-popover v-model:visible="visible" trigger="click" placement="top-start" :width="320"
    popper-class="composer-more-popper">
    <template #reference>
      <button
        type="button"
        class="composer-more-button"
        :class="{ active: selectedCollectionIds.length }"
        aria-label="更多功能：添加附件、私人知识"
        title="更多功能：添加附件、私人知识"
      ><el-icon :size="18"><Plus /></el-icon></button>
    </template>
    <div class="composer-more-menu" aria-label="更多功能">
      <section class="menu-section">
        <strong class="menu-title">添加附件</strong>
        <button
          type="button"
          class="menu-action add-attachment"
          :disabled="Boolean(attachmentsDisabledReason)"
          @click="addAttachment"
        >选择文档或图片</button>
        <small class="menu-note">
          已带 {{ attachmentCount }}/{{ attachmentLimit }} 份；可选 PDF / Word / PPT / txt / md 与图片（报告、片子、患处照片）。
        </small>
        <small v-if="attachmentsDisabledReason" class="menu-reason" role="status">{{ attachmentsDisabledReason }}</small>
      </section>

      <section class="menu-section">
        <PrivateKnowledgeSelector
          :model-value="selectedCollectionIds"
          :collections="collections"
          :loading="collectionsLoading"
          :error="collectionsError"
          @update:model-value="emit('update:selectedCollectionIds', $event)"
          @retry="emit('retry-collections')"
        />
      </section>
    </div>
  </el-popover>
</template>

<style scoped>
.composer-more-button { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid #d7e3ee;
  border-radius: 10px; background: #fff; color: #4b7ea6; cursor: pointer; }
.composer-more-button:hover { border-color: #9cc3e0; background: #f4faff; }
.composer-more-button:focus-visible { outline: 2px solid #4b91c4; outline-offset: 2px; }
.composer-more-button.active { border-color: #7fb3d8; background: #e8f3fd; color: #1f6396; }
.composer-more-menu { display: grid; gap: 10px; }
.menu-section { display: grid; gap: 6px; padding-bottom: 10px; border-bottom: 1px solid #eef3f8; }
.menu-section:last-child { padding-bottom: 0; border-bottom: 0; }
.menu-title { color: #315a79; font-size: 13px; }
.menu-note { color: #8a9aaa; font-size: 11px; line-height: 1.6; }
.menu-reason { color: #bf7a15; font-size: 11px; line-height: 1.5; }
.menu-action { justify-self: start; padding: 6px 12px; border: 1px solid #d7e3ee; border-radius: 9px;
  background: #fff; color: #3f7ba6; font-size: 12px; cursor: pointer; }
.menu-action:hover:not(:disabled) { border-color: #9cc3e0; background: #f4faff; }
.menu-action:disabled { border-color: #e6ecf2; background: #f3f6f9; color: #b3c1cd; cursor: default; }
.menu-action:focus-visible { outline: 2px solid #4b91c4; outline-offset: 2px; }
</style>

<style>
/* 面板由 Element Plus 传送到 body，作用域选择器够不到，所以这里用 popper-class。 */
.composer-more-popper { max-width: calc(100vw - 32px); }
</style>