/**
 * 门户资讯的展示辅助：同题多期聚合、期号提取、来源状态中文与时间格式化。
 *
 * 纯函数、无副作用，便于单测。**只做展示整理，不改内容语义**：
 * 标题原样呈现（不翻译、不缩写），期号只从原文链接末段识别，识别不到就不显示。
 */
import type { NewsItem, NewsSourceStatus } from '../api/news'

export interface NewsGroup {
  /** 组内最新的一条（按发布时间，缺发布时间时按获取时间） */
  lead: NewsItem
  /** 同题的其他期次，较旧在后 */
  updates: NewsItem[]
  /** 组内各期的期号（识别得出才有），最新在前 */
  periods: string[]
}

const SOURCE_STATUS_TEXT: Record<NewsSourceStatus, string> = {
  ready: '正常',
  empty: '暂无新条目',
  stale: '内容较早',
  failed: '更新失败',
}

export function sourceStatusText(status: NewsSourceStatus): string {
  return SOURCE_STATUS_TEXT[status]
}

/** 标题归一化：只用于「是不是同一篇」的判断，不改显示文本。 */
export function normalizeTitle(title: string): string {
  return title.normalize('NFKC').replace(/\s+/g, ' ').trim().toLowerCase()
}

/**
 * 从原文链接末段识别期号。
 *
 * WHO 疾病暴发新闻形如 `…/item/2026-DON618`，显示成 `DON618（2026）`；
 * 其他来源只有看起来像编号的短 slug 才当编号，普通文章路径一律不显示，避免编造期号。
 */
export function periodLabel(item: NewsItem): string | null {
  const slug = item.canonicalUrl.split('?')[0].split('/').filter(Boolean).pop() ?? ''
  const whoLike = slug.match(/^(\d{4})-(DON\d+)$/i)
  if (whoLike) {
    return `${whoLike[2]!.toUpperCase()}（${whoLike[1]}）`
  }
  return /^[A-Za-z0-9._-]{4,24}$/.test(slug) && /\d/.test(slug) ? slug : null
}

function moment(item: NewsItem): number {
  const parsed = Date.parse(item.publishedAt ?? item.retrievedAt)
  return Number.isNaN(parsed) ? 0 : parsed
}

/**
 * 同题多期折成一组：标题相同即视为同一专题的不同期次。
 *
 * 依据实测（2026-10-04）：WHO 对同一疫情的多期更新标题逐字相同，只有期号与发布时间不同，
 * 直接平铺会让列表看起来全是重复条目。分组保持服务端返回的顺序，组内按时间从新到旧。
 */
export function groupNewsItems(items: NewsItem[]): NewsGroup[] {
  const buckets = new Map<string, NewsItem[]>()
  for (const item of items) {
    const key = normalizeTitle(item.title)
    const bucket = buckets.get(key)
    if (bucket) {
      bucket.push(item)
    } else {
      buckets.set(key, [item])
    }
  }

  const groups: NewsGroup[] = []
  for (const bucket of buckets.values()) {
    const sorted = [...bucket].sort((left, right) => moment(right) - moment(left))
    const lead = sorted.shift()
    if (!lead) {
      continue
    }
    groups.push({
      lead,
      updates: sorted,
      periods: [lead, ...sorted]
        .map(periodLabel)
        .filter((label): label is string => label !== null),
    })
  }
  return groups
}

/** 时间格式化：拿不到或解析不了就返回兜底文案（不编造时间）。 */
export function formatMoment(raw: string | null | undefined, fallback = ''): string {
  if (!raw) {
    return fallback
  }
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) {
    return fallback
  }
  return parsed.toLocaleString('zh-CN', { hour12: false })
}