# 受控联网检索落地方案（本地知识不足时的当轮辅助）

> 本文只记录**决策、现状核对与接口契约**，不含实现。前端归 DSH，后端检索与安全链路归 Codex。
> 状态：2026-10-03 由 DSH 只读核对代码后撰写；**界面接线等后端契约落地**。

## 0. 用户决策（2026-10-03）

- 功能定位：**「本地知识不足时，受控联网检索并辅助当轮回答」**，而不是让爬虫抓到什么就写入正式知识库。
- 分工：Codex 负责后端检索与安全链路；DSH 负责前端状态与来源展示。
- 用户给出的四阶段：

| 阶段 | 后端：Codex | 前端：DSH |
| --- | --- | --- |
| 1. 搜索触发 | 扩展普通病名、药名问法的安全提取；本地证据为空或明显不足时触发搜索。只向搜索服务发送去标识化的通用主题，提取不确定就不发送。 | 复用现有对话状态区域，显示「正在检索」「未找到可靠资料」「搜索失败」；**不在输入框新增按钮**。 |
| 2. 获取与筛选 | 先复用现有搜索 API。只接收可信域名结果，校验实际 URL、主题相关性、发布时间；如需抓取页面正文，再单独设计限量抓取、超时、版权与站点规则，不做开放式全网爬取。 | 来源区显示机构、标题、链接、获取时间，以及醒目的「联网资料，未经医学审核」。 |
| 3. 回答安全 | 将合格结果作为当轮临时证据交给模型；抵御网页中的提示词注入，核验引用。资料不足时明确说不知道，不因搜索到了网页就给出诊断或处方。搜索故障时退回现有 RAG 和安全回答。 | 区分「审核知识」「联网未审核资料」和「无可靠依据」，不能把联网结果显示成已审核知识。 |
| 4. 数据治理与验收 | 搜索摘要最多进入有期限的 prototype 缓存，不得自动升为 approved；补隐私外发、误命中、失效网页、超时、生产环境开关及重复提问测试。 | 补前端单测与浏览器用例，核对加载、失败、来源标识、刷新历史对话后的显示。 |

- **上线门槛（用户原话）**：用一组包含常见病、陌生药名、含个人信息、急症、假冒官方域名和无结果问题的
  **冻结题集**，验证「该搜能搜、不该外发绝不外发、没有证据不编造」。**当前仍是开发环境原型，
  不应直接打开生产环境开关。**

## 1. 现状核对（2026-10-03 只读实测）

> **2026-10-04 更新**：用户后来确认改为「公开网页关键词发现」，上表第 2 行里的「只接收可信域名结果」
> **已过时**（现为公开 HTTPS URL 防护 + 未核实来源标注）；前端来源展示已按新规则修正（见 `COORDINATION.md` §7.2）。
> 仍未做的两项契约（`sources[].retrievedAt`、搜索开始信号）依然缺失。

后端读的是**工作树版本**（相对 HEAD 仍有未提交改动：`web_search.py` +64 行、`workflow.py` +18 行、
`retrieval.py` +12 行、`config.py` +3 行、`.env.example` +11 行）。

### 1.1 后端已经有

| 能力 | 位置 | 事实 |
| --- | --- | --- |
| 通用主题白名单 | `web_search.py:20-62` | 41 个固定病名，子串命中即返回 |
| 未知术语提取 | `web_search.py:150-194` | 三条路径 + `UNKNOWN_TERM.fullmatch` 后缀白名单 |
| 独立开关 | `config.py:174`、`.env.example:88` | `web_search_enabled` 默认 **False** |
| 触发条件 | `workflow.py:265-279` | `web_search_enabled and topic and (retrieval_status == "empty" or coverage_limited)` |
| 可信域名校验 | `web_search.py:229-244` | 必须 https、无账号/端口；`host == 域名` 或 `host.endswith("." + 域名)` |
| 只发通用词 | `web_search.py:247-277` | 发给 Tavily 的是主题词（`include_domains` 限定三家官网），不是用户原句 |
| 摘要入库 | `web_search.py:318-429` | `web_search_prototype` 来源、`review_status=prototype`、`license_type=unverified_search_excerpt`、`web_expires_at` **30 天**、不自动升 approved |

### 1.2 需要更正的描述（都有代码依据）

1. **「联网分支只在 development 环境运行」不准确。** 触发判断 `workflow.py:265-279` 里**没有环境判断**，
   只有 `web_search_enabled`（默认 false）。环境判断出现在**缓存复用**路径：`retrieval.py:141`（development
   下所有 prototype 可检索）、`retrieval.py:152`（非 development 只额外放行 `web_search_prototype`，
   且要 `include_web_cache and web_search_enabled`）。
   → 推论：当前**没有环境层面的硬保险**，只要把开关设成 true，任何环境都会真的外发查询。
   用户「不应直接打开生产环境开关」的告诫成立，且比预想更依赖这条自觉。
2. **「陌生术语必须被中文引号括起来才能提取」机制不对。** `safe_search_topic`（`web_search.py:162-181`）
   依次尝试：① 中文引号 `“…”`/`《…》`；② 前置模板（`什么是`/`药名是`/`得了`/`确诊为`…）；③ 后置模板
   （`X是什么`/`X有什么副作用`…）；未知术语还须匹配 `UNKNOWN_TERM`（2–10 个汉字 + `综合征|注射液|胶囊|颗粒|片|病|炎|癌|症`）。
   同时 41 个固定病名走子串命中。
   → 真实窄口是**模板 + 后缀白名单 + 长度上限**，不是引号：常见病名本来就会触发联网；
   自由文本里的药名/病名（不带模板、后缀不在这 8 个里、超过 10 字，或一句里出现两个候选）会被跳过。
   要扩的是这三处。

### 1.3 前端已经有（DSH 所有权内）

- 契约类型：`frontend/src/api/consultations.ts:7-14`（`status`/`gateReason`/`webSearchStatus`/`coverageLimited`/`errorCode`/`webSearchErrorCode`）。
- 状态文案：`frontend/src/views/HomeView.vue:567-589`（本地为空 + 搜索失败/搜索为空/未搜索、覆盖有限、本地检索失败；
  `WEB_SEARCH_TIMEOUT` 单独成句）。
- 来源展示：`frontend/src/components/ReferenceSources.vue`（「审核来源 / 联网原型 / 开发原型」徽标、
  联网告警句、「前往官网核对」、https 与三域名复核、旧消息「引用未核验」提示）。
- 测试：`ReferenceSources.test.ts`、`consultations.test.ts:173-244`、`api/consultations.test.ts`。
- **缺口**：① 没有「正在检索」（唯一等待态是 `AssistantAnswerCard.vue:71` 的「正在思考…」）；
  ② 没有获取时间（citation 无 `retrievedAt`）；③ 刷新历史对话后仍显示联网标识没有 e2e。

## 2. 接口契约

现状（前端已按它实现，无需重做）：

```
retrieval: {
  status, gateReason, webSearchStatus, webSearchErrorCode, coverageLimited, errorCode,
  sources: [{ referenceNumber, sourceKey, organization, title, canonicalUrl, sectionTitle, similarity, trustLevel }]
}
```

**需要新增的两项**（缺任一项都无法如实做界面）：

1. `sources[].retrievedAt`（ISO 8601，可空）——后端 `KnowledgeDocument.retrieved_at` 已有，
   只需进 `citation_snapshots` 载荷，用于显示「获取时间」。
2. **搜索开始信号**，二选一：**(a)** 新增中间事件 `webSearchStatus: "searching"`（建议，能如实显示
   「正在检索官网」）；**(b)** 零契约改动的降级：前端只显示「正在检索资料…」，不声称是否联网。

**不建议**把 `trustLevel` 扩成第三个枚举值——它承载「是否已审核」的语义；联网来源用
`sourceKey === 'web_search_prototype'` 区分已经足够（现状如此）。

待 Codex 确认（我没跑真实链路）：终态每条路径都带 `webSearchStatus` + `webSearchErrorCode`；
联网来源的 `organization`/`title`/`canonicalUrl` 均非空。

## 3. 给后端的边界建议（不是我要改的代码）

- 触发处补一条**环境守卫**：现在只有 `WEB_SEARCH_ENABLED` 这个软开关，建议在 `route_after_retrieval`
  或搜索入口处显式要求 `app_environment == "development"`，避免误开到生产。
- 每次联网命中都会调用 `vectorize_document`（`web_search.py:370,426`）→ 会走云端向量接口并写库
  （一次搜索最多 2–3 篇）。属费用与写库路径，文档里应点明。
- 抓取网页正文属「再单独设计」范围（限量、超时、版权、站点规则），本轮不做、也不做开放式爬取。

## 4. 前端改动清单（契约落地后动手）

1. 对话状态区：新增「正在检索」态（依赖契约 2）；保留并复核现有失败/为空/覆盖有限文案。
2. 来源区：每条来源显示`获取时间`（依赖契约 1）；联网来源的告警句强化为「联网资料，未经医学审核」；
   三态区分保持「审核来源 / 联网原型 / 开发原型」徽标 + 「无可靠依据」走状态文案。
3. 不新增任何输入框按钮（用户界面入口纪律），只复用现有状态区与来源组件。
4. 测试：单测覆盖新增状态与获取时间；e2e 覆盖加载、失败、来源标识、刷新历史对话后的显示；
   同步 `frontend/BROWSER_ACCEPTANCE.md` 的 1280px/375px 几何断言。

## 5. 未验证 / 待确认

- 未跑真实联网搜索、未跑真实前后端链路；`WEB_SEARCH_ENABLED` 在本机 dev 环境的实际取值、Tavily key
  是否配置，均**未查**（只核对了默认值与 `.env.example`）。
- 后端为工作树未提交版本，契约以 Codex 最终提交为准。
- 用户给的冻结题集尚未建立（常见病 / 陌生药名 / 含个人信息 / 急症 / 假冒官方域名 / 无结果六类）。