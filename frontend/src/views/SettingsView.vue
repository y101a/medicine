<script setup lang="ts">
import { defineAsyncComponent, computed, onBeforeUnmount, ref, watch, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { FirstAidKit, Key, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ProfileView from './ProfileView.vue'
import ModelCredentialsPanel from '../components/settings/ModelCredentialsPanel.vue'
import { useAuthStore } from '../stores/auth'
import { getPhoneVerificationErrorMessage, getRetryAfterSeconds } from '../api/auth'
import { ApiError } from '../api/http'

// 健康记录分栏按需加载：它带 ECharts（构建后约 540 kB），只看账户信息的人不该为它付下载成本。
const HealthRecordView = defineAsyncComponent(() => import('./HealthRecordView.vue'))

type SettingsTab = 'account' | 'health' | 'credentials'

const TABS: { value: SettingsTab; label: string; icon: Component }[] = [
  { value: 'account', label: '账户信息', icon: User },
  { value: 'health', label: '健康记录', icon: FirstAidKit },
  { value: 'credentials', label: '模型与密钥', icon: Key },
]

const route = useRoute()

/**
 * 初始分栏只读一次查询参数：旧路径 `/app/profile`、`/app/health-records` 会带 `?tab=` 重定向到这里。
 *
 * 之后切换分栏只改本地状态、不动地址。原因：工作区是 `<router-view :key="route.fullPath">`，
 * 查询参数一变整个页面就会重挂载，账户分栏里未保存的姓名/性别草稿会被悄悄抹掉。
 */
const requestedTab = String(route.query.tab)
const tab = ref<SettingsTab>(
  requestedTab === 'health' ? 'health' : requestedTab === 'credentials' ? 'credentials' : 'account',
)

/**
 * 「模型与密钥」里可能正粘着一个还没保存的 Key，所以这个分栏一旦打开就保持挂载（v-show），
 * 切走再切回不会把输入框清空。但首次打开前不挂载——账户分栏下不该白跑一次凭据接口。
 */
const credentialsOpened = ref(tab.value === 'credentials')
watch(tab, value => {
  if (value === 'credentials') credentialsOpened.value = true
})

/**
 * 已有用户的手机号补验证（方案第 5.5 节）。
 *
 * 只在后端明确说 `phoneVerified === false` 时出现：迁移前的老用户是这个状态，新注册用户
 * 是 `true`。手机号一律只显示脱敏值——完整号码连后端都只在解密后使用，界面不需要它。
 */
const authStore = useAuthStore()
const needsPhoneVerification = computed(() => authStore.user?.phoneVerified === false)

const phoneChallengeId = ref('')
const phoneCode = ref('')
const phoneCodeSent = ref(false)
const phoneCountdown = ref(0)
const sendingPhoneCode = ref(false)
const confirmingPhone = ref(false)
let phoneCountdownTimer: number | undefined

function stopPhoneCountdown() {
  if (phoneCountdownTimer !== undefined) {
    window.clearInterval(phoneCountdownTimer)
    phoneCountdownTimer = undefined
  }
}

function startPhoneCountdown(seconds: number) {
  stopPhoneCountdown()
  phoneCountdown.value = Math.max(0, Math.ceil(seconds))
  if (phoneCountdown.value === 0) return
  phoneCountdownTimer = window.setInterval(() => {
    phoneCountdown.value -= 1
    if (phoneCountdown.value <= 0) stopPhoneCountdown()
  }, 1000)
}

onBeforeUnmount(stopPhoneCountdown)

function resetPhoneVerification() {
  stopPhoneCountdown()
  phoneCountdown.value = 0
  phoneChallengeId.value = ''
  phoneCode.value = ''
  phoneCodeSent.value = false
}

async function requestPhoneCode() {
  sendingPhoneCode.value = true
  try {
    const challenge = await authStore.requestCurrentPhoneCode()
    phoneChallengeId.value = challenge.challengeId
    phoneCode.value = ''
    phoneCodeSent.value = true
    startPhoneCountdown(challenge.resendAfterSeconds)
    ElMessage.success('验证码已发送到你的手机')
  } catch (error) {
    const retryAfter = getRetryAfterSeconds(error)
    if (retryAfter !== undefined) startPhoneCountdown(retryAfter)
    ElMessage.error(getPhoneVerificationErrorMessage(error))
  } finally {
    sendingPhoneCode.value = false
  }
}

async function confirmPhoneCode() {
  confirmingPhone.value = true
  try {
    await authStore.confirmCurrentPhone({ challengeId: phoneChallengeId.value, code: phoneCode.value })
    ElMessage.success('手机号验证完成，现在可以使用短信找回密码了')
    resetPhoneVerification()
  } catch (error) {
    ElMessage.error(getPhoneVerificationErrorMessage(error))
    const code = error instanceof ApiError ? error.code : ''
    if (code === 'SMS_CODE_EXPIRED' || code === 'SMS_ATTEMPTS_EXCEEDED' || code === 'SMS_CHALLENGE_INVALID') {
      resetPhoneVerification()
    }
  } finally {
    confirmingPhone.value = false
  }
}
</script>

<template>
  <main class="settings">
    <header class="settings__header">
      <h1 class="settings__title">设置</h1>
      <p class="settings__intro">
        账户资料、健康记录与模型密钥都在这里。健康记录只保存你在对话中<strong>自己说过</strong>的信息，
        是背景资料，不是诊断结论，也不能替代医生面诊。
      </p>
    </header>

    <nav class="settings__tabs" role="tablist" aria-label="设置分栏">
      <button
        v-for="item in TABS"
        :key="item.value"
        type="button"
        role="tab"
        :aria-selected="tab === item.value"
        :class="{ 'is-active': tab === item.value }"
        @click="tab = item.value"
      >
        <el-icon><component :is="item.icon" /></el-icon>{{ item.label }}
      </button>
    </nav>

    <div class="settings__panel">
      <!-- 账户分栏用 v-show 保持挂载：里面有未保存的草稿，切分栏不该丢。 -->
      <section v-show="tab === 'account'" role="tabpanel" aria-label="账户信息">
        <!-- 补验证只在 phoneVerified === false 时出现；验证完成后本地状态立刻变 true，入口自动消失。 -->
        <section
          v-if="needsPhoneVerification"
          class="phone-verification"
          aria-labelledby="phone-verification-title"
        >
          <h2 id="phone-verification-title" class="phone-verification__title">验证当前手机号</h2>
          <p class="phone-verification__intro">
            这个账户还没有完成短信验证。完成一次验证后才能使用「忘记密码」里的短信找回功能。
            验证码会发送到 {{ authStore.user?.phoneMasked || '账户中已加密保存的手机号' }}。
          </p>
          <div class="phone-verification__row">
            <el-input
              v-model.trim="phoneCode"
              class="phone-verification__code"
              maxlength="6"
              inputmode="numeric"
              autocomplete="one-time-code"
              placeholder="6 位验证码"
              :disabled="!phoneCodeSent"
            />
            <el-button
              class="phone-verification__confirm"
              :disabled="!phoneCodeSent || phoneCode.length !== 6"
              :loading="confirmingPhone"
              @click="confirmPhoneCode"
            >
              确认验证
            </el-button>
            <el-button
              class="phone-verification__request"
              :disabled="phoneCountdown > 0 || sendingPhoneCode"
              :loading="sendingPhoneCode"
              @click="requestPhoneCode"
            >
              {{
                phoneCountdown > 0
                  ? `${phoneCountdown} 秒后可重发`
                  : (phoneCodeSent ? '重新获取验证码' : '获取验证码')
              }}
            </el-button>
          </div>
          <p v-if="phoneCodeSent" class="phone-verification__hint">
            验证码 5 分钟内有效；验证成功后这个入口会自动消失。
          </p>
        </section>

        <ProfileView />
      </section>
      <!-- 健康记录分栏是重内容（列表 + 图表），按需挂载，避免在账户分栏里白跑接口、白建图表。 -->
      <section v-if="tab === 'health'" role="tabpanel" aria-label="健康记录">
        <HealthRecordView />
      </section>
      <!-- 首次打开才挂载（避免白跑凭据接口），之后保持挂载（避免丢掉粘贴了一半的 Key）。 -->
      <section v-show="tab === 'credentials'" role="tabpanel" aria-label="模型与密钥">
        <ModelCredentialsPanel v-if="credentialsOpened" />
      </section>
    </div>
  </main>
</template>

<style scoped>
.settings { min-height: 100%; padding: 30px 34px 40px; background: #fff; }
.settings__title { margin: 0 0 8px; font-size: 22px; color: var(--text-main); }
.settings__intro { margin: 0; max-width: 760px; color: var(--text-secondary); font-size: 13px; line-height: 1.8; }
.settings__tabs { display: flex; gap: 6px; margin: 22px 0 20px; border-bottom: 1px solid #eef3f8; }
.settings__tabs button { display: flex; align-items: center; gap: 8px; margin-bottom: -1px; padding: 10px 14px;
  border: 0; border-bottom: 2px solid transparent; background: none; color: #647588; font-size: 14px; cursor: pointer; }
.settings__tabs button:hover { color: #196db2; }
.settings__tabs button.is-active { color: #196db2; border-bottom-color: #237ac2; font-weight: 600; }
.settings__tabs button:focus-visible { outline: 2px solid #398ad0; outline-offset: 2px; }

.phone-verification { margin: 0 0 22px; padding: 18px 20px; background: #f7fbff;
  border: 1px solid #dceaf6; border-radius: 14px; }
.phone-verification__title { margin: 0 0 8px; font-size: 16px; color: var(--text-main); }
.phone-verification__intro { margin: 0 0 14px; max-width: 720px; color: var(--text-secondary);
  font-size: 13px; line-height: 1.8; }
.phone-verification__row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.phone-verification__code { width: 180px; }
.phone-verification__hint { margin: 10px 0 0; color: var(--text-secondary); font-size: 12px; }
</style>