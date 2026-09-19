<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError, getApiErrorMessage } from '../../api/http'
import modelCredentialsApi from '../../api/modelCredentials'
import type { ModelCredentialSummary } from '../../types/modelCredentials'

/**
 * 可选服务商固定为注册表里的四家（后端 `registry.MODEL_DEFINITIONS`）；
 * 后端也拒绝其它值，并且 v1 不接受自定义 baseUrl（避免服务端变成任意外部请求入口）。
 */
const PROVIDERS = [
  { id: 'deepseek', name: 'DeepSeek' },
  { id: 'qwen', name: '阿里云百炼' },
  { id: 'kimi', name: 'Kimi' },
  { id: 'zhipuai', name: '智谱 AI' },
] as const

/** 与后端 `ModelCredentialWrite.api_key` 的 min_length 保持一致，本地先拦一道，省一次无效请求。 */
const MIN_KEY_LENGTH = 8

const credentials = ref<ModelCredentialSummary[]>([])
const loading = ref(false)
const loadError = ref('')
const editing = ref<string | null>(null)
const draftKey = ref('')
const saving = ref<string | null>(null)

const rows = computed(() =>
  PROVIDERS.map(provider => ({
    ...provider,
    credential: credentials.value.find(item => item.provider === provider.id),
  })),
)

function formatDateTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    credentials.value = await modelCredentialsApi.list()
  } catch (error) {
    loadError.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function startEdit(provider: string) {
  editing.value = provider
  draftKey.value = ''
}

function cancelEdit() {
  editing.value = null
  draftKey.value = ''
}

async function save(provider: string) {
  const apiKey = draftKey.value.trim()
  if (apiKey.length < MIN_KEY_LENGTH) {
    ElMessage.warning(`API Key 至少 ${MIN_KEY_LENGTH} 位，请确认是否粘贴完整`)
    return
  }

  saving.value = provider
  try {
    const saved = await modelCredentialsApi.save(provider, apiKey)
    const index = credentials.value.findIndex(item => item.provider === provider)
    if (index >= 0) credentials.value[index] = saved
    else credentials.value.push(saved)
    ElMessage.success('已保存，密钥验证通过')
    cancelEdit()
  } catch (error) {
    // 服务端已给出可读中文文案（无效 / 服务商故障 / 超时 / 过频），这里只对限流补一句可操作信息。
    if (error instanceof ApiError && error.code === 'MODEL_CREDENTIAL_RATE_LIMITED') {
      ElMessage.error(`${getApiErrorMessage(error)}（每个账号 10 分钟内最多验证 5 次）`)
    } else {
      ElMessage.error(getApiErrorMessage(error))
    }
  } finally {
    saving.value = null
  }
}

async function remove(provider: string, name: string) {
  try {
    await ElMessageBox.confirm(
      `删除后，「${name}」的模型会回落到本站默认密钥（如果本站已配置）。你填的 Key 会从服务器删除。`,
      '删除 API Key',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  try {
    await modelCredentialsApi.remove(provider)
    credentials.value = credentials.value.filter(item => item.provider !== provider)
    if (editing.value === provider) cancelEdit()
    ElMessage.success('已删除，该服务商不再使用你的 Key')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}
</script>

<template>
  <section class="credentials">
    <h2 class="credentials__title">模型与密钥</h2>
    <p class="credentials__intro">
      你可以填入自己的模型服务商 API Key。填了就用你的 Key、额度算在你的账号上；
      删掉就自动回到本站默认密钥。密钥只会以加密形式保存在服务器，界面永远只显示掩码。
    </p>

    <div class="credentials__notice" role="note">
      <strong>使用自带 Key 时，数据会发给对应服务商</strong>
      <p>
        选择使用你自带 Key 的模型后，本轮咨询内容与允许注入的健康记录摘要会发送到该服务商
        （DeepSeek、阿里云百炼、Kimi、智谱 AI）。发送前会自动移除显式姓名、手机号、身份证号、
        邮箱和详细地址，改用占位符；但这只是降低直接身份暴露，
        <strong>不等于健康文本已经匿名化</strong>，请自行判断是否愿意让该服务商处理这些内容。
      </p>
      <p>
        自带 Key 只改变认证凭据，不改变本站的安全规则：回答仍限于健康科普与就医分流，
        不作诊断、不替代医生，也不开处方；引用核验与红旗症状分流照旧生效。
      </p>
    </div>

    <p v-if="loadError" class="credentials__error">
      {{ loadError }}
      <el-button link type="primary" @click="load">重试</el-button>
    </p>
    <p v-else-if="loading" class="credentials__loading">正在读取已配置的密钥…</p>

    <ul class="credentials__list">
      <li v-for="row in rows" :key="row.id" class="credentials__item">
        <div class="credentials__meta">
          <strong>{{ row.name }}</strong>
          <template v-if="row.credential">
            <span class="credentials__state is-set">已配置 · {{ row.credential.maskedKey }}</span>
            <small>最近验证：{{ formatDateTime(row.credential.lastVerifiedAt) }}</small>
          </template>
          <span v-else class="credentials__state">未配置</span>
        </div>

        <div class="credentials__actions">
          <el-button v-if="!row.credential" size="small" @click="startEdit(row.id)">
            填入 API Key
          </el-button>
          <template v-else>
            <el-button size="small" @click="startEdit(row.id)">更换</el-button>
            <el-button size="small" type="danger" plain @click="remove(row.id, row.name)">
              删除
            </el-button>
          </template>
        </div>

        <div v-if="editing === row.id" class="credentials__editor">
          <el-input
            v-model="draftKey"
            type="password"
            show-password
            autocomplete="off"
            :placeholder="`粘贴 ${row.name} 的 API Key`"
            @keyup.enter="save(row.id)"
          />
          <el-button
            type="primary"
            size="small"
            :loading="saving === row.id"
            @click="save(row.id)"
          >
            验证并保存
          </el-button>
          <el-button size="small" @click="cancelEdit">取消</el-button>
        </div>
      </li>
    </ul>

    <p class="credentials__hint">
      保存前会用这个 Key 向服务商发一次最小请求（1 token）验证是否可用；验证不通过就不会保存。
      每个账号 10 分钟内最多验证 5 次。本站不支持自定义接口地址，只能选择上面四家官方端点。
    </p>
  </section>
</template>

<style scoped>
.credentials { display: flex; flex-direction: column; gap: 14px; }
.credentials__title { margin: 0; font-size: 18px; color: var(--text-main); }
.credentials__intro { margin: 0; max-width: 760px; color: var(--text-secondary); font-size: 13px; line-height: 1.8; }
.credentials__notice { max-width: 760px; padding: 12px 14px; border-left: 3px solid #e6a23c; background: #fdf6ec; }
.credentials__notice strong { display: block; margin-bottom: 6px; color: #8a6420; font-size: 13px; }
.credentials__notice p { margin: 0 0 6px; color: #6b5a35; font-size: 12px; line-height: 1.8; }
.credentials__notice p:last-child { margin-bottom: 0; }
.credentials__loading, .credentials__error { margin: 0; color: var(--text-secondary); font-size: 13px; }
.credentials__error { color: #c45656; }
.credentials__list { display: flex; flex-direction: column; gap: 10px; margin: 0; padding: 0; list-style: none; max-width: 760px; }
.credentials__item { display: grid; grid-template-columns: 1fr auto; gap: 6px 12px; align-items: center;
  padding: 12px 14px; border: 1px solid #e8edf3; border-radius: 8px; background: #fbfdff; }
.credentials__meta { display: flex; flex-direction: column; gap: 3px; }
.credentials__meta strong { font-size: 14px; color: var(--text-main); }
.credentials__state { color: #7c8b9b; font-size: 12px; }
.credentials__state.is-set { color: #196db2; }
.credentials__meta small { color: #96a4b3; font-size: 12px; }
.credentials__actions { display: flex; gap: 8px; }
.credentials__editor { grid-column: 1 / -1; display: flex; gap: 8px; align-items: center; padding-top: 4px; }
.credentials__editor :deep(.el-input) { max-width: 360px; }
.credentials__hint { margin: 0; max-width: 760px; color: #96a4b3; font-size: 12px; line-height: 1.8; }
</style>