<script setup lang="ts">
import { defineAsyncComponent, ref, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { FirstAidKit, User } from '@element-plus/icons-vue'
import ProfileView from './ProfileView.vue'

// 健康记录分栏按需加载：它带 ECharts（构建后约 540 kB），只看账户信息的人不该为它付下载成本。
const HealthRecordView = defineAsyncComponent(() => import('./HealthRecordView.vue'))

type SettingsTab = 'account' | 'health'

const TABS: { value: SettingsTab; label: string; icon: Component }[] = [
  { value: 'account', label: '账户信息', icon: User },
  { value: 'health', label: '健康记录', icon: FirstAidKit },
]

const route = useRoute()

/**
 * 初始分栏只读一次查询参数：旧路径 `/app/profile`、`/app/health-records` 会带 `?tab=` 重定向到这里。
 *
 * 之后切换分栏只改本地状态、不动地址。原因：工作区是 `<router-view :key="route.fullPath">`，
 * 查询参数一变整个页面就会重挂载，账户分栏里未保存的姓名/性别草稿会被悄悄抹掉。
 */
const tab = ref<SettingsTab>(String(route.query.tab) === 'health' ? 'health' : 'account')
</script>

<template>
  <main class="settings">
    <header class="settings__header">
      <h1 class="settings__title">设置</h1>
      <p class="settings__intro">
        账户资料与健康记录都在这里。健康记录只保存你在对话中<strong>自己说过</strong>的信息，
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
        <ProfileView />
      </section>
      <!-- 健康记录分栏是重内容（列表 + 图表），按需挂载，避免在账户分栏里白跑接口、白建图表。 -->
      <section v-if="tab === 'health'" role="tabpanel" aria-label="健康记录">
        <HealthRecordView />
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
</style>