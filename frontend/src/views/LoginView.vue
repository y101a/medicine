<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { getApiErrorMessage } from '../api/http'

interface LoginForm {
  username: string
  password: string
}

const formRef = ref<FormInstance>()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const form = reactive<LoginForm>({
  username: '',
  password: '',
})

const rules: FormRules<LoginForm> = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 4, max: 20, message: '用户名长度应为 4–20 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度应为 6–32 位', trigger: 'blur' },
  ],
}

async function handleLogin() {
  if (!formRef.value) return

  const isValid = await formRef.value.validate().catch(() => false)
  if (!isValid) return

  try {
    await authStore.login({ username: form.username, password: form.password })
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/app'
    await router.replace(redirect)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

onMounted(() => {
  if (route.query.reason === 'expired') ElMessage.warning('登录状态已失效，请重新登录')
})

function showForgotPasswordTip() {
  ElMessage.info('忘记密码功能暂未开放')
}

function goToRegister() {
  router.push('/register')
}
</script>

<template>
  <main class="login-page">
    <div class="background-orb background-orb--left" aria-hidden="true"></div>
    <div class="background-orb background-orb--right" aria-hidden="true"></div>

    <section class="login-card" aria-labelledby="login-title">
      <header class="brand">
        <div class="medical-mark" aria-hidden="true">
          <span></span>
          <span></span>
        </div>
        <p class="brand-caption">智能医疗健康科普平台</p>
        <h1 id="login-title">病理诊断科普助手</h1>
        <p class="welcome-text">欢迎回来，请登录您的账户</p>
      </header>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        class="login-form"
        @submit.prevent="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            :prefix-icon="User"
            maxlength="20"
            autocomplete="username"
            placeholder="请输入用户名"
            clearable
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            :prefix-icon="Lock"
            type="password"
            maxlength="32"
            autocomplete="current-password"
            placeholder="请输入密码"
            show-password
          />
        </el-form-item>

        <div class="form-actions">
          <button type="button" class="text-button" @click="showForgotPasswordTip">
            忘记密码？
          </button>
        </div>

        <el-button
          type="primary"
          native-type="submit"
          :loading="authStore.pendingAction === 'login'"
          class="login-button"
        >
          登录
        </el-button>
      </el-form>

      <p class="register-prompt">
        还没有账户？
        <button type="button" class="text-button text-button--strong" @click="goToRegister">
          注册账号
        </button>
      </p>

      <footer class="medical-notice">
        <span class="notice-dot" aria-hidden="true"></span>
        本产品仅提供健康科普信息，不能替代专业医生的诊断与治疗
      </footer>
    </section>
  </main>
</template>

<style scoped>
.login-page {
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

.login-page::before {
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

.login-card {
  position: relative;
  z-index: 1;
  width: min(100%, 440px);
  padding: 38px 42px 30px;
  background: rgb(255 255 255 / 96%);
  border: 1px solid rgb(210 228 242 / 90%);
  border-radius: 22px;
  box-shadow:
    0 26px 70px rgb(30 82 124 / 13%),
    0 4px 16px rgb(30 82 124 / 5%);
}

.brand {
  margin-bottom: 28px;
  text-align: center;
}

.medical-mark {
  position: relative;
  width: 54px;
  height: 54px;
  margin: 0 auto 16px;
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
  margin: 0 0 8px;
  color: var(--medical-blue);
  font-size: 13px;
  font-weight: 650;
  letter-spacing: 0.12em;
}

h1 {
  margin: 0;
  color: var(--text-main);
  font-size: 27px;
  font-weight: 700;
  line-height: 1.35;
}

.welcome-text {
  margin: 10px 0 0;
  color: var(--text-secondary);
  font-size: 14px;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.login-form :deep(.el-form-item__label) {
  padding-bottom: 7px;
  color: #294b68;
  font-weight: 600;
  line-height: 20px;
}

.login-form :deep(.el-input__wrapper) {
  min-height: 46px;
  padding: 1px 14px;
  background: #fbfdff;
  border-radius: 10px;
  box-shadow: 0 0 0 1px #d9e6f1 inset;
  transition: box-shadow 0.2s ease, background 0.2s ease;
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #95c5e9 inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  box-shadow: 0 0 0 1px var(--medical-blue) inset, 0 0 0 3px rgb(22 119 200 / 9%);
}

.login-form :deep(.el-input__prefix-inner) {
  color: #7c9ab3;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  margin: -6px 0 20px;
}

.text-button {
  padding: 0;
  color: var(--medical-blue);
  background: none;
  border: 0;
  cursor: pointer;
}

.text-button:hover,
.text-button:focus-visible {
  color: var(--medical-blue-dark);
  text-decoration: underline;
}

.text-button:focus-visible {
  outline: 2px solid rgb(22 119 200 / 28%);
  outline-offset: 3px;
  border-radius: 3px;
}

.login-button {
  width: 100%;
  height: 46px;
  border: 0;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: 0.08em;
  box-shadow: 0 10px 22px rgb(22 119 200 / 20%);
}

.register-prompt {
  margin: 23px 0 27px;
  color: var(--text-secondary);
  font-size: 14px;
  text-align: center;
}

.text-button--strong {
  font-weight: 650;
}

.medical-notice {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin: 0;
  padding: 12px 14px;
  color: #587186;
  font-size: 12px;
  line-height: 1.65;
  background: var(--medical-blue-soft);
  border-radius: 9px;
}

.notice-dot {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  margin-top: 6px;
  background: var(--medical-blue);
  border-radius: 50%;
}

@media (max-height: 650px) and (min-width: 521px) {
  .login-page {
    padding-block: 18px;
  }

  .login-card {
    padding-block: 26px 22px;
  }

  .brand {
    margin-bottom: 20px;
  }
}
</style>
