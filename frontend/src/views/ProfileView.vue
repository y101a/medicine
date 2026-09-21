<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { User } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { getApiErrorMessage } from '../api/http'
import type { Gender, UpdateProfileRequest } from '../types/auth'

const store = useAuthStore()
const router = useRouter()
const formRef = ref<FormInstance>()
const saving = ref(false)
const deleting = ref(false)
const uploadingAvatar = ref(false)
const avatarFailed = ref(false)
const avatarInput = ref<HTMLInputElement>()
const errorMessage = ref('')
const form = reactive<{ realName: string; gender: Gender }>({ realName: '', gender: 'private' })
const dirty = computed(() => !!store.user && (
  form.realName.trim() !== store.user.realName || form.gender !== store.user.gender
))
const registeredAt = computed(() => {
  const date = new Date(store.user?.registeredAt || '')
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
})

function resetForm() {
  if (!store.user) return
  form.realName = store.user.realName
  form.gender = store.user.gender
  errorMessage.value = ''
  formRef.value?.clearValidate()
}
watch(() => store.user, resetForm, { immediate: true })
watch(() => store.avatarUrl, () => { avatarFailed.value = false })

function chooseAvatar() {
  if (!uploadingAvatar.value) avatarInput.value?.click()
}

async function changeAvatar(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    errorMessage.value = '头像仅支持 JPG、PNG 或 WebP 格式'
    return
  }
  if (file.size > 3 * 1024 * 1024) {
    errorMessage.value = '头像文件不能超过 3 MB'
    return
  }
  uploadingAvatar.value = true
  errorMessage.value = ''
  try {
    await store.uploadAvatar(file)
    avatarFailed.value = false
    ElMessage.success('头像已更新')
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    uploadingAvatar.value = false
  }
}

const rules: FormRules = {
  realName: [{
    validator: (_rule, value: string, callback) => {
      const name = value.trim()
      if (name.length < 2 || name.length > 20) return callback(new Error('姓名长度应为 2–20 个字符'))
      if (!/^[A-Za-z\u4E00-\u9FFF·]+$/.test(name)) {
        return callback(new Error('姓名仅支持中文、英文字母和间隔符 ·'))
      }
      callback()
    },
    trigger: 'blur',
  }],
  gender: [{ required: true, message: '请选择性别', trigger: 'change' }],
}

async function save() {
  if (saving.value || !dirty.value || !store.user) return
  const name = form.realName.trim()
  if (name.length < 2 || name.length > 20) {
    errorMessage.value = '姓名长度应为 2–20 个字符'
    return
  }
  if (!/^[A-Za-z\u4E00-\u9FFF·]+$/.test(name)) {
    errorMessage.value = '姓名仅支持中文、英文字母和间隔符 ·'
    return
  }
  if (!await formRef.value?.validate().catch(() => false)) return
  const payload: UpdateProfileRequest = {}
  if (form.realName.trim() !== store.user.realName) payload.realName = form.realName.trim()
  if (form.gender !== store.user.gender) payload.gender = form.gender
  saving.value = true
  errorMessage.value = ''
  try {
    await store.updateProfile(payload)
    ElMessage.success('个人资料已保存')
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    saving.value = false
  }
}

/**
 * 删除账号不可逆：先把后果讲清楚，再要求输入当前密码（后端 422 ACCOUNT_PASSWORD_INVALID 兜底）。
 */
async function removeAccount() {
  if (deleting.value) return
  let currentPassword = ''
  try {
    const result = await ElMessageBox.prompt(
      '账号、咨询记录、健康记录与上传的文档都会被永久删除，无法恢复。',
      '删除账号',
      {
        confirmButtonText: '永久删除',
        cancelButtonText: '取消',
        inputType: 'password',
        inputPlaceholder: '请输入当前密码',
        inputValidator: (value: string) => (value && value.length >= 6
          ? true
          : '请输入至少 6 位的当前密码'),
        type: 'warning',
      },
    )
    currentPassword = result.value
  } catch { return }
  deleting.value = true
  errorMessage.value = ''
  try {
    await store.deleteAccount(currentPassword)
    ElMessage.success('账号已删除')
    await router.push({ name: 'login' })
  } catch (error) {
    errorMessage.value = getApiErrorMessage(error)
  } finally {
    deleting.value = false
  }
}

onBeforeRouteLeave(async () => {
  if (!store.isAuthenticated) return true
  if (saving.value) return false
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('修改尚未保存，确定离开吗？', '离开个人资料', {
      confirmButtonText: '离开', cancelButtonText: '继续编辑', type: 'warning',
    })
    return true
  } catch { return false }
})
</script>

<template>
  <main class="profile-page">
    <section class="profile-card" aria-labelledby="profile-title">
      <header class="profile-header">
        <div class="avatar-editor">
          <div class="avatar">
            <img v-if="store.avatarUrl && !avatarFailed" :src="store.avatarUrl" alt="当前用户头像" @error="avatarFailed = true" />
            <el-icon v-else :size="30"><User /></el-icon>
          </div>
          <button type="button" :disabled="uploadingAvatar" @click="chooseAvatar">
            {{ uploadingAvatar ? '上传中…' : '更换头像' }}
          </button>
          <input ref="avatarInput" class="sr-only" type="file" accept="image/jpeg,image/png,image/webp" @change="changeAvatar" />
        </div>
        <div>
          <p class="caption">病理诊断科普助手</p>
          <h1 id="profile-title">账户信息</h1>
          <p class="subtitle">查看账户信息，更新头像、姓名与性别</p>
        </div>
      </header>

      <section class="account-info" aria-label="账户信息">
        <dl>
          <div><dt>用户名</dt><dd>{{ store.user?.username }}</dd></div>
          <div><dt>账户角色</dt><dd>{{ store.user?.role === 'admin' ? '管理员' : '普通用户' }}</dd></div>
          <div><dt>手机号</dt><dd>{{ store.user?.phoneMasked || '—' }}</dd></div>
          <div><dt>身份证号码</dt><dd>{{ store.user?.idCardMasked || '—' }}</dd></div>
          <div class="wide"><dt>注册时间</dt><dd>{{ registeredAt }}</dd></div>
        </dl>
        <p class="readonly-note">以上信息暂不支持修改。</p>
      </section>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top"
        size="large" :disabled="saving" @submit.prevent="save">
        <div class="editable-fields">
          <el-form-item label="姓名" prop="realName">
            <el-input v-model="form.realName" maxlength="20" autocomplete="name"
              placeholder="请输入姓名" :prefix-icon="User" />
          </el-form-item>
          <el-form-item label="性别" prop="gender">
            <el-select v-model="form.gender">
              <el-option label="男" value="male" />
              <el-option label="女" value="female" />
              <el-option label="不愿透露" value="private" />
            </el-select>
          </el-form-item>
        </div>
        <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon
          :closable="false" class="save-error" />
        <div class="actions">
          <span class="save-hint">{{ dirty ? '有尚未保存的修改' : '资料已与账户同步' }}</span>
          <el-button :disabled="!dirty || saving" @click="resetForm">取消修改</el-button>
          <el-button type="primary" native-type="submit" :loading="saving" :disabled="!dirty">
            保存修改
          </el-button>
        </div>
      </el-form>

      <section class="danger-zone" aria-label="删除账号">
        <h2>删除账号</h2>
        <p>账号、咨询记录、健康记录与上传的病历文档会被永久删除，无法恢复。删除前需要验证当前密码。</p>
        <el-button type="danger" plain :loading="deleting" @click="removeAccount">删除账号</el-button>
      </section>
    </section>
  </main>
</template>

<style scoped>
.profile-page { min-height: 100%; display: grid; place-items: center; padding: 40px;
  background: #fff; }
.profile-card { width: min(760px, 100%); padding: 32px 40px; border: 1px solid #dceaf5;
  border-radius: 22px; background: #fff; box-shadow: 0 24px 64px rgb(30 82 124 / 10%); }
.profile-header { display: flex; align-items: center; gap: 18px; margin: 28px 0; }
.avatar-editor { display: grid; justify-items: center; gap: 7px; flex: 0 0 auto; }
.avatar { display: grid; place-items: center; width: 64px; height: 64px;
  overflow: hidden; border-radius: 50%; color: var(--medical-blue); background: #eaf5ff; }
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.avatar-editor button { padding: 0; border: 0; background: transparent; color: var(--medical-blue);
  font-size: 11px; cursor: pointer; }
.avatar-editor button:disabled { color: #9aa8b5; cursor: default; }
.caption { color: var(--medical-blue); font-size: 13px; margin: 0 0 5px; }
h1 { margin: 0; color: var(--text-main); font-size: 27px; }
.subtitle { color: var(--text-secondary); font-size: 14px; margin: 8px 0 0; }
.account-info { background: #f6faff; border: 1px solid #e1edf7; border-radius: 14px;
  padding: 22px 24px; margin-bottom: 28px; }
dl { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 0; }
dt { color: var(--text-secondary); font-size: 13px; margin-bottom: 6px; }
dd { color: var(--text-main); font-size: 15px; margin: 0; overflow-wrap: anywhere; }
.wide { grid-column: 1 / -1; }
.readonly-note { color: #71869a; font-size: 12px; margin: 20px 0 0; }
.editable-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.actions { display: flex; align-items: center; border-top: 1px solid #e7eff6;
  margin-top: 8px; padding-top: 24px; }
.save-hint { margin-right: auto; color: var(--text-secondary); font-size: 13px; }
.save-error { margin: 4px 0 18px; }
.danger-zone { margin-top: 32px; padding-top: 24px; border-top: 1px solid #f0e2e0; }
.danger-zone h2 { margin: 0 0 8px; color: #b4442c; font-size: 16px; }
.danger-zone p { margin: 0 0 14px; color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
</style>
