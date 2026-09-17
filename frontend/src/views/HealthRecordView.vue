<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getApiErrorMessage } from '../api/http'
import HealthRecordCharts from '../components/HealthRecordCharts.vue'
import { useHealthRecordsStore } from '../stores/healthRecords'
import type {
  HealthRecord,
  HealthRecordCategory,
  HealthRecordSource,
} from '../types/healthRecords'

const store = useHealthRecordsStore()
const draftCategory = ref<HealthRecordCategory>('symptom')
const draftContent = ref('')
const editingId = ref('')
const editingContent = ref('')

const categoryOptions: { value: HealthRecordCategory; label: string }[] = [
  { value: 'general_status', label: '近期身体状态' },
  { value: 'symptom', label: '近期症状' },
  { value: 'condition', label: '长期健康情况（我自述的）' },
  { value: 'medication', label: '正在使用的药物' },
  { value: 'allergy', label: '过敏史' },
  { value: 'lifestyle', label: '生活方式' },
  { value: 'measurement', label: '自测指标' },
  { value: 'care_seeking', label: '就医情况' },
  { value: 'other', label: '其他' },
]

const sourceLabels: Record<HealthRecordSource, string> = {
  onboarding: '首次采集',
  conversation: '对话自动记录',
  user: '你手动添加或修改',
}

const grouped = computed(() => {
  const order = categoryOptions.map((item) => item.value)
  const buckets = new Map<
    HealthRecordCategory,
    { category: HealthRecordCategory; label: string; items: HealthRecord[] }
  >()
  for (const record of store.records) {
    const bucket = buckets.get(record.category)
    if (bucket) {
      bucket.items.push(record)
    } else {
      buckets.set(record.category, {
        category: record.category,
        label: record.categoryLabel,
        items: [record],
      })
    }
  }
  return [...buckets.values()].sort(
    (left, right) => order.indexOf(left.category) - order.indexOf(right.category),
  )
})

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function guard(action: () => Promise<unknown>, success: string) {
  try {
    await action()
    if (success) ElMessage.success(success)
  } catch (caught) {
    ElMessage.error(getApiErrorMessage(caught))
  }
}

function onAdd() {
  const content = draftContent.value.trim()
  if (!content) return
  void guard(async () => {
    await store.addRecord(draftCategory.value, content)
    draftContent.value = ''
  }, '已添加')
}

function startEdit(record: HealthRecord) {
  editingId.value = record.id
  editingContent.value = record.content
}

function cancelEdit() {
  editingId.value = ''
  editingContent.value = ''
}

function onSaveEdit(id: string) {
  const content = editingContent.value.trim()
  if (!content) return
  void guard(async () => {
    await store.editRecord(id, content)
    cancelEdit()
  }, '已保存')
}

function onRemove(id: string) {
  void guard(async () => {
    await store.removeRecord(id)
  }, '已删除')
}

function onToggleCollection(value: string | number | boolean) {
  void guard(async () => {
    await store.setCollection(Boolean(value))
  }, '')
}

onMounted(() => {
  void store.loadSettings().catch(() => undefined)
  void store.loadRecords()
})
</script>

<template>
  <section class="health-records">
    <header class="health-records__header">
      <div>
        <h1 class="health-records__title">健康记录</h1>
        <p class="health-records__intro">
          这里只保存你在对话中<strong>自己说过</strong>的健康信息，用于减少重复询问、让科普更贴合你的情况。
          记录只是背景资料，不是诊断结论，也不能替代医生面诊。
        </p>
      </div>
      <el-switch
        class="health-records__switch"
        :model-value="store.collectionEnabled"
        :loading="store.saving"
        active-text="对话自动记录"
        @update:model-value="onToggleCollection"
      />
    </header>

    <el-alert
      v-if="!store.collectionEnabled"
      class="health-records__notice"
      type="info"
      show-icon
      :closable="false"
      title="对话自动记录已关闭"
      description="关闭后不会再从新对话里提取记录，也不再用于个性化回答；已有记录仍会保留，你可以逐条修改或删除。"
    />

    <el-card class="health-records__panel" shadow="never">
      <template #header>手动添加一条</template>
      <div class="health-records__form">
        <el-select v-model="draftCategory" class="health-records__select">
          <el-option
            v-for="option in categoryOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-input
          v-model="draftContent"
          class="health-records__input"
          maxlength="500"
          placeholder="例如：最近一周夜间失眠"
        />
        <el-button
          type="primary"
          :disabled="!draftContent.trim()"
          :loading="store.saving"
          @click="onAdd"
        >
          添加
        </el-button>
      </div>
    </el-card>

    <el-alert
      v-if="store.error"
      class="health-records__notice"
      type="error"
      show-icon
      :closable="false"
      :title="store.error"
    />

    <HealthRecordCharts :records="store.records" />

    <el-empty
      v-if="!store.loading && store.records.length === 0"
      description="还没有健康记录。你在对话里说过的健康信息会自动出现在这里。"
    />

    <el-card
      v-for="group in grouped"
      :key="group.category"
      class="health-records__panel"
      shadow="never"
    >
      <template #header>
        <span>{{ group.label }}</span>
        <span class="health-records__count">{{ group.items.length }} 条</span>
      </template>
      <ul class="health-records__list">
        <li v-for="record in group.items" :key="record.id" class="health-records__item">
          <template v-if="editingId === record.id">
            <el-input v-model="editingContent" class="health-records__input" maxlength="500" />
            <el-button type="primary" text :loading="store.saving" @click="onSaveEdit(record.id)">
              保存
            </el-button>
            <el-button text @click="cancelEdit">取消</el-button>
          </template>
          <template v-else>
            <div class="health-records__content">
              <p class="health-records__text">{{ record.content }}</p>
              <p class="health-records__meta">
                {{ sourceLabels[record.source] }} · {{ formatTime(record.recordedAt) }}
              </p>
            </div>
            <el-button text @click="startEdit(record)">修改</el-button>
            <el-popconfirm
              title="删除后无法恢复，确定删除这条记录吗？"
              confirm-button-text="删除"
              cancel-button-text="取消"
              @confirm="onRemove(record.id)"
            >
              <template #reference>
                <el-button text type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </li>
      </ul>
    </el-card>
  </section>
</template>

<style scoped>
.health-records {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.health-records__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.health-records__title {
  margin: 0 0 6px;
  font-size: 20px;
  color: var(--text-main);
}

.health-records__intro {
  margin: 0;
  max-width: 620px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.8;
}

.health-records__switch {
  flex: none;
}

.health-records__notice {
  margin: 0;
}

.health-records__panel {
  border: 1px solid var(--border);
  border-radius: 10px;
}

.health-records__form {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.health-records__select {
  width: 200px;
}

.health-records__input {
  flex: 1;
  min-width: 240px;
}

.health-records__count {
  margin-left: 8px;
  color: var(--text-secondary);
  font-size: 12px;
}

.health-records__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.health-records__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.health-records__item:last-child {
  border-bottom: none;
}

.health-records__content {
  flex: 1;
  min-width: 0;
}

.health-records__text {
  margin: 0;
  color: var(--text-main);
  word-break: break-word;
}

.health-records__meta {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}
</style>