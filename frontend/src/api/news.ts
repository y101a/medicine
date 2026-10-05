import http from './http'

export type NewsCategory = 'all' | 'wellness' | 'fitness' | 'disease' | 'medication'
export type NewsItemCategory = Exclude<NewsCategory, 'all'>

/**
 * 后端契约（`backend/app/schemas/news.py`）：未接入新闻源时只返回
 * `status: "sources_not_connected"` 与空 `items`/`tips`，前端不得据此编造条目。
 * N1 数据层已实现 ready / partial / stale / empty / failed 与来源级状态。
 */
export type NewsStatus =
  | 'sources_not_connected'
  | 'ready'
  | 'partial'
  | 'stale'
  | 'empty'
  | 'failed'

export type NewsSourceStatus = 'ready' | 'empty' | 'stale' | 'failed'

export interface NewsItem {
  id: string
  category: NewsItemCategory
  title: string
  /** 可选译题；原题始终保留在 title。 */
  titleZh?: string | null
  titleZhSource?: 'manual' | 'machine' | null
  /** 写不出可靠摘要时为 null：只显示标题、来源与链接，不编造内容。 */
  summary: string | null
  sourceName: string
  canonicalUrl: string
  /** 无法核实发布时间时为 null，不得用抓取时间冒充。 */
  publishedAt: string | null
  retrievedAt: string
  medicalReviewed: boolean
}

export interface NewsTip {
  id: string
  category: NewsItemCategory
  text: string
  sourceName: string
  canonicalUrl: string
}

export interface NewsSourceStatusEntry {
  id: string
  name: string
  /** 新版接口返回来源覆盖的分区；可选以兼容旧接口桩。 */
  categories?: NewsItemCategory[]
  status: NewsSourceStatus
  lastSuccessAt: string | null
  lastErrorCode: string | null
}

export interface NewsPage {
  category: NewsCategory
  status: NewsStatus
  /** 最近成功快照时间，不是接口调用时间。 */
  asOf: string | null
  items: NewsItem[]
  tips: NewsTip[]
  /** 以下字段后端已返回；测试桩可以不带，所以是可选的。 */
  nextRefreshAt?: string | null
  sourceStatuses?: NewsSourceStatusEntry[]
  total?: number
  hasMore?: boolean
  /** N3：当天首次访问触发的一轮自动刷新正在进行（接口不等待它完成）。 */
  refreshing?: boolean
}

/** F-P4：手动重试的结果（契约草案见 `COORDINATION.md` §6）。 */
export type NewsRefreshReason = 'started' | 'already_ran_today' | 'busy' | 'disabled'

export interface NewsRefreshResult {
  /** false 表示这一轮并没有真的开始（例如今天已经跑过、或功能未开启）。 */
  accepted: boolean
  reason: NewsRefreshReason
  nextRefreshAt: string | null
}

export const newsApi = {
  /**
   * 分页读取：接口 `limit` 上限 50、`offset` 上限 10000，默认 20/0 与后端一致。
   * 追加式加载由调用方传 `offset`，并按 `id` 去重（翻页期间若有新条目插入会错位）。
   */
  async page(
    category: NewsCategory = 'all',
    options: { limit?: number; offset?: number } = {},
  ) {
    return (
      await http.get<NewsPage>('/news', {
        params: { category, limit: options.limit, offset: options.offset },
      })
    ).data
  },
  /**
   * 手动触发一轮抓取（F-P4）。后端契约（`COORDINATION.md` §6）：**不等待抓取完成**，立即返回；
   * 同一更新日已跑过时 `accepted=false` + `reason=already_ran_today`，不伪造新一轮。
   */
  async requestRefresh() {
    return (await http.post<NewsRefreshResult>('/news/refresh')).data
  },
}
