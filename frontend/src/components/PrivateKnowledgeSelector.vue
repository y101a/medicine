<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Collection } from '@element-plus/icons-vue'
import type { PrivateKnowledgeCollection } from '../types/privateKnowledge'

/**
 * 咨询页的「私人知识」区块。
 *
 * **它本身不再是输入框里的一个按钮**（用户 2026-10-02 明令：不要把功能按钮都堆进输入框），
 * 而是由 `ComposerMoreMenu.vue` 的「+」菜单收纳，展开后才显示选择列表。
 *
 * 三种状态必须分得清，这是修掉的那处缺陷：加载中 / 加载失败（可重试、可去管理页）/
 * 真的没有知识库。此前只按 `collections` 是否为空渲染，请求失败时会显示成
 * 「还没有知识库」，把失败谎报成空（见 `COORDINATION.md` 7.2 的 2026-10-02 报告）。
 */
const props = defineProps<{
  modelValue: string[]
  collections: PrivateKnowledgeCollection[]
  loading?: boolean
  error?: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string[]]
  retry: []
}>()

/** 默认收起：菜单已经够长，只有用户要看库列表时才展开。 */
const open = ref(false)

/**
 * 管理入口用 `router.push` 而不是 `<RouterLink>`：这个区块渲染在 ElPopover 的传送内容里，
 * 而 `RouterLink` 依赖全局注册，测试环境里解析不到会直接让整页挂载失败（2026-10-02 实测）。
 */
const router = useRouter()

function goManage() {
  void router.push({ name: 'private-knowledge' })
}

const stateLabel = computed(() => (props.modelValue.length ? `已选 ${props.modelValue.length}` : '未选择'))

function toggle(id: string, checked: boolean) {
  if (checked) {
    if (props.modelValue.length >= 3 || props.modelValue.includes(id)) return
    emit('update:modelValue', [...props.modelValue, id])
  } else {
    emit('update:modelValue', props.modelValue.filter(item => item !== id))
  }
}
</script>

<template>
  <section class="private-knowledge-section">
    <button type="button" class="private-knowledge-toggle" :aria-expanded="open" @click="open = !open">
      <el-icon><Collection /></el-icon>
      <span class="section-name">私人知识</span>
      <b class="section-state">{{ stateLabel }}</b>
    </button>
    <div v-show="open" class="private-knowledge-panel">
      <p class="panel-hint">默认不使用。最多选择 3 个，只对本次发送的问题生效。</p>
      <span v-if="loading" class="panel-state">正在加载…</span>
      <p v-else-if="error" class="panel-error" role="status">
        <span>知识库列表加载失败：{{ error }}</span>
        <button type="button" class="retry-collections" @click="emit('retry')">重试</button>
        <button type="button" class="manage-link" @click="goManage">去「我的知识库」</button>
      </p>
      <p v-else-if="!collections.length" class="panel-state">
        <span>还没有知识库。</span>
        <button type="button" class="manage-link" @click="goManage">去「我的知识库」新建</button>
      </p>
      <template v-else>
        <label v-for="item in collections" :key="item.id" class="collection-option">
          <input
            type="checkbox"
            :checked="modelValue.includes(item.id)"
            :disabled="!modelValue.includes(item.id) && modelValue.length >= 3"
            @change="toggle(item.id, ($event.target as HTMLInputElement).checked)"
          />
          <span><b>{{ item.name }}</b><small>{{ item.documentCount }} 份文档</small></span>
        </label>
        <button v-if="modelValue.length" type="button" class="clear-selection" @click="emit('update:modelValue', [])">
          清空选择
        </button>
        <button type="button" class="manage-link" @click="goManage">管理我的知识库</button>
      </template>
    </div>
  </section>
</template>

<style scoped>
.private-knowledge-toggle { display: flex; align-items: center; gap: 7px; width: 100%; padding: 8px 2px;
  border: 0; background: transparent; color: #315a79; cursor: pointer; font-size: 13px; text-align: left; }
.private-knowledge-toggle:hover { color: #1f6396; }
.private-knowledge-toggle:focus-visible { outline: 2px solid #4b91c4; outline-offset: 2px; border-radius: 6px; }
.section-name { font-weight: 600; }
.section-state { margin-left: auto; color: #7c8f9f; font-size: 11px; font-weight: 500; }
.private-knowledge-panel { padding: 2px 2px 4px; }
.private-knowledge-panel > p { margin: 6px 0 10px; color: #8495a5; font-size: 11px; line-height: 1.6; }
.panel-state { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 6px 0; color: #8a9aaa; font-size: 12px; }
.panel-error { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; color: #bf7a15; font-size: 12px; }
.retry-collections { border: 1px solid #e2c79a; border-radius: 8px; padding: 3px 9px; background: #fffaf1;
  color: #a5701a; font-size: 11px; cursor: pointer; }
.retry-collections:hover { border-color: #d8b273; }
.manage-link { border: 0; padding: 0; background: transparent; color: #4d83aa; font-size: 11px; cursor: pointer;
  text-align: left; }
.manage-link:hover { color: #1f6396; }
.collection-option { display: flex; align-items: center; gap: 9px; padding: 7px 2px; color: #48647b; cursor: pointer; }
.collection-option span { display: grid; gap: 2px; min-width: 0; }
.collection-option b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 600; }
.collection-option small { color: #96a4b1; font-size: 10px; }
.clear-selection { margin-top: 6px; padding: 0; border: 0; background: transparent; color: #4d83aa; font-size: 11px; cursor: pointer; }
</style>