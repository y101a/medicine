<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ApiError, getApiErrorMessage, sanitizeApiMessage } from '../api/http'
import {
  knowledgeGraphApi,
  type GraphConcept,
  type GraphRelation,
} from '../api/knowledgeGraph'
import {
  KNOWLEDGE_GRAPH_BOUNDARY_SHORT,
  KNOWLEDGE_GRAPH_DISCLAIMER,
  KNOWLEDGE_GRAPH_EMPTY_CAVEAT,
  KNOWLEDGE_GRAPH_EMPTY_HINT,
  KNOWLEDGE_GRAPH_EXAMPLE_QUERIES,
  KNOWLEDGE_GRAPH_MAX_NODES,
  KNOWLEDGE_GRAPH_MAX_RELATIONS,
  KNOWLEDGE_GRAPH_QUERY_MAX_LENGTH,
  KNOWLEDGE_GRAPH_QUERY_MIN_LENGTH,
  KNOWLEDGE_GRAPH_UNAVAILABLE_HINT,
  KNOWLEDGE_GRAPH_UNREVIEWED_NOTICE,
  conceptTypeLabel,
  groupRelationsByPredicate,
  isHttpUrl,
  predicateLabel,
  readRelationReview,
  type KnowledgeGraphViewState,
} from '../types/knowledgeGraphUi'

/**
 * 知识图谱探索页（独立路由 `/knowledge-graph`，入口在主导航）。
 *
 * 产品决策（用户已确认，不再询问）：**独立路由页 + 页面内自带搜索框**；
 * 入口**不得**放进聊天输入框 `.composer` 的任何位置（`AGENTS.md` 的界面入口纪律）。
 *
 * 三条硬要求在这一页里怎么落地：
 * 1. **只呈现、不生成**：所有关系与证据都来自后端只读接口，本页不拼结论、不给剂量、
 *    不推荐药名、不说确诊。证据里没有正文片段（后端只返回文档/知识块标识），所以也不编摘要。
 * 2. **三态必须区分**：`data-state="unavailable|empty|ready"`。
 *    - `unavailable`：请求报错/超时/非 2xx，或后端明确 `available=false`（未启用、版本失配、故障）；
 *    - `empty`：查询成功但没有可展示内容（没有概念，或概念下没有已发布关系）；
 *    - `ready`：拿到了至少一条已发布关系。
 *    **绝不把失败显示成空结果**（本项目有过「请求失败显示成还没有知识库」的真实事故）。
 *    另外 `GET /concepts` 在图谱开关关闭时同样返回空列表，这一点在空态里如实说明。
 * 3. **未审核关系必须标注**：契约只返回已发布且已审核的关系，但一旦响应里出现
 *    `status`/`reviewStatus`/`reviewDecision` 且不是 published/approved，
 *    卡片必须显著标注「未审核、仅供参考、不是医学结论」。
 */

const state = ref<KnowledgeGraphViewState>('idle')
const query = ref('')
const validationError = ref('')
const unavailableReason = ref('')
const unavailableWhat = ref('')
const concepts = ref<GraphConcept[]>([])
const selectedConceptId = ref<string | null>(null)
const relations = ref<GraphRelation[]>([])
const revision = ref<number | null>(null)
const expandedEvidence = ref<Record<string, boolean>>({})

/** 状态区（`tabindex="-1"`）：状态切换后把键盘焦点移过去，读屏与键盘用户都不用重新找。 */
const stateRegion = ref<HTMLElement | null>(null)

/** 只认最后一次请求：慢响应不能覆盖新一次查询的结果。 */
let requestSeq = 0

const groups = computed(() => groupRelationsByPredicate(relations.value))
const selectedConcept = computed(
  () => concepts.value.find(concept => concept.id === selectedConceptId.value) ?? null,
)
const selectedConceptName = computed(() => selectedConcept.value?.name ?? '')

const emptyHeading = computed(() =>
  concepts.value.length ? '没有找到相关关系' : '没有找到相关概念',
)

const mayBeTruncated = computed(() => relations.value.length >= KNOWLEDGE_GRAPH_MAX_RELATIONS)

const announcement = computed(() => {
  switch (state.value) {
    case 'loading':
      return '正在查询图谱…'
    case 'unavailable':
      return `图谱暂不可用：${unavailableReason.value}`
    case 'empty':
      return emptyHeading.value
    case 'ready':
      return `已找到 ${relations.value.length} 条已发布关系`
    default:
      return ''
  }
})

function focusState() {
  void nextTick(() => stateRegion.value?.focus())
}

function clearResults() {
  concepts.value = []
  selectedConceptId.value = null
  relations.value = []
  revision.value = null
  expandedEvidence.value = {}
  unavailableReason.value = ''
  unavailableWhat.value = ''
}

/** 失败一律走这里：**不**退化成空结果。 */
function markUnavailable(error: unknown, what: string) {
  const status = error instanceof ApiError ? error.status : undefined
  const code = error instanceof ApiError ? sanitizeApiMessage(error.code) : undefined
  const detail = [status ? `HTTP ${status}` : '', code ?? ''].filter(Boolean).join(' / ')
  unavailableWhat.value = what
  unavailableReason.value = `${what}失败：${getApiErrorMessage(error)}${detail ? `（${detail}）` : ''}`
  state.value = 'unavailable'
  focusState()
}

/**
 * 拉某个概念的关系。
 *
 * `available=false` 是**可用性**信号（后端未启用/版本失配/故障），必须显示成①而不是②。
 */
async function loadRelations(conceptId: string, seq?: number) {
  const token = seq ?? ++requestSeq
  selectedConceptId.value = conceptId
  expandedEvidence.value = {}
  relations.value = []
  revision.value = null
  state.value = 'loading'
  try {
    const result = await knowledgeGraphApi.explore(conceptId)
    if (token !== requestSeq) return
    if (!result.available) {
      unavailableWhat.value = '关系查询'
      unavailableReason.value =
        '后端返回 available=false：图谱读取开关未启用、发布版本与预期不一致，或图谱服务暂时故障。'
      state.value = 'unavailable'
      focusState()
      return
    }
    revision.value = result.revision
    relations.value = result.relations
    // 概念找到了但一条已发布关系都没有，也算「查询成功但无结果」，不能显示成可用结果。
    state.value = relations.value.length ? 'ready' : 'empty'
    focusState()
  } catch (error) {
    if (token !== requestSeq) return
    markUnavailable(error, '关系查询')
  }
}

async function runSearch() {
  const keyword = query.value.trim()
  validationError.value = ''
  if (keyword.length < KNOWLEDGE_GRAPH_QUERY_MIN_LENGTH) {
    validationError.value = `请至少输入 ${KNOWLEDGE_GRAPH_QUERY_MIN_LENGTH} 个字符`
    return
  }
  if (keyword.length > KNOWLEDGE_GRAPH_QUERY_MAX_LENGTH) {
    validationError.value = `最多输入 ${KNOWLEDGE_GRAPH_QUERY_MAX_LENGTH} 个字符`
    return
  }
  const token = ++requestSeq
  clearResults()
  state.value = 'loading'
  try {
    const found = await knowledgeGraphApi.concepts(keyword)
    if (token !== requestSeq) return
    concepts.value = found
    if (!found.length) {
      // 查询本身成功，但没有任何可展示内容。
      state.value = 'empty'
      focusState()
      return
    }
    await loadRelations(found[0].id, token)
  } catch (error) {
    if (token !== requestSeq) return
    markUnavailable(error, '概念搜索')
  }
}

function selectConcept(conceptId: string) {
  if (state.value === 'loading') return
  void loadRelations(conceptId)
}

function useExample(text: string) {
  query.value = text
  void runSearch()
}

/** 重试按「上一次做到哪一步」重放，不改变用户输入。 */
function retry() {
  if (selectedConceptId.value && concepts.value.length) {
    void loadRelations(selectedConceptId.value)
    return
  }
  if (query.value.trim().length >= KNOWLEDGE_GRAPH_QUERY_MIN_LENGTH) {
    void runSearch()
    return
  }
  state.value = 'idle'
}

function toggleEvidence(claimId: string) {
  expandedEvidence.value = {
    ...expandedEvidence.value,
    [claimId]: !expandedEvidence.value[claimId],
  }
}

function evidenceId(claimId: string) {
  return `kg-evidence-${claimId}`
}
</script>

<template>
  <div class="knowledge-graph" :data-state="state">
    <header class="kg-head">
      <router-link class="kg-back" to="/app">← 返回工作区</router-link>
      <div class="kg-head__text">
        <h1 class="kg-title">知识图谱探索</h1>
        <p class="kg-subtitle">公共医学知识图谱 · 只读 · 结果来自后端已发布快照</p>
      </div>
    </header>

    <main class="kg-main">
      <p class="kg-disclaimer" role="note">{{ KNOWLEDGE_GRAPH_DISCLAIMER }}</p>

      <form class="kg-search" role="search" @submit.prevent="runSearch">
        <label class="kg-search__label" for="kg-query">
          搜索概念（症状、主题或科室）
        </label>
        <div class="kg-search__row">
          <input
            id="kg-query"
            v-model="query"
            class="kg-search__input"
            type="search"
            name="kg-query"
            autocomplete="off"
            :maxlength="KNOWLEDGE_GRAPH_QUERY_MAX_LENGTH"
            placeholder="例如：发热、儿童发热、科学运动"
            :aria-describedby="validationError ? 'kg-query-error' : 'kg-query-hint'"
          />
          <button type="submit" class="kg-search__submit" :disabled="state === 'loading'">
            {{ state === 'loading' ? '查询中…' : '搜索' }}
          </button>
        </div>
        <p id="kg-query-hint" class="kg-search__hint">
          支持 {{ KNOWLEDGE_GRAPH_QUERY_MIN_LENGTH }}–{{ KNOWLEDGE_GRAPH_QUERY_MAX_LENGTH }} 个字符；
          这里只做概念与关系检索，不会保存你的症状，也不做诊断。
        </p>
        <p v-if="validationError" id="kg-query-error" class="kg-search__error" role="alert">
          {{ validationError }}
        </p>
      </form>

      <p class="kg-live" role="status" aria-live="polite">{{ announcement }}</p>

      <section v-if="concepts.length" class="kg-concepts" aria-label="概念候选">
        <h2 class="kg-concepts__title">概念候选（{{ concepts.length }}）</h2>
        <ul class="kg-concepts__list">
          <li v-for="concept in concepts" :key="concept.id">
            <button
              type="button"
              class="kg-concept"
              :class="{ 'kg-concept--selected': concept.id === selectedConceptId }"
              :aria-pressed="concept.id === selectedConceptId"
              @click="selectConcept(concept.id)"
            >
              <span class="kg-concept__name">{{ concept.name }}</span>
              <span class="kg-concept__type">{{ conceptTypeLabel(concept.type) }}</span>
            </button>
          </li>
        </ul>
      </section>

      <section
        v-if="state === 'idle'"
        class="kg-state kg-state--idle"
        data-testid="kg-state-idle"
      >
        <h2>输入一个概念开始探索</h2>
        <p>{{ KNOWLEDGE_GRAPH_EMPTY_HINT }}</p>
        <ul class="kg-examples">
          <li v-for="example in KNOWLEDGE_GRAPH_EXAMPLE_QUERIES" :key="example">
            <button type="button" class="kg-example" @click="useExample(example)">
              {{ example }}
            </button>
          </li>
        </ul>
      </section>

      <section
        v-else-if="state === 'loading'"
        class="kg-state kg-state--loading"
        data-testid="kg-state-loading"
      >
        <h2>正在查询图谱…</h2>
        <p>只读查询，不会改动图谱数据。</p>
      </section>

      <!-- ① 图谱不可用：必须与「没有找到」分开，并给出原因与重试。 -->
      <section
        v-else-if="state === 'unavailable'"
        ref="stateRegion"
        class="kg-state kg-state--unavailable"
        data-testid="kg-state-unavailable"
        role="alert"
        tabindex="-1"
      >
        <h2>图谱暂不可用</h2>
        <p class="kg-state__reason">{{ unavailableReason }}</p>
        <p class="kg-state__hint">{{ KNOWLEDGE_GRAPH_UNAVAILABLE_HINT }}</p>
        <p class="kg-state__scope">
          出错环节：{{ unavailableWhat || '图谱查询' }}。这不表示该概念在医学上「没有关系」，
          也不表示图谱里没有它。
        </p>
        <button type="button" class="kg-retry" @click="retry">重试</button>
      </section>

      <!-- ② 查询成功但无结果。 -->
      <section
        v-else-if="state === 'empty'"
        ref="stateRegion"
        class="kg-state kg-state--empty"
        data-testid="kg-state-empty"
        tabindex="-1"
      >
        <h2>{{ emptyHeading }}</h2>
        <p class="kg-state__hint">{{ KNOWLEDGE_GRAPH_EMPTY_HINT }}</p>
        <ul class="kg-examples">
          <li v-for="example in KNOWLEDGE_GRAPH_EXAMPLE_QUERIES" :key="example">
            <button type="button" class="kg-example" @click="useExample(example)">
              {{ example }}
            </button>
          </li>
        </ul>
        <p class="kg-state__caveat">{{ KNOWLEDGE_GRAPH_EMPTY_CAVEAT }}</p>
        <button v-if="selectedConceptId" type="button" class="kg-retry" @click="retry">
          重新查询这个概念
        </button>
      </section>

      <!-- ③ 有结果。 -->
      <section
        v-else-if="state === 'ready'"
        ref="stateRegion"
        class="kg-state kg-state--ready"
        data-testid="kg-state-ready"
        tabindex="-1"
      >
        <div class="kg-results__head">
          <h2>已发布关系（{{ relations.length }} 条）</h2>
          <p class="kg-results__meta">
            <span v-if="selectedConceptName">概念「{{ selectedConceptName }}」</span>
            <span v-if="revision !== null"> · 图谱版本 revision={{ revision }}</span>
          </p>
          <p class="kg-results__scope">
            1 跳只读关系，最多 {{ KNOWLEDGE_GRAPH_MAX_NODES }} 个节点；
            这些是知识库里的关联线索，不是诊断结论，也不是就医指令。
          </p>
          <p v-if="mayBeTruncated" class="kg-results__truncated">
            已达到后端单次返回上限（{{ KNOWLEDGE_GRAPH_MAX_NODES }} 个节点），
            该概念可能还有未列出的关系。
          </p>
        </div>

        <section
          v-for="group in groups"
          :key="group.predicate"
          class="kg-group"
          :data-predicate="group.predicate"
        >
          <h3 class="kg-group__title">
            {{ group.label }}（{{ group.relations.length }}）
            <span v-if="!group.known" class="kg-group__unknown">
              后端返回了本页未登记的关系类型，已原样展示
            </span>
          </h3>
          <ul class="kg-relations">
            <li
              v-for="relation in group.relations"
              :key="relation.claimId"
              class="kg-relation"
              :class="{ 'kg-relation--unreviewed': !readRelationReview(relation).reviewed }"
              :data-claim-id="relation.claimId"
            >
              <p class="kg-relation__line">
                <span class="kg-relation__subject">{{ relation.subject?.name }}</span>
                <span class="kg-relation__type">
                  {{ relation.subject?.type ? conceptTypeLabel(relation.subject.type) : '' }}
                </span>
                <span class="kg-relation__arrow" aria-hidden="true">→</span>
                <span class="kg-relation__label">{{ predicateLabel(relation.predicate) }}</span>
                <span class="kg-relation__arrow" aria-hidden="true">→</span>
                <span class="kg-relation__object">{{ relation.object?.name }}</span>
                <span class="kg-relation__type">
                  {{ relation.object?.type ? conceptTypeLabel(relation.object.type) : '' }}
                </span>
              </p>

              <p
                v-if="!readRelationReview(relation).reviewed"
                class="kg-relation__unreviewed"
                role="note"
              >
                {{ KNOWLEDGE_GRAPH_UNREVIEWED_NOTICE }}
                <span v-if="readRelationReview(relation).raw" class="kg-relation__unreviewed-raw">
                  （后端状态：{{ readRelationReview(relation).raw }}）
                </span>
              </p>

              <button
                type="button"
                class="kg-evidence-toggle"
                :aria-expanded="expandedEvidence[relation.claimId] === true"
                :aria-controls="evidenceId(relation.claimId)"
                @click="toggleEvidence(relation.claimId)"
              >
                {{ expandedEvidence[relation.claimId] ? '收起证据' : '查看证据' }}
                （{{ (relation.evidence || []).length }}）
              </button>

              <ul
                v-if="expandedEvidence[relation.claimId]"
                :id="evidenceId(relation.claimId)"
                class="kg-evidence"
              >
                <li
                  v-for="(item, index) in relation.evidence || []"
                  :key="item.chunkId || index"
                  class="kg-evidence__item"
                >
                  <p class="kg-evidence__title">{{ item.title || '后端未提供文档标题' }}</p>
                  <p v-if="item.section" class="kg-evidence__section">章节：{{ item.section }}</p>
                  <p class="kg-evidence__ids">
                    文档 ID <code>{{ item.documentId }}</code>
                    · 知识块 ID <code>{{ item.chunkId }}</code>
                  </p>
                  <!-- 证据只给定位标识，后端不返回正文片段，所以这里不展示任何摘录。 -->
                  <a
                    v-if="isHttpUrl(item.url)"
                    class="kg-evidence__link"
                    :href="item.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >打开来源原文（外部站点，未经本页核对）</a>
                  <span v-else class="kg-evidence__nourl">后端未提供可打开的来源链接</span>
                </li>
                <li v-if="!(relation.evidence || []).length" class="kg-evidence__item">
                  后端没有返回这条关系的证据条目。
                </li>
              </ul>
            </li>
          </ul>
        </section>
      </section>

      <p class="kg-foot-note">{{ KNOWLEDGE_GRAPH_BOUNDARY_SHORT }}</p>
    </main>

    <footer class="kg-foot">
      <p>
        知识图谱探索 · 开发原型。内容未经医学审核，仅供科普参考，不构成诊断或用药建议，
        请以医生面诊与原始来源为准。
      </p>
      <p class="kg-foot__mark">病理诊断科普助手 · 健康科普与就医分流</p>
    </footer>
  </div>
</template>

<style scoped>
/* 独立路由页：**不挂在** WorkspaceLayout 下，因此不受 ADR-011 的 1000px 桌面优先约束，
   375px 下也必须真的不横向溢出（与 /portal 同一取舍）。 */
.knowledge-graph {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  max-width: 100%;
  overflow-x: hidden;
  background: #f5f8fb;
  color: #334d64;
}
.knowledge-graph *,
.knowledge-graph *::before,
.knowledge-graph *::after { box-sizing: border-box; }

.kg-head {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
  align-items: baseline;
  padding: 20px clamp(16px, 3vw, 40px) 6px;
}
.kg-back {
  flex-shrink: 0;
  color: #196db2;
  font-size: 13px;
  text-decoration: none;
  border-radius: 6px;
  padding: 4px 6px;
}
.kg-back:hover { background: #e7f0fa; }
.kg-head__text { min-width: 0; }
.kg-title { margin: 4px 0 2px; font-size: 22px; color: #22405c; }
.kg-subtitle { margin: 0; font-size: 12px; color: #8a99a8; }

.kg-main {
  flex: 1;
  min-width: 0;
  width: 100%;
  max-width: 1040px;
  padding: 8px clamp(16px, 3vw, 40px) 28px;
}

.kg-disclaimer {
  margin: 0 0 16px;
  padding: 12px 14px;
  border-left: 3px solid #e0a34a;
  border-radius: 6px;
  background: #fdf6ea;
  color: #7a5620;
  font-size: 13px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.kg-search {
  padding: 14px;
  border: 1px solid #e4ebf2;
  border-radius: 10px;
  background: #fff;
}
.kg-search__label { display: block; margin-bottom: 8px; font-size: 13px; color: #3d5a75; }
.kg-search__row { display: flex; flex-wrap: wrap; gap: 10px; }
.kg-search__input {
  flex: 1 1 220px;
  min-width: 0;
  height: 40px;
  padding: 0 12px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  font-size: 14px;
  color: #26405a;
}
.kg-search__input:focus-visible,
.kg-search__submit:focus-visible,
.kg-concept:focus-visible,
.kg-example:focus-visible,
.kg-retry:focus-visible,
.kg-evidence-toggle:focus-visible,
.kg-back:focus-visible,
.kg-evidence__link:focus-visible {
  outline: 2px solid #398ad0;
  outline-offset: 2px;
}
.kg-search__submit {
  flex-shrink: 0;
  height: 40px;
  padding: 0 22px;
  border: 0;
  border-radius: 8px;
  background: #237ac2;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}
.kg-search__submit:disabled { background: #a9c6dd; cursor: not-allowed; }
.kg-search__hint { margin: 10px 0 0; font-size: 12px; color: #8a99a8; line-height: 1.7; }
.kg-search__error { margin: 8px 0 0; font-size: 12px; color: #c0392b; }

/* 读屏用播报区：视觉上不重复状态标题，但必须留在 DOM 里。 */
.kg-live {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.kg-concepts { margin: 18px 0 0; }
.kg-concepts__title { margin: 0 0 8px; font-size: 13px; color: #5b7084; }
.kg-concepts__list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.kg-concept {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 7px 12px;
  border: 1px solid #d9e2ec;
  border-radius: 999px;
  background: #fff;
  color: #2c4b68;
  font-size: 13px;
  cursor: pointer;
}
.kg-concept__name { overflow-wrap: anywhere; }
.kg-concept__type { flex-shrink: 0; font-size: 11px; color: #8a99a8; }
.kg-concept--selected { border-color: #237ac2; background: #e7f0fa; color: #17578f; }

.kg-state {
  margin: 18px 0 0;
  padding: 16px;
  border: 1px solid #e4ebf2;
  border-radius: 10px;
  background: #fff;
}
.kg-state:focus { outline: none; }
.kg-state:focus-visible { outline: 2px solid #398ad0; outline-offset: 2px; }
.kg-state h2 { margin: 0 0 8px; font-size: 16px; color: #22405c; }
.kg-state p { margin: 0 0 8px; font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.kg-state__hint { color: #5b7084; }
.kg-state__reason { color: #b3402f; }
.kg-state__scope { color: #8a99a8; font-size: 12px !important; }
.kg-state__caveat {
  padding: 10px 12px;
  border-radius: 8px;
  background: #f4f7fa;
  color: #647588;
  font-size: 12px !important;
}
.kg-state--unavailable { border-color: #edc9c1; background: #fdf4f2; }
.kg-state--unavailable h2 { color: #a8331f; }

.kg-examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 10px;
  padding: 0;
  list-style: none;
}
.kg-example {
  padding: 6px 12px;
  border: 1px dashed #c8d6e3;
  border-radius: 999px;
  background: #fbfdff;
  color: #31618c;
  font-size: 12px;
  cursor: pointer;
}

.kg-retry {
  padding: 9px 18px;
  border: 1px solid #237ac2;
  border-radius: 8px;
  background: #fff;
  color: #17578f;
  font-size: 13px;
  cursor: pointer;
}
.kg-retry:hover { background: #eaf3fb; }

.kg-results__head h2 { margin: 0 0 6px; font-size: 16px; color: #22405c; }
.kg-results__meta { margin: 0 0 6px; font-size: 12px; color: #8a99a8; }
.kg-results__scope { margin: 0 0 4px; font-size: 12px; color: #647588; line-height: 1.7; }
.kg-results__truncated { margin: 0; font-size: 12px; color: #a06a15; }

.kg-group { margin: 16px 0 0; padding-top: 12px; border-top: 1px solid #eef3f8; }
.kg-group__title { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; margin: 0 0 10px; font-size: 14px; color: #31618c; }
.kg-group__unknown { font-size: 11px; color: #a06a15; font-weight: 400; }
.kg-relations { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.kg-relation {
  padding: 12px;
  border: 1px solid #e8eef5;
  border-radius: 8px;
  background: #fbfdff;
}
.kg-relation--unreviewed { border-color: #e0a34a; background: #fdf6ea; }
.kg-relation__line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
  margin: 0 0 8px;
  font-size: 13px;
  color: #26405a;
  overflow-wrap: anywhere;
}
.kg-relation__subject,
.kg-relation__object { font-weight: 600; }
.kg-relation__label { color: #5b7084; }
.kg-relation__type { font-size: 11px; color: #93a3b2; }
.kg-relation__arrow { color: #a9b6c1; }
.kg-relation__unreviewed {
  margin: 0 0 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #f6e3c2;
  color: #7a5620;
  font-size: 12px;
  font-weight: 600;
}
.kg-relation__unreviewed-raw { font-weight: 400; }

.kg-evidence-toggle {
  padding: 6px 12px;
  border: 1px solid #d9e2ec;
  border-radius: 6px;
  background: #fff;
  color: #31618c;
  font-size: 12px;
  cursor: pointer;
}
.kg-evidence { display: grid; gap: 8px; margin: 10px 0 0; padding: 0; list-style: none; }
.kg-evidence__item {
  padding: 10px;
  border: 1px dashed #dbe5ee;
  border-radius: 8px;
  background: #fff;
}
.kg-evidence__item p { margin: 0 0 4px; font-size: 12px; line-height: 1.7; color: #4a6377; overflow-wrap: anywhere; }
.kg-evidence__title { font-weight: 600; color: #26405a !important; }
.kg-evidence__ids { color: #8a99a8 !important; }
.kg-evidence__ids code { overflow-wrap: anywhere; }
.kg-evidence__link { font-size: 12px; color: #196db2; overflow-wrap: anywhere; }
.kg-evidence__nourl { font-size: 12px; color: #a9b6c1; }

.kg-foot-note { margin: 20px 0 0; font-size: 12px; color: #8a99a8; }
.kg-foot {
  margin-top: auto;
  padding: 16px clamp(16px, 3vw, 40px) 22px;
  border-top: 1px solid #e6edf3;
  background: #fff;
}
.kg-foot p { max-width: 1000px; margin: 0 0 6px; font-size: 11px; line-height: 1.9; color: #8c9ba9; }
.kg-foot__mark { color: #a9b6c1; }

/* 375px：单列纵向排列，长 ID 与长概念名都必须能换行，不允许撑出横向滚动。 */
@media (max-width: 640px) {
  .kg-head { padding: 16px 14px 4px; }
  .kg-main { padding: 6px 14px 22px; }
  .kg-search__row { flex-direction: column; }
  .kg-search__submit { width: 100%; }
  .kg-relation__line { flex-direction: column; gap: 2px; }
  .kg-relation__arrow { display: none; }
}
</style>