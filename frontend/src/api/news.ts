import http from './http'

export type NewsCategory = 'all' | 'wellness' | 'fitness' | 'disease' | 'medication'
export type NewsItemCategory = Exclude<NewsCategory, 'all'>

/**
 * 后端契约（`backend/app/schemas/news.py`）：未接入新闻源时只返回
 * `status: "sources_not_connected"` 与空 `items`/`tips`，前端不得据此编造条目。
 * 未来 `status` 可能扩展为 ready / partial / stale / failed。
 */
export type NewsStatus = 'sources_not_connected' | 'ready' | 'partial' | 'stale' | 'failed'

export interface NewsItem {
  id: string
  category: NewsItemCategory
  title: string
  summary: string
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

export interface NewsPage {
  category: NewsCategory
  status: NewsStatus
  asOf: string | null
  items: NewsItem[]
  tips: NewsTip[]
}

export const newsApi = {
  async page(category: NewsCategory = 'all') {
    return (await http.get<NewsPage>('/news', { params: { category } })).data
  },
}