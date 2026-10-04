<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Basketball, FirstAidKit, Grid, Memo, Sunny } from '@element-plus/icons-vue'
import { getApiErrorMessage } from '../api/http'
import { newsApi, type NewsCategory, type NewsItem, type NewsStatus } from '../api/news'

/**
 * 独立资讯门户（F1：只有页面框架，真实新闻源最后接入）。
 *
 * 内容从工作区首页原型迁移而来（见 `COORDINATION.md` §7.2）：
 * 工作区 `/app` 已恢复原概览，门户不再显示侧栏。
 */
const router = useRouter()

/** 五个分区做成平铺大卡片（用户 2026-10-04：四块放大的同时「把全部也保留」）。 */
const categories: { value: NewsCategory; label: string; icon: unknown; text: string }[] = [
  { value: 'all', label: '全部', icon: Grid, text: '所有分区的资讯总览' },
  { value: 'wellness', label: '养生', icon: Sunny, text: '作息、饮食与日常调理' },
  { value: 'fitness', label: '健身', icon: Basketball, text: '运动方式与安全注意' },
  { value: 'disease', label: '疾病', icon: FirstAidKit, text: '常见疾病科普与就医方向' },
  { value: 'medication', label: '药物', icon: Memo, text: '药品用途与注意事项' },
]

const active = ref<NewsCategory>('all')
/** 列表标题：当前分区名；选「全部」时不强调某个分区。 */
const activeLabel = computed(
  () => categories.find(item => item.value === active.value)?.label ?? '全部资讯',
)
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
      <div class="hero-bg" aria-hidden="true">
        <span class="orb orb--1"></span>
        <span class="orb orb--2"></span>
        <span class="grid"></span>
      </div>
      <div class="hero-copy">
        <p class="eyebrow">健康资讯</p>
        <h1>病理诊断科普助手</h1>
        <ul class="chips">
          <li>健康科普</li>
          <li>医学资料辅助解释</li>
          <li>就医方向梳理</li>
        </ul>
        <p class="capability">不作确诊、不开处方，也不能替代医生面诊。</p>
        <div class="hero-actions">
          <button class="primary" @click="start()">与 AI 对话 <el-icon><ArrowRight /></el-icon></button>
          <!-- 仓库目前没有可验证的 Windows 安装包：宁可明确说没有，也不跳假链接。 -->
          <button class="ghost" disabled aria-disabled="true" title="暂未提供安装包">下载 Windows 版（暂未提供）</button>
        </div>
      </div>
      <div class="hero-art" aria-hidden="true">
        <span class="ring"></span>
        <span class="star">✦</span>
      </div>
    </section>

    <section class="categories" role="tablist" aria-label="资讯分类">
      <button
        v-for="item in categories"
        :key="item.value"
        class="category-tile"
        role="tab"
        :aria-selected="active === item.value"
        :class="{ selected: active === item.value }"
        @click="load(item.value)"
      >
        <span class="tile-icon" aria-hidden="true"><el-icon><component :is="item.icon" /></el-icon></span>
        <strong>{{ item.label }}</strong>
        <small>{{ item.text }}</small>
      </button>
    </section>

    <div class="columns">
      <section class="news">
        <div class="panel-head">
          <h2>{{ activeLabel }}</h2>
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
/* AI 展示区：约占桌面首屏一半（min-height: 50vh），动效全部是纯 CSS 装饰，
   放在 overflow: hidden 的容器里，不会制造横向溢出；降低动态效果偏好下会静止。 */
.hero { position: relative; display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 50vh; padding: clamp(24px, 4vw, 40px) clamp(20px, 4vw, 44px); overflow: hidden; border: 1px solid #dfeaf4; border-radius: 20px; background: linear-gradient(120deg, #f4f9fd 0%, #eaf4fc 40%, #e6f2fb 60%, #f6fbff 100%); background-size: 220% 220%; animation: heroShift 24s ease-in-out infinite alternate; }
.hero-bg { position: absolute; inset: 0; z-index: 0; }
.orb { position: absolute; border-radius: 50%; filter: blur(2px); opacity: .55; }
.orb--1 { width: clamp(180px, 24vw, 300px); height: clamp(180px, 24vw, 300px); right: -60px; top: -90px; background: radial-gradient(circle at 30% 30%, rgb(255 255 255 / 85%), rgb(180 214 240 / 35%)); animation: floatY 9s ease-in-out infinite; }
.orb--2 { width: clamp(120px, 16vw, 200px); height: clamp(120px, 16vw, 200px); right: 22%; bottom: -80px; background: radial-gradient(circle at 40% 40%, rgb(214 236 250 / 75%), rgb(160 205 236 / 25%)); animation: floatY 12s ease-in-out infinite reverse; }
.grid { position: absolute; inset: 0; background-image: linear-gradient(rgb(90 150 200 / 7%) 1px, transparent 1px), linear-gradient(90deg, rgb(90 150 200 / 7%) 1px, transparent 1px); background-size: 34px 34px; mask-image: radial-gradient(circle at 25% 40%, #000 0%, transparent 72%); }
.eyebrow { margin: 0 0 10px; color: #367cb5; font-size: 12px; letter-spacing: 2px; }
h1 { margin: 0; color: #24445f; font-size: clamp(24px, 3.4vw, 34px); font-weight: 650; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 0; padding: 0; list-style: none; }
.chips li { padding: 5px 12px; border: 1px solid rgb(140 190 228 / 55%); border-radius: 999px; background: rgb(255 255 255 / 62%); color: #33729f; font-size: 12px; }
.capability { max-width: 620px; margin: 14px 0 22px; color: #688095; font-size: 14px; line-height: 1.9; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 12px; }
.primary, .ghost { display: inline-flex; align-items: center; gap: 9px; padding: 11px 19px; border-radius: 10px; font-size: 13px; cursor: pointer; }
.primary { border: 0; background: #237ac2; color: #fff; box-shadow: 0 7px 18px rgb(35 122 194 / 18%); }
.primary:hover { background: #176eaf; }
.ghost { border: 1px dashed #b9cbdb; background: rgb(255 255 255 / 72%); color: #7d8fa0; cursor: not-allowed; }
.hero-copy { position: relative; z-index: 2; display: flex; flex-direction: column; justify-content: center; }
.hero-art { position: relative; z-index: 2; display: grid; place-items: center; flex: 0 0 148px; height: 148px; }
.ring { position: absolute; inset: 0; border-radius: 50%; border: 2px dashed rgb(120 180 224 / 65%); animation: spin 26s linear infinite; }
.star { display: grid; place-items: center; width: 92px; height: 92px; border-radius: 26px; background: rgb(255 255 255 / 72%); color: #2a7fc3; font-size: 44px; box-shadow: 0 12px 30px rgb(58 128 186 / 16%); animation: pulse 5.5s ease-in-out infinite; }
@keyframes heroShift { from { background-position: 0% 50%; } to { background-position: 100% 50%; } }
@keyframes floatY { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-16px); } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.06); } }
.columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 340px); gap: 18px; flex: 1; min-height: 0; margin-top: 18px; }
.news, .rail-card { border: 1px solid #e6edf3; border-radius: 16px; background: #fff; }
.news { display: flex; flex-direction: column; padding: 22px 26px 26px; }
/* 五个分区：平铺在 AI 展示区下方；桌面一行铺满，窄屏 3 列 / 2 列 / 单列。 */
.categories { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin-top: 18px; }
.category-tile { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding: 18px 18px 16px; border: 1px solid #e2eaf1; border-radius: 16px; background: #fff; color: inherit; text-align: left; cursor: pointer; transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease; }
.category-tile:hover { transform: translateY(-3px); border-color: #bcd8ee; box-shadow: 0 12px 24px rgb(52 116 168 / 12%); }
.category-tile.selected { border-color: #7fb6de; background: linear-gradient(150deg, #f2f9ff, #e7f3fc); box-shadow: 0 10px 22px rgb(52 116 168 / 14%); }
.tile-icon { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 13px; background: #eaf4fc; color: #2f7cb4; font-size: 20px; }
.category-tile strong { color: #35536c; font-size: 15px; }
.category-tile small { color: #8b9aa8; font-size: 11px; line-height: 1.6; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-bottom: 14px; border-bottom: 1px solid #eef2f5; }
.panel-head h2 { margin: 0; color: #3d566d; font-size: 15px; }
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
@media (max-width: 1180px) {
  .categories { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .hero { flex-direction: column; align-items: flex-start; min-height: 46vh; }
  .hero-art { display: none; }
  .categories { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .columns { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 480px) {
  .hero { min-height: auto; }
  .hero-actions { flex-direction: column; align-items: stretch; }
  .primary, .ghost { justify-content: center; }
  .categories { grid-template-columns: minmax(0, 1fr); }
}
/* 用户可能有「降低动态效果」偏好：装饰动画全部静止，内容照常显示。 */
@media (prefers-reduced-motion: reduce) {
  .hero, .orb, .ring, .star { animation: none; }
}
</style>