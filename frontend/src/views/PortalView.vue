<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import { getApiErrorMessage } from '../api/http'
import { newsApi, type NewsCategory, type NewsItem, type NewsStatus } from '../api/news'

/**
 * 独立资讯门户（F1：只有页面框架，真实新闻源最后接入）。
 *
 * 内容从工作区首页原型迁移而来（见 `COORDINATION.md` §7.2）：
 * 工作区 `/app` 已恢复原概览，门户不再显示侧栏。
 */
const router = useRouter()

const categories: { value: NewsCategory; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'wellness', label: '养生' },
  { value: 'fitness', label: '健身' },
  { value: 'disease', label: '疾病' },
  { value: 'medication', label: '药物' },
]

const active = ref<NewsCategory>('all')
const loading = ref(false)
const error = ref('')
const status = ref<NewsStatus | ''>('')
const items = ref<NewsItem[]>([])
const tips = ref<{ id: string; text: string; sourceName: string; canonicalUrl: string }[]>([])

const emptyReason = computed(() => {
  if (status.value === 'sources_not_connected') return 'sources_not_connected'
  if (status.value === 'stale') return 'stale'
  return 'no_update'
})

async function load(category: NewsCategory = active.value) {
  active.value = category
  loading.value = true
  error.value = ''
  try {
    const page = await newsApi.page(category)
    status.value = page.status
    items.value = page.items
    tips.value = page.tips
  } catch (e) {
    // 失败时清空列表：上一个分类的条目留着会被当成当前分类的资讯。
    status.value = ''
    items.value = []
    tips.value = []
    error.value = getApiErrorMessage(e)
  } finally {
    loading.value = false
  }
}

function start() {
  void router.push({ path: '/app/chat' })
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '发布时间未核实'
}

onMounted(() => void load())
</script>

<template>
  <main class="portal-home">
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">健康资讯</p>
        <h1>病理诊断科普助手</h1>
        <p class="capability">
          健康科普、医学资料辅助解释与就医方向梳理。不作确诊、不开处方，也不能替代医生面诊。
        </p>
        <div class="hero-actions">
          <button class="primary" @click="start()">与 AI 对话 <el-icon><ArrowRight /></el-icon></button>
          <!-- 仓库目前没有可验证的 Windows 安装包：宁可明确说没有，也不跳假链接。 -->
          <button class="ghost" disabled aria-disabled="true" title="暂未提供安装包">下载 Windows 版（暂未提供）</button>
        </div>
      </div>
      <div class="hero-art" aria-hidden="true"><span>✦</span></div>
    </section>

    <div class="columns">
      <section class="news">
        <div class="tabs" role="tablist" aria-label="资讯分类">
          <button
            v-for="item in categories"
            :key="item.value"
            role="tab"
            :aria-selected="active === item.value"
            :class="{ selected: active === item.value }"
            @click="load(item.value)"
          >{{ item.label }}</button>
        </div>

        <p v-if="loading" class="state" role="status">正在读取资讯…</p>
        <p v-else-if="error" class="state state--error" role="status">
          {{ error }} <button class="retry" @click="load()">重试</button>
        </p>
        <div v-else-if="emptyReason === 'sources_not_connected'" class="empty">
          <strong>新闻源尚未接入</strong>
          <p>
            这一版只搭好了资讯位置：目前没有接入任何新闻来源，所以这里不会显示任何条目，
            也不会用示例内容冒充每日新闻。接入真实来源后，这里会显示标题、来源机构、原文链接、
            发布时间与获取时间，并标注未经医学审核。
          </p>
        </div>
        <div v-else-if="emptyReason === 'stale'" class="empty">
          <strong>暂时取不到较新的资讯</strong>
          <p>已接入的来源暂时没有返回新内容，这里不展示旧条目冒充更新。</p>
        </div>
        <div v-else-if="!items.length" class="empty">
          <strong>暂时没有更新</strong>
          <p>已接入的来源今天还没有新条目；没有条目时不会写成「今日已更新」。</p>
        </div>
        <ul v-else class="cards">
          <li v-for="item in items" :key="item.id">
            <div class="card-head">
              <strong>{{ item.title }}</strong>
              <span v-if="!item.medicalReviewed" class="badge">未经医学审核</span>
            </div>
            <p class="card-summary">{{ item.summary }}</p>
            <p class="card-meta">
              {{ item.sourceName }} · 发布 {{ formatTime(item.publishedAt) }} · 获取 {{ formatTime(item.retrievedAt) }}
            </p>
            <a :href="item.canonicalUrl" target="_blank" rel="noopener noreferrer nofollow">前往来源核对</a>
          </li>
        </ul>
      </section>

      <aside class="rail">
        <section class="rail-card">
          <h2>小贴士</h2>
          <p v-if="!tips.length" class="muted">小贴士尚未接入来源，这里不展示占位内容。</p>
          <ul v-else class="tip-list">
            <li v-for="tip in tips" :key="tip.id">
              <p>{{ tip.text }}</p>
              <a :href="tip.canonicalUrl" target="_blank" rel="noopener noreferrer nofollow">{{ tip.sourceName }}</a>
            </li>
          </ul>
        </section>
      </aside>
    </div>

    <section class="boundary">
      <span class="boundary-icon" aria-hidden="true">+</span>
      <div>
        <strong>使用前请了解</strong>
        <p>本门户仅提供健康科普、可能原因梳理与就医分流，不作确诊，也不能替代医生面诊。出现严重或紧急症状时，请及时拨打 120 或前往急诊。资讯内容未经医学审核，仅作线索，不能作为诊断或用药依据。</p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.portal-home { display: flex; flex: 1; flex-direction: column; width: 100%; padding: 18px clamp(14px, 2.5vw, 36px) 30px; }
.hero { position: relative; display: flex; justify-content: space-between; gap: 24px; padding: clamp(24px, 4vw, 34px) clamp(20px, 4vw, 44px); overflow: hidden; border: 1px solid #dfeaf4; border-radius: 20px; background: linear-gradient(120deg, #f4f9fd 0%, #eaf4fc 62%, #e2f0fa 100%); }
.hero::after { content: ''; position: absolute; width: 260px; height: 260px; right: -70px; top: -108px; border-radius: 50%; border: 38px solid rgb(255 255 255 / 35%); }
.eyebrow { margin: 0 0 10px; color: #367cb5; font-size: 12px; letter-spacing: 2px; }
h1 { margin: 0; color: #24445f; font-size: clamp(22px, 3vw, 28px); font-weight: 650; }
.capability { max-width: 620px; margin: 14px 0 22px; color: #688095; font-size: 14px; line-height: 1.9; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 12px; }
.primary, .ghost { display: inline-flex; align-items: center; gap: 9px; padding: 11px 19px; border-radius: 10px; font-size: 13px; cursor: pointer; }
.primary { border: 0; background: #237ac2; color: #fff; box-shadow: 0 7px 18px rgb(35 122 194 / 18%); }
.primary:hover { background: #176eaf; }
.ghost { border: 1px dashed #b9cbdb; background: rgb(255 255 255 / 72%); color: #7d8fa0; cursor: not-allowed; }
.hero-art { z-index: 1; display: grid; place-items: center; flex: 0 0 126px; }
.hero-art span { display: grid; place-items: center; width: 88px; height: 88px; border-radius: 24px; background: rgb(255 255 255 / 65%); color: #2a7fc3; font-size: 42px; }
.columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 340px); gap: 18px; flex: 1; min-height: 0; margin-top: 18px; }
.news, .rail-card { border: 1px solid #e6edf3; border-radius: 16px; background: #fff; }
.news { display: flex; flex-direction: column; padding: 22px 26px 26px; }
.tabs { display: flex; flex-wrap: wrap; gap: 8px; padding-bottom: 16px; border-bottom: 1px solid #eef2f5; }
.tabs button { padding: 7px 15px; border: 1px solid #dde7f0; border-radius: 999px; background: #f8fafc; color: #5b748c; font-size: 12px; cursor: pointer; }
.tabs button.selected { border-color: #9ec8e6; background: #eaf4fc; color: #1e6ba8; font-weight: 600; }
.state { flex: 1; margin: 28px 0; color: #8798a8; font-size: 12px; }
.state--error { color: #b0653c; }
.retry { border: 0; background: none; color: #237ac2; font-size: 12px; cursor: pointer; }
.empty { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: center; padding: 40px 18px; color: #8798a8; text-align: center; }
.empty strong { color: #5f7487; font-size: 14px; }
.empty p { max-width: 560px; margin: 10px 0 0; font-size: 12px; line-height: 1.85; }
.cards { display: grid; gap: 4px; margin: 0; padding: 6px 0 0; list-style: none; }
.cards li { padding: 15px 2px; }
.cards li + li { border-top: 1px solid #eef2f5; }
.card-head { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 8px; }
.card-head strong { color: #3d566d; font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.badge { padding: 1px 7px; border-radius: 999px; background: #fff3dc; color: #9a681c; font-size: 9px; line-height: 1.7; }
.card-summary { margin: 7px 0 0; color: #7d8fa0; font-size: 12px; line-height: 1.8; }
.card-meta { margin: 7px 0 0; color: #98a7b4; font-size: 10px; }
.cards a { display: inline-block; margin-top: 7px; color: #367fae; font-size: 11px; text-decoration: none; }
.cards a:hover { text-decoration: underline; }
.rail { display: grid; gap: 16px; align-content: start; }
.rail-card { padding: 18px 18px 20px; }
.rail-card h2 { margin: 0 0 12px; color: #3d566d; font-size: 14px; font-weight: 650; }
.muted { margin: 0; color: #98a7b4; font-size: 11px; line-height: 1.8; }
.tip-list { display: grid; gap: 12px; margin: 0; padding: 0; list-style: none; }
.tip-list p { margin: 0 0 5px; color: #7d8fa0; font-size: 11px; line-height: 1.8; }
.tip-list a { color: #367fae; font-size: 10px; text-decoration: none; }
.boundary { display: flex; gap: 16px; margin-top: 20px; padding: 18px 22px; border: 1px solid #e9edf1; border-radius: 14px; background: #fff; }
.boundary-icon { display: grid; place-items: center; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 8px; background: #fceded; color: #c55656; font-size: 20px; }
.boundary strong { color: #52697d; font-size: 12px; }
.boundary p { margin: 5px 0 0; color: #8897a5; font-size: 11px; line-height: 1.75; }
button:focus-visible, a:focus-visible { outline: 2px solid #398ad0; outline-offset: 3px; }

/* 独立门户不受 ADR-011 约束：窄屏改纵向排列，不留横向滚动。 */
@media (max-width: 900px) {
  .hero { flex-direction: column; }
  .hero-art { display: none; }
  .columns { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 480px) {
  .hero-actions { flex-direction: column; align-items: stretch; }
  .primary, .ghost { justify-content: center; }
  .tabs button { flex: 1 1 auto; }
}
</style>