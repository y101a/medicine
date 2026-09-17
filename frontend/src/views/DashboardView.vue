<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, ChatDotRound, Clock, Compass, Document, Lock } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { useConsultationsStore } from '../stores/consultations'

const router = useRouter()
const auth = useAuthStore()
const consultations = useConsultationsStore()
const displayName = computed(() => auth.user?.realName || auth.user?.username || '用户')
const consultationCount = computed(() => `${consultations.items.length}${consultations.hasMore ? '+' : ''}`)
const latestTime = computed(() => {
  const value = consultations.items[0]?.updatedAt
  return value ? new Date(value).toLocaleDateString('zh-CN') : '暂无记录'
})
const quickStarts = [
  { title: '描述身体症状', text: '按发生时间、持续时长和感受逐步说明', icon: ChatDotRound, prompt: '我想了解这些症状的可能原因：' },
  { title: '了解就医方向', text: '根据当前情况了解科室与就医紧急程度', icon: Compass, prompt: '我想了解应该去哪个科室就诊。我的情况是：' },
  { title: '读懂医学术语', text: '把检查单或病历中的陌生词语讲清楚', icon: Document, prompt: '请用通俗的语言解释这个医学术语：' },
]

function start(prompt = '') {
  void router.push({ path: '/app/chat', query: prompt ? { prompt } : undefined })
}
</script>

<template>
  <main class="dashboard">
    <section class="hero">
      <div>
        <p class="eyebrow">健康科普个人工作区</p>
        <h1>{{ displayName }}，你好</h1>
        <p>从一个症状或健康疑问开始，我们会帮助你理清信息与下一步就医方向。</p>
        <button class="primary-action" @click="start()">
          开始智能咨询 <el-icon><ArrowRight /></el-icon>
        </button>
      </div>
      <div class="hero-symbol" aria-hidden="true"><span>✦</span></div>
    </section>

    <section class="summary" aria-label="工作区概览">
      <article><el-icon><Clock /></el-icon><div><span>已保存咨询</span><strong>{{ consultationCount }}</strong></div></article>
      <article><el-icon><ChatDotRound /></el-icon><div><span>最近咨询</span><strong class="date">{{ latestTime }}</strong></div></article>
      <article><el-icon><Lock /></el-icon><div><span>账户数据</span><strong class="safe">独立保存</strong></div></article>
    </section>

    <div class="content-grid">
      <section class="panel quick-panel">
        <div class="section-heading"><div><h2>快捷开始</h2><p>选择一个方向，也可以进入咨询后自由描述。</p></div></div>
        <div class="quick-list">
          <button v-for="item in quickStarts" :key="item.title" @click="start(item.prompt)">
            <span class="quick-icon"><el-icon><component :is="item.icon" /></el-icon></span>
            <span><strong>{{ item.title }}</strong><small>{{ item.text }}</small></span>
            <el-icon class="arrow"><ArrowRight /></el-icon>
          </button>
        </div>
      </section>

      <section class="panel recent-panel">
        <div class="section-heading">
          <div><h2>最近咨询</h2><p>继续上次未说完的健康问题。</p></div>
          <router-link to="/app/history">查看全部</router-link>
        </div>
        <p v-if="consultations.loading" class="state">正在加载咨询记录…</p>
        <button v-else-if="consultations.error" class="retry" @click="consultations.load()">加载失败，点击重试</button>
        <div v-else-if="!consultations.items.length" class="empty">
          <span>✦</span><strong>还没有咨询记录</strong><p>发送第一条消息后，会自动保存在这里。</p>
        </div>
        <div v-else class="recent-list">
          <router-link v-for="item in consultations.items.slice(0, 4)" :key="item.id" :to="`/app/consultations/${item.id}`">
            <span><strong>{{ item.title }}</strong><small>{{ item.messageCount }} 条消息 · {{ new Date(item.updatedAt).toLocaleString('zh-CN') }}</small></span>
            <el-icon><ArrowRight /></el-icon>
          </router-link>
        </div>
      </section>
    </div>

    <section class="boundary">
      <span class="boundary-icon">+</span>
      <div><strong>使用前请了解</strong><p>本助手仅提供健康科普、可能原因梳理与就医分流，不作确诊，也不能替代医生面诊。出现严重或紧急症状时，请及时拨打 120 或前往急诊。</p></div>
    </section>
  </main>
</template>

<style scoped>
.dashboard { max-width: 1180px; margin: 0 auto; padding: 34px 42px 48px; color: #334d64; }
.hero { position: relative; display: flex; justify-content: space-between; min-height: 210px; padding: 38px 48px; overflow: hidden; border: 1px solid #dfeaf4; border-radius: 20px; background: linear-gradient(120deg, #f4f9fd 0%, #eaf4fc 62%, #e2f0fa 100%); }
.hero::after { content: ''; position: absolute; width: 270px; height: 270px; right: -74px; top: -112px; border-radius: 50%; border: 40px solid rgb(255 255 255 / 35%); }
.eyebrow { margin: 0 0 10px; color: #367cb5; font-size: 12px; letter-spacing: 2px; }
h1 { margin: 0; color: #24445f; font-size: 30px; font-weight: 650; }
.hero p:not(.eyebrow) { max-width: 610px; margin: 14px 0 25px; color: #688095; font-size: 14px; line-height: 1.9; }
.primary-action { display: inline-flex; align-items: center; gap: 12px; padding: 12px 20px; border: 0; border-radius: 10px; background: #237ac2; color: #fff; cursor: pointer; box-shadow: 0 7px 18px rgb(35 122 194 / 18%); }
.primary-action:hover { background: #176eaf; }
.hero-symbol { z-index: 1; display: grid; place-items: center; width: 126px; flex: 0 0 126px; }
.hero-symbol span { display: grid; place-items: center; width: 88px; height: 88px; border-radius: 24px; background: rgb(255 255 255 / 65%); color: #2a7fc3; font-size: 44px; box-shadow: 0 16px 38px rgb(53 111 158 / 12%); }
.summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 20px 0; }
.summary article { display: flex; align-items: center; gap: 15px; min-height: 88px; padding: 18px 22px; border: 1px solid #e6edf3; border-radius: 14px; background: #fff; }
.summary .el-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 11px; background: #eef6fc; color: #3b82bb; font-size: 19px; }
.summary div { display: flex; flex-direction: column; gap: 5px; }
.summary span { color: #8a9aaa; font-size: 12px; }
.summary strong { color: #344f66; font-size: 22px; font-weight: 650; }
.summary strong.date, .summary strong.safe { font-size: 14px; }
.summary strong.safe { color: #43836b; }
.content-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.panel { min-height: 330px; padding: 25px 26px; border: 1px solid #e6edf3; border-radius: 16px; background: #fff; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; }
.section-heading h2 { margin: 0; color: #344f66; font-size: 16px; font-weight: 650; }
.section-heading p { margin: 7px 0 0; color: #93a1ae; font-size: 11px; }
.section-heading a { color: #327bb7; font-size: 12px; text-decoration: none; }
.quick-list { display: grid; gap: 9px; }
.quick-list button { display: grid; grid-template-columns: 42px 1fr 18px; align-items: center; gap: 13px; width: 100%; padding: 14px; border: 1px solid transparent; border-radius: 11px; background: #f8fafc; color: inherit; text-align: left; cursor: pointer; }
.quick-list button:hover { border-color: #cfe0ee; background: #f3f8fc; }
.quick-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 10px; background: #eaf3fa; color: #357daf; }
.quick-list strong, .recent-list strong { display: block; color: #40596f; font-size: 13px; font-weight: 600; }
.quick-list small, .recent-list small { display: block; margin-top: 6px; color: #8c9ba9; font-size: 10px; line-height: 1.5; }
.arrow { color: #93a7b8; }
.recent-list { display: grid; }
.recent-list a { display: flex; align-items: center; justify-content: space-between; padding: 16px 4px; border-bottom: 1px solid #eef2f5; color: inherit; text-decoration: none; }
.recent-list a:hover strong { color: #237ac2; }
.state, .retry { margin: 35px 0; color: #8798a8; font-size: 12px; }
.retry { border: 0; background: none; color: #237ac2; cursor: pointer; }
.empty { display: flex; flex-direction: column; align-items: center; padding-top: 42px; color: #8798a8; text-align: center; }
.empty > span { color: #9abbd5; font-size: 27px; }
.empty strong { margin-top: 12px; color: #5f7487; font-size: 13px; }
.empty p { margin: 8px 0; font-size: 11px; }
.boundary { display: flex; gap: 16px; margin-top: 20px; padding: 18px 22px; border: 1px solid #e9edf1; border-radius: 14px; background: #fafbfc; }
.boundary-icon { display: grid; place-items: center; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 8px; background: #fceded; color: #c55656; font-size: 20px; }
.boundary strong { color: #52697d; font-size: 12px; }
.boundary p { margin: 5px 0 0; color: #8897a5; font-size: 11px; line-height: 1.75; }
button:focus-visible, a:focus-visible { outline: 2px solid #398ad0; outline-offset: 3px; }
</style>
