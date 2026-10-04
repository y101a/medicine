import { describe, expect, it } from 'vitest'

import type { NewsItem } from '../api/news'
import {
  formatMoment,
  groupNewsItems,
  periodLabel,
  sourceStatusText,
} from './portalNews'

function item(overrides: Partial<NewsItem> & { id: string }): NewsItem {
  return {
    category: 'disease',
    title: 'Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo',
    summary: null,
    sourceName: 'WHO 疾病暴发新闻',
    canonicalUrl: 'https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON618',
    publishedAt: '2026-09-25T15:16:26Z',
    retrievedAt: '2026-10-04T16:04:47Z',
    medicalReviewed: false,
    ...overrides,
  }
}

describe('门户资讯展示辅助', () => {
  it('同题多期折成一组，最新一条作为主条，其余作为较早期次', () => {
    const groups = groupNewsItems([
      item({ id: 'a', publishedAt: '2026-09-25T15:16:26Z', canonicalUrl: 'https://www.who.int/x/2026-DON618' }),
      item({ id: 'b', publishedAt: '2026-09-10T08:16:08Z', canonicalUrl: 'https://www.who.int/x/2026-DON617' }),
      item({
        id: 'c',
        title: 'Cholera - Haiti',
        publishedAt: '2026-08-01T10:13:28Z',
        canonicalUrl: 'https://www.who.int/x/2026-DON614',
      }),
    ])

    expect(groups).toHaveLength(2)
    expect(groups[0]!.lead.id).toBe('a')
    expect(groups[0]!.updates.map(entry => entry.id)).toEqual(['b'])
    expect(groups[0]!.periods).toEqual(['DON618（2026）', 'DON617（2026）'])
    expect(groups[1]!.lead.id).toBe('c')
    expect(groups[1]!.updates).toEqual([])
  })

  it('组内按时间从新到旧排序，缺发布时间时退回获取时间', () => {
    const groups = groupNewsItems([
      item({ id: 'old', publishedAt: null, retrievedAt: '2026-09-01T00:00:00Z' }),
      item({ id: 'new', publishedAt: null, retrievedAt: '2026-10-01T00:00:00Z' }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]!.lead.id).toBe('new')
  })

  it('期号只从链接末段识别，认不出就不显示', () => {
    expect(periodLabel(item({ id: 'a', canonicalUrl: 'https://www.who.int/x/2026-DON618' }))).toBe(
      'DON618（2026）',
    )
    expect(
      periodLabel(item({ id: 'b', canonicalUrl: 'https://example.org/news/health-tips' })),
    ).toBeNull()
    expect(periodLabel(item({ id: 'c', canonicalUrl: 'https://example.org/' }))).toBeNull()
  })

  it('来源状态用中文，时间解析不了就走兜底文案', () => {
    expect(sourceStatusText('ready')).toBe('正常')
    expect(sourceStatusText('failed')).toBe('更新失败')
    expect(formatMoment(null, '发布时间未核实')).toBe('发布时间未核实')
    expect(formatMoment('不是时间', '发布时间未核实')).toBe('发布时间未核实')
    expect(formatMoment('2026-09-25T15:16:26Z')).toContain('2026')
  })
})