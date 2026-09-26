<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Iphone, Lock } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import {
  PASSWORD_RESET_SENT_MESSAGE,
  authApi,
  getPhoneVerificationErrorMessage,
  getRetryAfterSeconds,
} from '../api/auth'
import { ApiError } from '../api/http'

interface ResetForm {
  phone: string
  code: string
  password: string
  confirmPassword: string
}

type Step = 'phone' | 'code' | 'password'

const STEP_LABELS: { value: Step; label: string }[] = [
  { value: 'phone', label: '手机号' },
  { value: 'code', label: '验证码' },
  { value: 'password', label: '新密码' },
]

const phonePattern = /^1[3-9]\d{9}$/
const router = useRouter()
const formRef = ref<FormInstance>()
const authStore = useAuthStore()

const step = ref<Step>('phone')
const form = reactive<ResetForm>({ phone: '', code: '', password: '', confirmPassword: '' })

/**
 * 挑战与令牌只放内存，不写浏览器存储（6 节硬约束）。
 *
 * 刷新页面等于放弃这次找回流程——方案第 11 节明确允许「刷新页面不必恢复未完成流程」，
 * 所以这里既不用 localStorage 也不用 sessionStorage，避免验证码或令牌被留在机器上。
 */
const challengeId = ref('')
const verificationToken = ref('')
const countdown = ref(0)
const sendingCode = ref(false)
const verifyingCode = ref(false)
const submitting = ref(false)
let countdownTimer: number | undefined

/** 发送阶段的统一文案。只要发出过请求就显示，措辞不随结果变化——不泄露账户是否存在。 */
const sentNotice = ref('')

const phoneLooksValid = computed(() => phonePattern.test(form.phone))
const canRequestCode = computed(
  () => phoneLooksValid.value && countdown.value === 0 && !sendingCode.value,
)

const rules: FormRules<ResetForm> = {
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
        if (!value) return callback(new Error('请输入手机号'))
        if (!phonePattern.test(value)) return callback(new Error('请输入有效的中国大陆手机号'))
        callback()
      },
      trigger: 'blur',
    },
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { len: 6, message: '验证码是 6 位数字', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度应为 6–32 位', trigger: 'blur' },
  ],
  confirmPassword: [
    {
      validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
        if (!value) return callback(new Error('请再次输入新密码'))
        if (value !== form.password) return callback(new Error('两次输入的密码不一致'))
        callback()
      },
      trigger: 'blur',
    },
  ],
}

function stopCountdown() {
  if (countdownTimer !== undefined) {
    window.clearInterval(countdownTimer)
    countdownTimer = undefined
  }
}

/** 倒计时只认服务端给的 `resendAfterSeconds`；前端倒计时只是体验层（8 节限流在后端）。 */
function startCountdown(seconds: number) {
  stopCountdown()
  countdown.value = Math.max(0, Math.ceil(seconds))
  if (countdown.value === 0) return
  countdownTimer = window.setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) stopCountdown()
  }, 1000)
}

onBeforeUnmount(stopCountdown)

async function requestCode() {
  if (!phoneLooksValid.value) {
    ElMessage.warning('请输入有效的中国大陆手机号')
    return
  }

  sendingCode.value = true
  try {
    const challenge = await authApi.requestPhoneVerificationCode({
      phone: form.phone,
      purpose: 'password_reset',
    })
    challengeId.value = challenge.challengeId
    form.code = ''
    startCountdown(challenge.resendAfterSeconds)
    sentNotice.value = PASSWORD_RESET_SENT_MESSAGE
    step.value = 'code'
  } catch (error) {
    // 限流不是「账户是否存在」的信号，照实提示并把剩余秒数用在倒计时上。
    const retryAfter = getRetryAfterSeconds(error)
    if (retryAfter !== undefined) startCountdown(retryAfter)
    ElMessage.error(getPhoneVerificationErrorMessage(error))
  } finally {
    sendingCode.value = false
  }
}

async function verifyCode() {
  if (!formRef.value) return
  const isValid = await formRef.value.validateField(['code']).catch(() => false)
  if (isValid === false) return

  verifyingCode.value = true
  try {
    const grant = await authApi.verifyPhoneVerificationCode({
      challengeId: challengeId.value,
      code: form.code,
    })
    verificationToken.value = grant.verificationToken
    step.value = 'password'
  } catch (error) {
    ElMessage.error(getPhoneVerificationErrorMessage(error))
    const code = error instanceof ApiError ? error.code : ''
    if (code === 'SMS_CODE_EXPIRED' || code === 'SMS_ATTEMPTS_EXCEEDED' || code === 'SMS_CHALLENGE_INVALID') {
      // 挑战已作废，退回第一步重新获取，别让用户对着一个死掉的输入框反复试。
      challengeId.value = ''
      form.code = ''
      stopCountdown()
      countdown.value = 0
      sentNotice.value = ''
      step.value = 'phone'
    }
  } finally {
    verifyingCode.value = false
  }
}

async function submitReset() {
  if (!formRef.value) return
  const isValid = await formRef.value.validate().catch(() => false)
  if (!isValid) return

  submitting.value = true
  try {
    await authStore.resetPassword({
      phone: form.phone,
      verificationToken: verificationToken.value,
      newPassword: form.password,
    })
    // 成功后不留任何验证态：令牌已被消费，新密码也不该继续停在内存里。
    verificationToken.value = ''
    challengeId.value = ''
    form.password = ''
    form.confirmPassword = ''
    form.code = ''
    stopCountdown()
    countdown.value = 0
    await router.replace({ name: 'login', query: { reason: 'password-reset' } })
  } catch (error) {
    ElMessage.error(getPhoneVerificationErrorMessage(error))
    const code = error instanceof ApiError ? error.code : ''
    if (code === 'PHONE_VERIFICATION_TOKEN_INVALID') {
      verificationToken.value = ''
      sentNotice.value = ''
      step.value = 'phone'
    }
  } finally {
    submitting.value = false
  }
}

function backToPhone() {
  step.value = 'phone'
  form.code = ''
  challengeId.value = ''
  sentNotice.value = ''
  stopCountdown()
  countdown.value = 0
}

function goToLogin() {
  router.push({ name: 'login' })
}
</script>

<template>
  <main class="forgot-page">
    <div class="background-orb background-orb--left" aria-hidden="true"></div>
    <div class="background-orb background-orb--right" aria-hidden="true"></div>

    <section class="forgot-card" aria-labelledby="forgot-title">
      <button type="button" class="back-button" @click="goToLogin">
        <el-icon><ArrowLeft /></el-icon>
        返回登录
      </button>

      <header class="brand">
        <div class="medical-mark" aria-hidden="true">
          <span></span>
          <span></span>
        </div>
        <p class="brand-caption">病理诊断科普助手</p>
        <h1 id="forgot-title">重设密码</h1>
        <p class="welcome-text">用已验证的手机号接收短信验证码，验证后设置新密码</p>
      </header>

      <ol class="forgot-steps">
        <li
          v-for="(item, index) in STEP_LABELS"
          :key="item.value"
          class="forgot-steps__item"
          :class="{
            'is-active': step === item.value,
            'is-done': STEP_LABELS.findIndex(entry => entry.value === step) > index,
          }"
        >
          <span class="forgot-steps__index">{{ index + 1 }}</span>{{ item.label }}
        </li>
      </ol>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        class="forgot-form"
        @submit.prevent="submitReset"
      >
        <template v-if="step === 'phone'">
          <el-form-item label="手机号" prop="phone">
            <el-input
              v-model.trim="form.phone"
              class="phone-input"
              :prefix-icon="Iphone"
              maxlength="11"
              inputmode="numeric"
              autocomplete="tel"
              placeholder="注册时绑定的手机号"
              clearable
            />
          </el-form-item>

          <el-button
            type="primary"
            class="send-code-button"
            :disabled="!canRequestCode"
            :loading="sendingCode"
            @click="requestCode"
          >
            {{ countdown > 0 ? `${countdown} 秒后可重发` : '获取验证码' }}
          </el-button>
        </template>

        <template v-else-if="step === 'code'">
          <p class="reset-notice" role="status">{{ sentNotice }}</p>

          <el-form-item label="短信验证码" prop="code">
            <el-input
              v-model.trim="form.code"
              class="code-input"
              maxlength="6"
              inputmode="numeric"
              autocomplete="one-time-code"
              placeholder="请输入 6 位验证码"
            />
          </el-form-item>

          <el-button
            type="primary"
            class="verify-code-button"
            :disabled="form.code.length !== 6"
            :loading="verifyingCode"
            @click="verifyCode"
          >
            验证
          </el-button>

          <div class="secondary-actions">
            <el-button
              class="resend-code-button"
              text
              :disabled="!canRequestCode"
              :loading="sendingCode"
              @click="requestCode"
            >
              {{ countdown > 0 ? `${countdown} 秒后可重发` : '重新获取验证码' }}
            </el-button>
            <el-button class="back-to-phone-button" text @click="backToPhone">换个手机号</el-button>
          </div>
        </template>

        <template v-else>
          <el-form-item label="新密码" prop="password">
            <el-input
              v-model="form.password"
              class="password-input"
              :prefix-icon="Lock"
              type="password"
              maxlength="32"
              autocomplete="new-password"
              placeholder="6–32 位"
              show-password
            />
          </el-form-item>

          <el-form-item label="确认新密码" prop="confirmPassword">
            <el-input
              v-model="form.confirmPassword"
              class="confirm-password-input"
              :prefix-icon="Lock"
              type="password"
              maxlength="32"
              autocomplete="new-password"
              placeholder="请再次输入新密码"
              show-password
            />
          </el-form-item>

          <el-button
            type="primary"
            native-type="submit"
            class="reset-button"
            :loading="submitting"
          >
            重设密码
          </el-button>

          <p class="password-notice">
            重设成功后，其他设备上的登录状态会立即失效，请用新密码重新登录。
          </p>
        </template>
      </el-form>

      <footer class="privacy-notice">
        短信验证码只用于本次身份确认，不会用于其他用途；手机号仍以加密方式保存
      </footer>
    </section>
  </main>
</template>

<style scoped>
.forgot-page {
  position: relative;
  display: grid;
  min-height: 100vh;
  place-items: center;
  overflow: hidden;
  padding: 32px 20px;
  background:
    linear-gradient(rgb(255 255 255 / 44%), rgb(255 255 255 / 44%)),
    linear-gradient(145deg, #f7fbff 0%, #eaf5ff 54%, #f5faff 100%);
}

.forgot-page::before {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgb(20 112 184 / 3%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(20 112 184 / 3%) 1px, transparent 1px);
  background-size: 34px 34px;
  content: "";
  mask-image: linear-gradient(to bottom, black, transparent 76%);
}

.background-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(2px);
  pointer-events: none;
}

.background-orb--left {
  top: -120px;
  left: -100px;
  width: 360px;
  height: 360px;
  background: rgb(57 156 226 / 12%);
}

.background-orb--right {
  right: -90px;
  bottom: -150px;
  width: 420px;
  height: 420px;
  background: rgb(22 119 200 / 10%);
}

.forgot-card {
  position: relative;
  z-index: 1;
  width: min(100%, 470px);
  padding: 30px 38px 26px;
  background: rgb(255 255 255 / 96%);
  border: 1px solid rgb(210 228 242 / 90%);
  border-radius: 22px;
  box-shadow:
    0 26px 70px rgb(30 82 124 / 13%),
    0 4px 16px rgb(30 82 124 / 5%);
}

.back-button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  color: var(--medical-blue);
  font-size: 14px;
  background: none;
  border: 0;
  cursor: pointer;
}

.back-button:hover {
  color: var(--medical-blue-dark);
}

.brand {
  margin: 16px 0 20px;
  text-align: center;
}

.medical-mark {
  position: relative;
  width: 54px;
  height: 54px;
  margin: 0 auto 14px;
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
  margin: 0 0 6px;
  color: var(--medical-blue);
  font-size: 13px;
  font-weight: 650;
  letter-spacing: 0.1em;
}

h1 {
  margin: 0;
  color: var(--text-main);
  font-size: 24px;
  line-height: 1.35;
}

.welcome-text {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.forgot-steps {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  margin: 0 0 20px;
  padding: 0;
  list-style: none;
}

.forgot-steps__item {
  display: flex;
  flex: 1 1 0;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 7px 6px;
  color: #7b8ea1;
  font-size: 12px;
  background: #f5f9fd;
  border-radius: 8px;
}

.forgot-steps__item.is-active {
  color: var(--medical-blue-dark);
  font-weight: 650;
  background: var(--medical-blue-soft);
}

.forgot-steps__item.is-done {
  color: #1f7a45;
  background: #eefaf1;
}

.forgot-steps__index {
  display: inline-flex;
  width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  background: rgb(255 255 255 / 80%);
  border-radius: 50%;
}

.forgot-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.forgot-form :deep(.el-form-item__label) {
  padding-bottom: 7px;
  color: #294b68;
  font-weight: 600;
  line-height: 20px;
}

.forgot-form :deep(.el-input__wrapper) {
  min-height: 46px;
  padding: 1px 14px;
  background: #fbfdff;
  border-radius: 10px;
  box-shadow: 0 0 0 1px #d9e6f1 inset;
}

.forgot-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #95c5e9 inset;
}

.forgot-form :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  box-shadow: 0 0 0 1px var(--medical-blue) inset, 0 0 0 3px rgb(22 119 200 / 9%);
}

.forgot-form :deep(.el-input__prefix-inner) {
  color: #7c9ab3;
}

.send-code-button,
.verify-code-button,
.reset-button {
  width: 100%;
  height: 46px;
  border: 0;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: 0.06em;
  box-shadow: 0 10px 22px rgb(22 119 200 / 20%);
}

.reset-notice {
  margin: 0 0 16px;
  padding: 11px 14px;
  color: #245073;
  font-size: 13px;
  line-height: 1.7;
  background: var(--medical-blue-soft);
  border-radius: 9px;
}

.secondary-actions {
  display: flex;
  justify-content: space-between;
  margin-top: 12px;
}

.password-notice {
  margin: 14px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.7;
}

.privacy-notice {
  margin: 20px 0 0;
  padding: 10px 14px;
  color: #587186;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
  background: var(--medical-blue-soft);
  border-radius: 9px;
}

@media (max-width: 480px) {
  .forgot-page {
    padding: 18px 14px;
  }

  .forgot-card {
    padding: 22px 18px;
  }

  .forgot-steps {
    gap: 5px;
  }

  .forgot-steps__item {
    font-size: 11px;
  }
}
</style>