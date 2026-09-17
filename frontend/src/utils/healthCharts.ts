import type { HealthRecord, HealthRecordSource } from '../types/healthRecords'

/**
 * 图表边界文案。
 *
 * 健康记录是用户自述事实的集合，不是病程数据。图表只能描述「记录行为与构成」，
 * 不得表达严重程度、病情进展或患病风险——那属于医学判断，越过产品「不作确诊、
 * 不替代医生」的边界，也与提示词里「不得据记录推断病因」的规则相冲突。
 */
export const CHART_BOUNDARY_TEXT =
  '以下图表只统计你记录的条数与分类构成，反映的是记录情况，不反映病情轻重或变化趋势，不构成诊断，也不能替代医生。'

export const ACTIVITY_WINDOW_MONTHS = 6

export const SOURCE_LABELS: Record<HealthRecordSource, string> = {
  onboarding: '首次采集',
  conversation: '对话自动记录',
  user: '你手动添加或修改',
}

/** 来源在图例中的固定顺序：手动最可控，排最前。 */
const SOURCE_ORDER: HealthRecordSource[] = ['user', 'conversation', 'onboarding']

export interface SliceDatum {
  name: string
  value: number
}

export interface ActivityData {
  labels: string[]
  counts: number[]
}

export interface PieOption {
  // ECharts 的 ECBasicOption 带索引签名，这里必须显式声明才能直接传入 setOption。
  [key: string]: unknown
  tooltip: { trigger: 'item'; formatter: string }
  legend: { bottom: number; type: 'scroll'; icon: string; data: string[] }
  series: Array<{
    type: 'pie'
    radius: [string, string]
    center: [string, string]
    avoidLabelOverlap: boolean
    itemStyle: { borderColor: string; borderWidth: number }
    label: { formatter: string }
    data: SliceDatum[]
  }>
}

export interface ActivityOption {
  // 同上：ECharts 的 ECBasicOption 带索引签名。
  [key: string]: unknown
  tooltip: { trigger: 'axis'; axisPointer: { type: 'shadow' }; formatter: string }
  grid: { left: number; right: number; top: number; bottom: number; containLabel: boolean }
  xAxis: { type: 'category'; data: string[]; axisTick: { alignWithLabel: boolean } }
  yAxis: {
    type: 'value'
    name: string
    minInterval: number
    axisLabel: { formatter: string }
  }
  series: Array<{
    type: 'bar'
    name: string
    data: number[]
    barMaxWidth: number
    itemStyle: { color: string; borderRadius: [number, number, number, number] }
  }>
}

function monthKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}`
}

/** 按分类统计条数，用于构成占比。 */
export function categoryDistribution(records: HealthRecord[]): SliceDatum[] {
  const counts = new Map<string, number>()
  for (const record of records) {
    const name = record.categoryLabel || record.category
    counts.set(name, (counts.get(name) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([name, value]) => ({ name, value }))
    .sort((left, right) => right.value - left.value || left.name.localeCompare(right.name, 'zh-CN'))
}

/** 按来源统计条数，顺序固定，避免图例随数据跳动。 */
export function sourceDistribution(records: HealthRecord[]): SliceDatum[] {
  const counts = new Map<string, number>()
  for (const record of records) {
    counts.set(record.source, (counts.get(record.source) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([source, value]) => ({
      name: SOURCE_LABELS[source as HealthRecordSource] ?? source,
      value,
      rank: SOURCE_ORDER.indexOf(source as HealthRecordSource),
    }))
    .sort((left, right) => {
      const leftRank = left.rank === -1 ? SOURCE_ORDER.length : left.rank
      const rightRank = right.rank === -1 ? SOURCE_ORDER.length : right.rank
      return leftRank - rightRank
    })
    .map(({ name, value }) => ({ name, value }))
}

/**
 * 统计最近若干个月各月的记录条数。
 *
 * 这是「记录活跃度」，不是症状频率：纵轴单位是条数，窗口外的记录不计入。
 * `now` 可注入，便于测试得到确定结果。
 */
export function monthlyActivity(
  records: HealthRecord[],
  months: number = ACTIVITY_WINDOW_MONTHS,
  now: Date = new Date(),
): ActivityData {
  const window = Math.max(1, Math.trunc(months))
  const cursor = new Date(now.getFullYear(), now.getMonth(), 1)
  cursor.setMonth(cursor.getMonth() - (window - 1))

  const keys: string[] = []
  const labels: string[] = []
  const buckets = new Map<string, number>()
  for (let index = 0; index < window; index += 1) {
    keys.push(monthKey(cursor))
    labels.push(`${cursor.getMonth() + 1}月`)
    buckets.set(monthKey(cursor), 0)
    cursor.setMonth(cursor.getMonth() + 1)
  }

  for (const record of records) {
    const date = new Date(record.recordedAt)
    if (Number.isNaN(date.getTime())) continue
    const key = monthKey(date)
    if (buckets.has(key)) buckets.set(key, (buckets.get(key) ?? 0) + 1)
  }

  return { labels, counts: keys.map((key) => buckets.get(key) ?? 0) }
}

export function buildCategoryOption(data: SliceDatum[]): PieOption {
  return {
    tooltip: { trigger: 'item', formatter: '{b}：{c} 条（{d}%）' },
    legend: {
      bottom: 0,
      type: 'scroll',
      icon: 'circle',
      data: data.map((item) => item.name),
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '68%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#ffffff', borderWidth: 1 },
        label: { formatter: '{b} {c}' },
        data,
      },
    ],
  }
}

export function buildSourceOption(data: SliceDatum[]): PieOption {
  return {
    tooltip: { trigger: 'item', formatter: '{b}：{c} 条（{d}%）' },
    legend: {
      bottom: 0,
      type: 'scroll',
      icon: 'circle',
      data: data.map((item) => item.name),
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '68%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#ffffff', borderWidth: 1 },
        label: { formatter: '{b} {c}' },
        data,
      },
    ],
  }
}

export function buildActivityOption(data: ActivityData): ActivityOption {
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: '{b}：记录 {c} 条',
    },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: data.labels, axisTick: { alignWithLabel: true } },
    // 纵轴刻意命名为「记录条数」：避免任何「严重程度 / 症状频率」的临床读法。
    yAxis: {
      type: 'value',
      name: '记录条数',
      minInterval: 1,
      axisLabel: { formatter: '{value}' },
    },
    series: [
      {
        type: 'bar',
        name: '记录条数',
        data: data.counts,
        barMaxWidth: 32,
        itemStyle: { color: '#409eff', borderRadius: [4, 4, 0, 0] },
      },
    ],
  }
}

/** 三个图表共用的空状态判断：没有记录时不渲染图表，由页面显示空提示。 */
export function hasChartData(records: HealthRecord[]): boolean {
  return records.length > 0
}