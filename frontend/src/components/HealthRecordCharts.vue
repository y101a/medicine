<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import type { HealthRecord } from '../types/healthRecords'
import {
  ACTIVITY_WINDOW_MONTHS,
  CHART_BOUNDARY_TEXT,
  buildActivityOption,
  buildCategoryOption,
  buildSourceOption,
  categoryDistribution,
  hasChartData,
  monthlyActivity,
  sourceDistribution,
} from '../utils/healthCharts'
import type { ActivityOption, PieOption } from '../utils/healthCharts'

// 按需注册：只引入用到的图表与组件，避免整包 ECharts 进入主包。
use([BarChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ records: HealthRecord[] }>()

type ChartKey = 'activity' | 'category' | 'source'
type ChartInstance = ReturnType<typeof init>
type ChartOption = ActivityOption | PieOption

const CHART_KEYS: readonly ChartKey[] = ['activity', 'category', 'source']

const activityEl = ref<HTMLDivElement | null>(null)
const categoryEl = ref<HTMLDivElement | null>(null)
const sourceEl = ref<HTMLDivElement | null>(null)

const instances: Partial<Record<ChartKey, ChartInstance>> = {}

const visible = computed(() => hasChartData(props.records))

function discard(key: ChartKey) {
  const chart = instances[key]
  delete instances[key]
  try {
    chart?.dispose()
  } catch {
    // 实例已损坏，忽略。
  }
}

/**
 * 图表只是补充信息，任何绘制失败都必须静默降级。
 *
 * jsdom（单元测试环境）没有画布，ECharts 可能在 `init` 或 `setOption` 阶段抛错。
 * 若放任它抛出，会连带打断同一页面上其它组件的渲染——实测会让同页的元素开关报错，
 * 所以这里两个阶段都要兜住。
 */
function apply(key: ChartKey, el: HTMLDivElement | null, option: ChartOption) {
  if (!el) return
  try {
    const chart = instances[key] ?? init(el)
    instances[key] = chart
    chart.setOption(option)
  } catch {
    discard(key)
  }
}

/** 只更新数据、不重建实例：重建会丢过渡动画，也会让 resize 失效。 */
function draw() {
  if (!visible.value) return
  apply('activity', activityEl.value, buildActivityOption(monthlyActivity(props.records)))
  apply('category', categoryEl.value, buildCategoryOption(categoryDistribution(props.records)))
  apply('source', sourceEl.value, buildSourceOption(sourceDistribution(props.records)))
}

function onResize() {
  for (const key of CHART_KEYS) {
    try {
      instances[key]?.resize()
    } catch {
      discard(key)
    }
  }
}

onMounted(() => {
  draw()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  for (const key of CHART_KEYS) discard(key)
})

// 容器随 `visible` 挂载，必须等 DOM 更新后再取 ref。
watch(() => props.records, draw, { flush: 'post' })
</script>

<template>
  <section v-if="visible" class="health-charts" aria-label="健康记录统计图表">
    <div class="health-charts__grid">
      <article class="health-charts__panel health-charts__panel--wide">
        <h2 class="health-charts__title">近 {{ ACTIVITY_WINDOW_MONTHS }} 个月记录条数</h2>
        <div ref="activityEl" class="health-charts__canvas"></div>
      </article>
      <article class="health-charts__panel">
        <h2 class="health-charts__title">记录分类构成</h2>
        <div ref="categoryEl" class="health-charts__canvas"></div>
      </article>
      <article class="health-charts__panel">
        <h2 class="health-charts__title">记录来源构成</h2>
        <div ref="sourceEl" class="health-charts__canvas"></div>
      </article>
    </div>
    <p class="health-charts__boundary">{{ CHART_BOUNDARY_TEXT }}</p>
  </section>
</template>

<style scoped>
.health-charts {
  margin-bottom: 16px;
}

.health-charts__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.health-charts__panel {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
}

.health-charts__panel--wide {
  grid-column: 1 / -1;
}

.health-charts__title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-main);
}

.health-charts__canvas {
  width: 100%;
  height: 220px;
}

.health-charts__boundary {
  margin: 10px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 720px) {
  .health-charts__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>