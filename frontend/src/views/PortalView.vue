<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Basketball, FirstAidKit, Grid, Memo, Sunny } from '@element-plus/icons-vue'
import { ApiError, getApiErrorMessage } from '../api/http'
import {
  newsApi,
  type NewsCategory,
  type NewsItem,
  type NewsSourceStatusEntry,
  type NewsStatus,
} from '../api/news'
import { formatMoment, groupNewsItems, periodLabel, sourceStatusText } from './portalNews'

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
/** 最近成功快照时间、下次更新时间与来源级状态（后端契约；测试桩可不带后两项）。 */
const asOf = ref<string | null>(null)
const nextRefreshAt = ref<string | null>(null)
const sourceStatuses = ref<NewsSourceStatusEntry[]>([])
const sourceCoverageKnown = ref(false)
/** N3：当天首次访问触发的一轮自动刷新是否正在进行。 */
const refreshing = ref(false)
/** F-P1 分页：首屏一页 20 条（与后端默认一致），「加载更多」按 offset 追加。 */
const PAGE_SIZE = 20
const total = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)
const loadMoreError = ref('')
/** F-P4：手动重试。后端还没提供这个接口时自动退让，不留点了没用的按钮。 */
const retrying = ref(false)
const retryNote = ref('')
const retryUnsupported = ref(false)
/** 触发后按退避轮询等结果：4 次共约 15 秒，超时如实说没等到，不动已有内容。 */
const RETRY_POLL_DELAYS = [2000, 3000, 5000, 5000]
let latestRequest = 0

/** 同题多期折成一组：WHO 同一疫情的多期更新标题逐字相同，直接平铺会像重复条目。 */
const groups = computed(() => groupNewsItems(items.value))
const visibleSourceStatuses = computed(() => {
  if (active.value === 'all') return sourceStatuses.value
  return sourceStatuses.value.filter(entry =>
    !entry.categories || entry.categories.includes(active.value as Exclude<NewsCategory, 'all'>),
  )
})
const categoryHasSource = computed(() =>
  active.value === 'all' || sourceStatuses.value.some(entry => entry.categories?.includes(active.value as Exclude<NewsCategory, 'all'>)),
)
/** 只有「来源失败」或「整体过期」时才给重试；服务端没有这个接口时整块不显示。 */
const retryable = computed(() =>
  !retryUnsupported.value
  && (status.value === 'failed'
    || status.value === 'stale'
    || visibleSourceStatuses.value.some(entry => entry.status === 'failed' || entry.status === 'stale')),
)

const emptyReason = computed(() => {
  if (!items.value.length && sourceCoverageKnown.value && !categoryHasSource.value) return 'category_without_source'
  if (status.value === 'sources_not_connected') return 'sources_not_connected'
  if (status.value === 'stale') return 'stale'
  if (status.value === 'failed') return 'failed'
  return 'no_update'
})

/** 顶部状态说明：把「部分来源失败」「内容可能较旧」这类事实说清楚，不夸大也不隐藏。 */
const statusNote = computed(() => {
  if (sourceCoverageKnown.value && !categoryHasSource.value) return ''
  // 正在更新就说正在更新：不把「刚触发刷新」说成「已是最新」。
  if (refreshing.value) return '正在更新来源，稍后刷新可见新条目'
  if (status.value === 'ready' || status.value === 'partial') {
    const parts: string[] = []
    if (asOf.value) parts.push(`最近更新 ${formatMoment(asOf.value)}`)
    if (nextRefreshAt.value) parts.push(`下次更新 ${formatMoment(nextRefreshAt.value)}`)
    if (status.value === 'partial') parts.push('部分来源暂时不可用，下面是最近成功的条目')
    return parts.join(' · ')
  }
  if (status.value === 'stale') return '最近一次成功更新较早，下面的内容可能已过期'
  if (status.value === 'failed') return '来源更新失败，下面是最近一次成功的内容'
  return ''
})

async function load(category: NewsCategory = active.value, options: { silent?: boolean } = {}) {
  const request = ++latestRequest
  const silent = options.silent ?? false
  active.value = category
  // silent：重试后轮询时静默刷新，不把列表切成「正在读取资讯…」。
  if (!silent) loading.value = true
  error.value = ''
  loadMoreError.value = ''
  try {
    const page = await newsApi.page(category, { limit: PAGE_SIZE, offset: 0 })
    if (request !== latestRequest) return
    status.value = page.status
    items.value = page.items
    tips.value = page.tips
    asOf.value = page.asOf ?? null
    nextRefreshAt.value = page.nextRefreshAt ?? null
    sourceStatuses.value = page.sourceStatuses ?? []
    sourceCoverageKnown.value = !!page.sourceStatuses?.length && page.sourceStatuses.every(entry => Array.isArray(entry.categories))
    refreshing.value = page.refreshing ?? false
    total.value = page.total ?? page.items.length
    hasMore.value = page.hasMore ?? (page.items.length < total.value)
  } catch (e) {
    if (request !== latestRequest) return
    // 失败时清空列表：上一个分类的条目留着会被当成当前分类的资讯。
    status.value = ''
    items.value = []
    tips.value = []
    asOf.value = null
    nextRefreshAt.value = null
    sourceStatuses.value = []
    sourceCoverageKnown.value = false
    refreshing.value = false
    total.value = 0
    hasMore.value = false
    error.value = getApiErrorMessage(e)
  } finally {
    if (request === latestRequest && !silent) loading.value = false
  }
}

/** F-P1：追加下一页。按 id 去重（翻页期间插入新条目会错位），失败保留已加载条目。 */
async function loadMore() {
  if (loadingMore.value || !hasMore.value) return
  const request = latestRequest
  loadingMore.value = true
  loadMoreError.value = ''
  try {
    const page = await newsApi.page(active.value, { limit: PAGE_SIZE, offset: items.value.length })
    if (request !== latestRequest) return
    const seen = new Set(items.value.map(item => item.id))
    items.value = [...items.value, ...page.items.filter(item => !seen.has(item.id))]
    total.value = page.total ?? total.value
    hasMore.value = page.hasMore ?? (items.value.length < total.value)
  } catch (e) {
    if (request !== latestRequest) return
    // 加载更多失败只提示这一次没取到，已展示的条目不动。
    loadMoreError.value = getApiErrorMessage(e)
  } finally {
    if (request === latestRequest) loadingMore.value = false
  }
}

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * F-P4：手动重试一轮抓取。接口不等待抓取完成：POST 立即返回，
 * 再由前端按退避轮询到「最近成功快照时间前进」为止；超时就如实说没等到。
 */
async function retryRefresh() {
  if (retrying.value) return
  const before = asOf.value
  retrying.value = true
  retryNote.value = ''
  try {
    const result = await newsApi.requestRefresh()
    if (!result.accepted) {
      retryNote.value = result.reason === 'already_ran_today'
        ? '今天这一轮已经更新过，等下次自动更新即可'
        : result.reason === 'busy'
          ? '更新正在进行，稍后刷新可见新条目'
          : '服务端当前没有开启在线更新'
      return
    }
    retryNote.value = '已开始更新，正在等结果…'
    for (const delay of RETRY_POLL_DELAYS) {
      await sleep(delay)
      await load(active.value, { silent: true })
      if (asOf.value && asOf.value !== before) {
        retryNote.value = '更新完成，下面是本轮的最近成功内容'
        return
      }
    }
    retryNote.value = '这次没等到新结果，可以稍后再试；已有内容不受影响'
  } catch (e) {
    // 后端还没提供这个接口时不要留死按钮：收起按钮，改说明「下次自动更新」。
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
      retryUnsupported.value = true
      retryNote.value = '服务端暂未开放手动重试，将在下次自动更新时重试'
    } else {
      retryNote.value = getApiErrorMessage(e)
    }
  } finally {
    retrying.value = false
  }
}

function start() {
  void router.push({ path: '/app/chat' })
}

/** 时间一律走这里：解析不了就给兜底文案，绝不编造时间。 */
function formatTime(value: string | null, fallback = '发布时间未核实') {
  return formatMoment(value, fallback)
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

        <p v-if="statusNote" class="status-line" role="status">{{ statusNote }}</p>
        <ul v-if="!loading && visibleSourceStatuses.length" class="source-status" aria-label="来源状态">
          <li v-for="entry in visibleSourceStatuses" :key="entry.id">
            <span class="dot" :class="`dot--${entry.status}`" aria-hidden="true"></span>
            {{ entry.name }}：{{ sourceStatusText(entry.status) }}
            <span class="muted">最后成功 {{ entry.lastSuccessAt ? formatTime(entry.lastSuccessAt, '时间未记录') : '无成功记录' }}</span>
            <span v-if="entry.lastErrorCode" class="muted">（{{ entry.lastErrorCode }}）</span>
          </li>
        </ul>

        <p v-if="retryable || retrying || retryNote" class="retry-line" role="status">
          <button
            v-if="retryable && !retrying"
            type="button"
            class="retry"
            @click="retryRefresh()"
          >
            重试更新
          </button>
          <span v-if="retrying">正在等待更新结果…</span>
          <span v-if="retryNote" class="muted">{{ retryNote }}</span>
        </p>

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
        <div v-else-if="emptyReason === 'failed'" class="empty">
          <strong>来源更新失败</strong>
          <p>最近一次抓取没有成功，这里不展示未核实的旧内容冒充更新；来源恢复后会重新出现条目。</p>
        </div>
        <div v-else-if="emptyReason === 'category_without_source'" class="empty">
          <strong>该分区尚无新闻来源</strong>
          <p>目前没有已接入此分区的来源；这不代表今天没有相关新闻。接入来源后才会显示真实条目。</p>
        </div>
        <div v-else-if="!items.length" class="empty">
          <strong>暂时没有更新</strong>
          <p v-if="sourceCoverageKnown">已接入的来源目前没有可显示条目；不代表今天没有相关新闻。</p>
          <p v-else>当前没有可显示条目；来源覆盖情况尚未核实，不能判断是未接入还是暂无更新。</p>
        </div>
        <ul v-else class="cards">
          <li v-for="group in groups" :key="group.lead.id">
            <div class="card-head">
              <a
                class="card-title"
                :href="group.lead.canonicalUrl"
                target="_blank"
                rel="noopener noreferrer nofollow"
              >
                <strong>{{ group.lead.titleZh?.trim() || group.lead.title }}</strong>
              </a>
              <span v-if="group.lead.titleZh?.trim() && group.lead.titleZhSource === 'manual'" class="badge badge--translation">人工核对译题</span>
              <span v-else-if="group.lead.titleZh?.trim() && group.lead.titleZhSource === 'machine'" class="badge badge--translation">机器翻译·未经医学审核</span>
              <span v-if="!group.lead.medicalReviewed" class="badge">未经医学审核</span>
            </div>
            <p v-if="group.lead.titleZh?.trim()" class="card-original">原题：{{ group.lead.title }}</p>
            <p v-if="group.lead.summary" class="card-summary">{{ group.lead.summary }}</p>
            <p v-if="group.periods.length > 1" class="card-updates">
              同题更新 {{ group.periods.length }} 期：{{ group.periods.join(' · ') }}
            </p>
            <p class="card-meta">
              {{ group.lead.sourceName }} · 发布 {{ formatTime(group.lead.publishedAt) }} · 获取
              {{ formatTime(group.lead.retrievedAt, '获取时间未记录') }}
            </p>
            <a :href="group.lead.canonicalUrl" target="_blank" rel="noopener noreferrer nofollow">
              前往来源核对
            </a>
            <details v-if="group.updates.length" class="card-more">
              <summary>另有 {{ group.updates.length }} 期较早更新</summary>
              <ul>
                <li v-for="update in group.updates" :key="update.id">
                  <a :href="update.canonicalUrl" target="_blank" rel="noopener noreferrer nofollow">
                    {{ periodLabel(update) ?? '原文' }}
                  </a>
                  <span class="muted">发布 {{ formatTime(update.publishedAt) }}</span>
                </li>
              </ul>
            </details>
          </li>
        </ul>

        <div v-if="items.length" class="load-more">
          <button v-if="hasMore" type="button" :disabled="loadingMore" @click="loadMore()">
            {{ loadingMore ? '正在加载…' : `加载更多（已显示 ${items.length} / ${total} 条）` }}
          </button>
          <p v-else class="muted">已显示全部 {{ total }} 条</p>
          <p v-if="loadMoreError" class="state state--error" role="status">
            {{ loadMoreError }} <button class="retry" @click="loadMore()">重试</button>
          </p>
        </div>
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
.badge--translation { background: #eaf4fc; color: #36749e; }
/* 标题本身就是原文链接：用户第一反应是点标题，不能只有右下角小字可点。 */
.card-title { color: inherit; text-decoration: none; }
.card-title:hover strong, .card-title:focus-visible strong { color: #2f6f9f; text-decoration: underline; }
.card-summary { margin: 7px 0 0; color: #7d8fa0; font-size: 12px; line-height: 1.8; }
.card-original { margin: 7px 0 0; color: #71879b; font-size: 11px; line-height: 1.7; overflow-wrap: anywhere; }
/* F2：状态说明、来源级状态、同题多期标注 */
.status-line { margin: 12px 0 0; color: #5b748c; font-size: 12px; line-height: 1.7; }
.source-status { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 8px 0 0; padding: 0; list-style: none; color: #71879b; font-size: 11px; }
.source-status li { display: flex; align-items: center; gap: 6px; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: #b6c4d1; }
.dot--ready { background: #4fae7a; }
.dot--empty { background: #c9b471; }
.dot--stale { background: #d59b52; }
.dot--failed { background: #d1726f; }
.card-updates { margin: 7px 0 0; color: #4a7ba6; font-size: 12px; }
.card-more { margin-top: 8px; color: #6b8195; font-size: 12px; }
.card-more summary { cursor: pointer; }
.card-more ul { display: flex; flex-direction: column; gap: 5px; margin: 8px 0 0; padding-left: 16px; }
.card-more li { display: flex; gap: 8px; align-items: baseline; }
.card-meta { margin: 7px 0 0; color: #98a7b4; font-size: 10px; }
.cards a { display: inline-block; margin-top: 7px; color: #367fae; font-size: 11px; text-decoration: none; }
.cards a:hover { text-decoration: underline; }
/* F-P1：加载更多按钮随内容流放在列表下方（入口位置经用户 2026-10-05 确认）。 */
.load-more { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 14px 0 2px; }
.load-more button { padding: 8px 18px; border: 1px solid #bcd8ee; border-radius: 10px; background: #f4f9fd; color: #2f6f9f; font-size: 12px; cursor: pointer; }
.load-more button:hover:enabled { background: #e7f3fc; }
.load-more button:disabled { color: #9aa9b6; cursor: default; }
.load-more .muted { margin: 0; }
/* F-P4：重试入口紧跟来源状态（入口位置经用户 2026-10-05 确认）。 */
.retry-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 8px 0 0; font-size: 11px; }
.retry-line .retry { padding: 4px 12px; border: 1px solid #bcd8ee; border-radius: 999px; background: #f4f9fd; }
.retry-line .muted { margin: 0; }
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
