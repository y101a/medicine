import { describe, expect, it } from 'vitest'
import type { HealthRecord } from '../types/healthRecords'
import {
  CHART_BOUNDARY_TEXT,
  buildActivityOption,
  buildCategoryOption,
  buildSourceOption,
  categoryDistribution,
  hasChartData,
  monthlyActivity,
  sourceDistribution,
} from './healthCharts'

/** 用本地时间正午构造，避免时区把日期推到相邻月份。 */
function localIso(year: number, month: number, day: number): string {
  return new Date(year, month - 1, day, 12, 0, 0, 0).toISOString()
}

function record(overrides: Partial<HealthRecord> = {}): HealthRecord {
  return {
    id: 'r1',
    category: 'symptom',
    categoryLabel: '近期症状',
    content: '示例内容',
    source: 'user',
    recordedAt: localIso(2026, 9, 10),
    updatedAt: localIso(2026, 9, 10),
    ...overrides,
  }
}

describe('健康记录图表数据派生', () => {
  it('按分类统计条数并按条数降序排列', () => {
    const data = categoryDistribution([
      record({ id: 'a', category: 'symptom', categoryLabel: '近期症状' }),
      record({ id: 'b', category: 'allergy', categoryLabel: '过敏史' }),
      record({ id: 'c', category: 'symptom', categoryLabel: '近期症状' }),
    ])

    expect(data).toEqual([
      { name: '近期症状', value: 2 },
      { name: '过敏史', value: 1 },
    ])
  })

  it('分类标签缺失时退回分类原始值', () => {
    const data = categoryDistribution([record({ categoryLabel: '' })])
    expect(data).toEqual([{ name: 'symptom', value: 1 }])
  })

  it('按来源统计并固定顺序，方便图例位置稳定', () => {
    const data = sourceDistribution([
      record({ id: 'a', source: 'conversation' }),
      record({ id: 'b', source: 'onboarding' }),
      record({ id: 'c', source: 'user' }),
      record({ id: 'd', source: 'user' }),
    ])

    expect(data).toEqual([
      { name: '你手动添加或修改', value: 2 },
      { name: '对话自动记录', value: 1 },
      { name: '首次采集', value: 1 },
    ])
  })

  it('按月统计记录条数，窗口外的记录与非法时间都不计入', () => {
    const data = monthlyActivity(
      [
        record({ id: 'a', recordedAt: localIso(2026, 9, 10) }),
        record({ id: 'b', recordedAt: localIso(2026, 7, 3) }),
        record({ id: 'c', recordedAt: localIso(2026, 7, 28) }),
        record({ id: 'd', recordedAt: localIso(2026, 1, 5) }),
        record({ id: 'e', recordedAt: '不是时间' }),
      ],
      6,
      new Date(2026, 8, 20, 12, 0, 0),
    )

    expect(data.labels).toEqual(['4月', '5月', '6月', '7月', '8月', '9月'])
    expect(data.counts).toEqual([0, 0, 0, 2, 0, 1])
  })

  it('跨年窗口按年份正确分桶', () => {
    const data = monthlyActivity(
      [
        record({ id: 'a', recordedAt: localIso(2026, 1, 8) }),
        record({ id: 'b', recordedAt: localIso(2025, 12, 30) }),
      ],
      6,
      new Date(2026, 0, 15, 12, 0, 0),
    )

    expect(data.labels).toEqual(['8月', '9月', '10月', '11月', '12月', '1月'])
    expect(data.counts).toEqual([0, 0, 0, 0, 1, 1])
  })

  it('没有记录时返回全零而不是报错', () => {
    const data = monthlyActivity([], 3, new Date(2026, 8, 20, 12, 0, 0))
    expect(data.counts).toEqual([0, 0, 0])
  })
})

describe('图表配置不得越过产品边界', () => {
  it('活跃度图纵轴只表达「记录条数」，不出现临床口径', () => {
    const option = buildActivityOption(monthlyActivity([], 3, new Date(2026, 8, 20, 12, 0, 0)))
    const serialized = JSON.stringify(option)

    expect(option.yAxis.name).toBe('记录条数')
    expect(option.yAxis.minInterval).toBe(1)
    // 回归保护：任何「严重程度 / 症状频率 / 病情进展」的说法都不允许出现在图表配置里。
    expect(serialized).not.toMatch(/严重|程度|病情|恶化|好转|风险|患病|频率/)
  })

  it('构成类图表只统计条数占比，不做临床解读', () => {
    const data = [{ name: '近期症状', value: 2 }]
    const options = [buildCategoryOption(data), buildSourceOption(data)]

    for (const option of options) {
      expect(option.series[0].type).toBe('pie')
      expect(option.series[0].data).toEqual(data)
      expect(option.tooltip.formatter).toContain('条')
      expect(JSON.stringify(option)).not.toMatch(/严重|程度|病情|风险/)
    }
  })

  it('边界文案始终包含「不构成诊断」与「不能替代医生」', () => {
    expect(CHART_BOUNDARY_TEXT).toContain('不构成诊断')
    expect(CHART_BOUNDARY_TEXT).toContain('不能替代医生')
    expect(CHART_BOUNDARY_TEXT).toContain('不反映病情轻重或变化趋势')
  })
})

describe('图表空状态', () => {
  it('没有记录时不显示图表', () => {
    expect(hasChartData([])).toBe(false)
    expect(hasChartData([record()])).toBe(true)
  })
})