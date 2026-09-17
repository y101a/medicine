<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, CreditCard, Iphone, Lock, User } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { getApiErrorMessage } from '../api/http'
import type { Gender } from '../types/auth'

interface RegisterForm {
  username: string
  realName: string
  phone: string
  idCard: string
  gender: '' | Gender
  password: string
  confirmPassword: string
}

type ValidationCallback = (error?: Error) => void

const router = useRouter()
const formRef = ref<FormInstance>()
const authStore = useAuthStore()

const form = reactive<RegisterForm>({
  username: '',
  realName: '',
  phone: '',
  idCard: '',
  gender: '',
  password: '',
  confirmPassword: '',
})

function validateRealName(_rule: unknown, value: string, callback: ValidationCallback) {
  if (!value) return callback(new Error('请输入姓名'))
  if (value.length < 2 || value.length > 20) {
    return callback(new Error('姓名长度应为 2–20 个字符'))
  }
  if (!/^[A-Za-z\u4E00-\u9FFF·]+$/.test(value)) {
    return callback(new Error('姓名仅支持中文、英文字母和间隔符 ·'))
  }
  callback()
}

function validatePhone(_rule: unknown, value: string, callback: ValidationCallback) {
  if (!value) return callback(new Error('请输入手机号'))
  if (!/^1[3-9]\d{9}$/.test(value)) {
    return callback(new Error('请输入有效的中国大陆手机号'))
  }
  callback()
}

function isValidIdCard(value: string) {
  const idCard = value.toUpperCase()
  if (!/^\d{17}[\dX]$/.test(idCard)) return false

  const provinceCodes = new Set([
    '11', '12', '13', '14', '15',
    '21', '22', '23',
    '31', '32', '33', '34', '35', '36', '37',
    '41', '42', '43', '44', '45', '46',
    '50', '51', '52', '53', '54',
    '61', '62', '63', '64', '65',
    '71', '81', '82',
  ])
  if (!provinceCodes.has(idCard.slice(0, 2))) return false

  const birthText = idCard.slice(6, 14)
  const year = Number(birthText.slice(0, 4))
  const month = Number(birthText.slice(4, 6))
  const day = Number(birthText.slice(6, 8))
  const birthDate = new Date(year, month - 1, day)
  const today = new Date()
  if (
    year < 1900
    || birthDate > today
    || birthDate.getFullYear() !== year
    || birthDate.getMonth() !== month - 1
    || birthDate.getDate() !== day
  ) {
    return false
  }

  const weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
  const checkCodes = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']
  const sum = weights.reduce((total, weight, index) => total + Number(idCard[index]) * weight, 0)
  return checkCodes[sum % 11] === idCard[17]
}

function validateIdCard(_rule: unknown, value: string, callback: ValidationCallback) {
  if (!value) return callback(new Error('请输入身份证号码'))
  if (!isValidIdCard(value)) {
    return callback(new Error('请输入有效的中国大陆居民身份证号码'))
  }
  callback()
}

function validateConfirmPassword(_rule: unknown, value: string, callback: ValidationCallback) {
  if (!value) return callback(new Error('请再次输入密码'))
  if (value !== form.password) return callback(new Error('两次输入的密码不一致'))
  callback()
}

const rules: FormRules<RegisterForm> = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 4, max: 20, message: '用户名长度应为 4–20 个字符', trigger: 'blur' },
  ],
  realName: [{ validator: validateRealName, trigger: 'blur' }],
  phone: [{ validator: validatePhone, trigger: 'blur' }],
  idCard: [{ validator: validateIdCard, trigger: 'blur' }],
  gender: [{ required: true, message: '请选择性别', trigger: 'change' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度应为 6–32 位', trigger: 'blur' },
  ],
  confirmPassword: [{ validator: validateConfirmPassword, trigger: 'blur' }],
}

async function handleRegister() {
  if (!formRef.value) return

  const isValid = await formRef.value.validate().catch(() => false)
  if (!isValid) return

  try {
    const result = await authStore.register({
      username: form.username,
      realName: form.realName,
      phone: form.phone,
      idCard: form.idCard,
      gender: form.gender as Gender,
      password: form.password,
    })
    const registeredAt = new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(result.user.registeredAt))
    ElMessage.success(`注册成功，注册时间：${registeredAt}`)
    formRef.value?.resetFields()
    window.setTimeout(() => router.push('/login'), 800)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

function goToLogin() {
  router.push('/login')
}
</script>

<template>
  <main class="register-page">
    <div class="background-orb background-orb--left" aria-hidden="true"></div>
    <div class="background-orb background-orb--right" aria-hidden="true"></div>

    <section class="register-card" aria-labelledby="register-title">
      <button type="button" class="back-button" @click="goToLogin">
        <el-icon><ArrowLeft /></el-icon>
        返回登录
      </button>

      <header class="brand">
        <div class="medical-mark" aria-hidden="true">
          <span></span>
          <span></span>
        </div>
        <div>
          <p class="brand-caption">病理诊断科普助手</p>
          <h1 id="register-title">创建普通用户账户</h1>
          <p class="welcome-text">填写基本信息，开始使用健康科普服务</p>
        </div>
      </header>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        class="register-form"
        @submit.prevent="handleRegister"
      >
        <div class="form-grid">
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="form.username"
              :prefix-icon="User"
              maxlength="20"
              autocomplete="username"
              placeholder="4–20 个字符"
              clearable
            />
          </el-form-item>

          <el-form-item label="姓名" prop="realName">
            <el-input
              v-model.trim="form.realName"
              :prefix-icon="User"
              maxlength="20"
              autocomplete="name"
              placeholder="请输入姓名"
              clearable
            />
          </el-form-item>

          <el-form-item label="手机号" prop="phone">
            <el-input
              v-model.trim="form.phone"
              :prefix-icon="Iphone"
              maxlength="11"
              inputmode="numeric"
              autocomplete="tel"
              placeholder="中国大陆手机号"
              clearable
            />
          </el-form-item>

          <el-form-item label="性别" prop="gender">
            <el-select v-model="form.gender" placeholder="请选择性别" class="full-width">
              <el-option label="男" value="male" />
              <el-option label="女" value="female" />
              <el-option label="不愿透露" value="private" />
            </el-select>
          </el-form-item>

          <el-form-item label="身份证号码" prop="idCard" class="form-item--wide">
            <el-input
              v-model.trim="form.idCard"
              :prefix-icon="CreditCard"
              maxlength="18"
              autocomplete="off"
              placeholder="请输入 18 位中国大陆居民身份证号码"
              clearable
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              :prefix-icon="Lock"
              type="password"
              maxlength="32"
              autocomplete="new-password"
              placeholder="6–32 位"
              show-password
            />
          </el-form-item>

          <el-form-item label="确认密码" prop="confirmPassword">
            <el-input
              v-model="form.confirmPassword"
              :prefix-icon="Lock"
              type="password"
              maxlength="32"
              autocomplete="new-password"
              placeholder="请再次输入密码"
              show-password
            />
          </el-form-item>
        </div>

        <el-button
          type="primary"
          native-type="submit"
          :loading="authStore.pendingAction === 'register'"
          class="register-button"
        >
          创建账户
        </el-button>
      </el-form>

      <p class="login-prompt">
        已有账户？
        <button type="button" class="text-button" @click="goToLogin">立即登录</button>
      </p>

      <footer class="privacy-notice">
        姓名、手机号和身份证将加密保存，页面仅展示脱敏信息
      </footer>
    </section>
  </main>
</template>

<style scoped>
.register-page {
  position: relative;
  display: grid;
  min-height: 100vh;
  place-items: center;
  overflow: hidden;
  padding: 34px 24px;
  background:
    linear-gradient(rgb(255 255 255 / 42%), rgb(255 255 255 / 42%)),
    linear-gradient(145deg, #f7fbff 0%, #eaf5ff 54%, #f5faff 100%);
}

.register-page::before {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgb(20 112 184 / 3%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(20 112 184 / 3%) 1px, transparent 1px);
  background-size: 34px 34px;
  content: "";
  mask-image: linear-gradient(to bottom, black, transparent 78%);
}

.background-orb {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}

.background-orb--left {
  top: -130px;
  left: -100px;
  width: 380px;
  height: 380px;
  background: rgb(57 156 226 / 12%);
}

.background-orb--right {
  right: -100px;
  bottom: -170px;
  width: 440px;
  height: 440px;
  background: rgb(22 119 200 / 10%);
}

.register-card {
  position: relative;
  z-index: 1;
  width: 650px;
  padding: 30px 42px 26px;
  background: rgb(255 255 255 / 97%);
  border: 1px solid rgb(210 228 242 / 90%);
  border-radius: 22px;
  box-shadow:
    0 26px 70px rgb(30 82 124 / 13%),
    0 4px 16px rgb(30 82 124 / 5%);
}

.back-button,
.text-button {
  color: var(--medical-blue);
  background: none;
  border: 0;
  cursor: pointer;
}

.back-button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  font-size: 14px;
}

.back-button:hover,
.text-button:hover {
  color: var(--medical-blue-dark);
}

.brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin: 18px 0 25px;
  text-align: left;
}

.medical-mark {
  position: relative;
  flex: 0 0 auto;
  width: 54px;
  height: 54px;
  background: #fff0f0;
  border: 1px solid #ffe0e1;
  border-radius: 15px;
  box-shadow: 0 8px 22px rgb(229 72 77 / 10%);
}

.medical-mark span {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 29px;
  height: 9px;
  background: var(--medical-red);
  border-radius: 2px;
  transform: translate(-50%, -50%);
}

.medical-mark span:last-child {
  transform: translate(-50%, -50%) rotate(90deg);
}

.brand-caption {
  margin: 0 0 4px;
  color: var(--medical-blue);
  font-size: 13px;
  font-weight: 650;
  letter-spacing: 0.08em;
}

h1 {
  margin: 0;
  color: var(--text-main);
  font-size: 25px;
  line-height: 1.35;
}

.welcome-text {
  margin: 5px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 20px;
}

.form-item--wide {
  grid-column: 1 / -1;
}

.register-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.register-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  color: #294b68;
  font-weight: 600;
  line-height: 20px;
}

.register-form :deep(.el-input__wrapper),
.register-form :deep(.el-select__wrapper) {
  min-height: 44px;
  background: #fbfdff;
  border-radius: 10px;
  box-shadow: 0 0 0 1px #d9e6f1 inset;
}

.register-form :deep(.el-input__wrapper:hover),
.register-form :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px #95c5e9 inset;
}

.register-form :deep(.el-input__wrapper.is-focus),
.register-form :deep(.el-select__wrapper.is-focused) {
  background: #fff;
  box-shadow: 0 0 0 1px var(--medical-blue) inset, 0 0 0 3px rgb(22 119 200 / 9%);
}

.register-form :deep(.el-input__prefix-inner) {
  color: #7c9ab3;
}

.full-width,
.register-button {
  width: 100%;
}

.register-button {
  height: 46px;
  margin-top: 2px;
  border: 0;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: 0.08em;
  box-shadow: 0 10px 22px rgb(22 119 200 / 20%);
}

.login-prompt {
  margin: 18px 0;
  color: var(--text-secondary);
  font-size: 14px;
  text-align: center;
}

.text-button {
  padding: 0;
  font-weight: 650;
}

.privacy-notice {
  padding: 10px 14px;
  color: #587186;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
  background: var(--medical-blue-soft);
  border-radius: 9px;
}

@media (max-height: 790px) {
  .register-page {
    align-items: start;
    overflow-y: auto;
    padding-block: 22px;
  }

  .register-card {
    padding-top: 24px;
  }

  .brand {
    margin-block: 12px 18px;
  }
}
</style>
