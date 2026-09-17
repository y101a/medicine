<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { House, ChatDotRound, Clock, User, Plus, Fold, Expand, ArrowDown, FirstAidKit } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { getApiErrorMessage } from '../api/http'
import { useConsultationsStore } from '../stores/consultations'
import { useHealthRecordsStore } from '../stores/healthRecords'
import HealthRecordNoticeDialog from '../components/HealthRecordNoticeDialog.vue'

const store = useAuthStore()
const consultations = useConsultationsStore()
const healthRecords = useHealthRecordsStore()
watch(() => store.user?.id, (id) => {
  if (id) {
    void consultations.load()
    // 首次登录只提示一次；采集默认开启，用户可在健康记录页关闭。
    void healthRecords.checkFirstNotice()
  }
}, { immediate: true })
// 离开工作区（退出登录或登录态失效）时清空，避免下一个账号看到上一个用户的记录。
onUnmounted(() => healthRecords.reset())
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const avatarFailed = ref(false)
watch(() => store.avatarUrl, () => { avatarFailed.value = false })
const displayName = computed(() => store.user?.realName || store.user?.username || '用户')
const title = computed(() => ({
  home: '首页',
  chat: '智能咨询',
  consultation: '智能咨询',
  history: '咨询历史',
  healthRecords: '健康记录',
  profile: '个人中心',
}[String(route.name)] || '病理诊断科普助手'))
const links = [
  { path: '/app', label: '首页', icon: House, names: ['home'] },
  { path: '/app/chat', label: '智能咨询', icon: ChatDotRound, names: ['chat', 'consultation'] },
  { path: '/app/history', label: '咨询历史', icon: Clock, names: ['history'] },
  { path: '/app/health-records', label: '健康记录', icon: FirstAidKit, names: ['healthRecords'] },
  { path: '/app/profile', label: '个人中心', icon: User, names: ['profile'] },
]
async function newChat() {
  await router.push({ path: '/app/chat', query: { new: String(Date.now()) } })
}
async function menu(command: string) {
  if (command === 'profile') return router.push('/app/profile')
  if (store.pendingAction === 'logout') return
  try {
    await store.logout()
    await router.replace('/login')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
    await router.replace('/login')
  }
}
</script>

<template>
  <div class="workspace" :class="{ collapsed }">
    <aside class="sidebar">
      <div class="brand"><span class="brand-symbol">✦</span><span v-if="!collapsed">病理诊断科普助手<small>HEALTH COMPANION</small></span></div>
      <button class="new-chat" title="新建咨询" @click="newChat"><el-icon><Plus /></el-icon><span v-if="!collapsed">新建咨询</span></button>
      <nav aria-label="主导航">
        <router-link v-for="link in links" :key="link.path" :to="link.path"
          :title="link.label" :class="{ selected: link.names.includes(String(route.name)) }">
          <el-icon><component :is="link.icon" /></el-icon><span v-if="!collapsed">{{ link.label }}</span>
        </router-link>
      </nav>
      <section v-if="!collapsed" class="recent" aria-label="最近咨询">
        <p>最近咨询</p>
        <span v-if="consultations.loading">正在加载…</span>
        <button v-if="consultations.error" @click="consultations.load()">加载失败，点击重试</button>
        <span v-if="!consultations.loading && !consultations.error && !consultations.items.length">发送第一条消息后会出现在这里</span>
        <router-link v-for="item in consultations.items.slice(0, 10)" :key="item.id"
          :to="`/app/consultations/${item.id}`" :title="item.title"
          :class="{ active: route.params.id === item.id }">{{ item.title }}</router-link>
      </section>
      <div class="sidebar-bottom">
        <span v-if="!collapsed" class="version">健康科普 · 个人工作区</span>
        <button class="icon-button" :aria-label="collapsed ? '展开侧栏' : '收起侧栏'" @click="collapsed = !collapsed">
          <el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon>
        </button>
      </div>
    </aside>
    <div class="workspace-main">
      <header class="topbar">
        <div class="page-title">{{ title }}<span v-if="route.name === 'chat' || route.name === 'consultation'" class="preview-tag">AI 科普模式</span></div>
        <el-dropdown @command="menu">
          <button class="user-menu"><span class="user-avatar">
            <img v-if="store.avatarUrl && !avatarFailed" :src="store.avatarUrl" alt="" @error="avatarFailed = true" />
            <template v-else>{{ displayName.slice(0, 1) }}</template>
          </span>
            <span>{{ displayName }}</span><el-icon><ArrowDown /></el-icon>
          </button>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item command="profile">个人资料</el-dropdown-item>
            <el-dropdown-item command="logout" divided :disabled="store.pendingAction === 'logout'">退出登录</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
      </header>
      <div class="workspace-content"><router-view :key="route.fullPath" /></div>
    </div>
    <HealthRecordNoticeDialog />
  </div>
</template>

<style scoped>
.workspace { display: grid; grid-template-columns: 236px minmax(0, 1fr); height: 100vh; min-width: 1000px; background: #fff; }
.workspace.collapsed { grid-template-columns: 76px minmax(0, 1fr); }
.sidebar { display: flex; flex-direction: column; padding: 28px 16px 14px; background: #f6f8fb; border-right: 1px solid #e8edf3; }
.sidebar { min-height: 0; }
.recent { overflow-y: auto; margin: 22px 0; font-size: 12px; color: #8a99a8; }
.recent p { padding: 0 12px; }
.recent > span { display: block; padding: 8px 12px; line-height: 1.8; }
.recent a { display: block; padding: 10px 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-decoration: none; border-radius: 8px; color: #647588; }
.recent a:hover, .recent a.active { background: #e7f0fa; color: #196db2; }
.recent button { border: 0; background: none; color: #196db2; cursor: pointer; }
.brand { display: flex; align-items: center; gap: 10px; padding: 0 5px; font-size: 14px; font-weight: 650; white-space: nowrap; }
.brand-symbol { font-size: 29px; color: #237ac2; }
.brand small { display: block; font-size: 9px; letter-spacing: 1.5px; color: #91a2b4; margin-top: 5px; }
.new-chat { display: flex; align-items: center; gap: 10px; height: 43px; padding: 0 12px; margin: 32px 0 20px; background: #fff; border: 1px solid #dce4ec; border-radius: 9px; color: #284c6c; cursor: pointer; text-align: left; }
nav { display: grid; gap: 5px; }
nav a { display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 8px; text-decoration: none; color: #647588; font-size: 14px; white-space: nowrap; }
nav a:hover, .new-chat:hover { background: #edf3f9; }
nav a.selected { background: #e7f0fa; color: #196db2; font-weight: 600; }
.sidebar-note { margin: 38px 12px; font-size: 12px; color: #96a3b1; line-height: 1.8; }
.sidebar-note span { color: #718497; }
.sidebar-bottom { margin-top: auto; display: flex; align-items: center; justify-content: space-between; }
.version { font-size: 11px; color: #91a0af; }
.icon-button { padding: 8px; background: none; border: none; color: #718497; cursor: pointer; }
.workspace-main { min-width: 0; display: flex; flex-direction: column; min-height: 0; }
.topbar { height: 70px; flex-shrink: 0; display: flex; align-items: center; justify-content: space-between; padding: 0 32px; border-bottom: 1px solid #f0f3f7; }
.page-title { display: flex; align-items: center; gap: 12px; font-size: 14px; color: #344d64; }
.preview-tag { font-size: 11px; color: #7f90a1; border: 1px solid #e4eaf0; padding: 3px 7px; border-radius: 5px; }
.user-menu { display: flex; align-items: center; gap: 10px; border: none; background: transparent; color: #5b7084; font-size: 13px; cursor: pointer; }
.user-avatar { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%; background: #edf3fa; color: #3777ad; }
.user-avatar { overflow: hidden; }
.user-avatar img { width: 100%; height: 100%; object-fit: cover; }
.workspace-content { flex: 1; min-height: 0; overflow: auto; }
button:focus-visible, a:focus-visible { outline: 2px solid #398ad0; outline-offset: 3px; }
</style>
