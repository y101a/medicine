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

export const newsApi = {
  async page(category: NewsCategory = 'all') {
    return (await http.get<NewsPage>('/news', { params: { category } })).data
  },
}
