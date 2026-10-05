# 门户新闻前端规划（用户 2026-10-05 清单 → 前端部分）

> 分工：**前端 DSH / 后端 Codex**。本文只规划 `frontend/**`，后端来源核验与接入见
> `backend/docs/NEWS_SOURCE_EXPANSION.md`。结论先行：**让专区出现内容靠后端来源**；前端剩下的活
> 大多与「有没有内容」无关，可以先做完，等来源一到位就自动可用。

## 1. 现状核对（逐条对用户的清单）

| 用户要求（前端部分） | 现状 | 结论 |
| --- | --- | --- |
| 展示各专区新闻列表，并清楚区分「暂无新闻」与「尚未接入来源」 | 已做：`category_without_source` 空态 + `sourceCoverageKnown`（来源未带 `categories` 时退回保守文案「来源覆盖情况尚未核实」） | ✅ 已满足 |
| 显示标题、来源、发布日期、原文入口、「未经医学审核」标记 | 已做：`.card-meta` 给发布与获取两种时间、`.badge` 标「未经医学审核」、**标题本身**即原文链接（`target="_blank"` + `rel="noopener noreferrer nofollow"`） | ✅ 已满足 |
| 展示更新时间和来源失败状态 | 已做：`asOf`／`nextRefreshAt`／`.status-line`／`.source-status`（中文状态 + 圆点 + 受控错误码） | ✅ 已满足，可加强（见 F-P2） |
| 支持重试 | **未做**：后端只有「当天首次访问自动跑一轮」（`daily_auto_refresh` + `update_day` 租约），用户重复 GET 不会强制新一轮 | ❌ 需后端新接口（§3） |
| 支持分页或「加载更多」 | **未做**：接口已支持 `limit`（1–50，默认 20）与 `offset`，响应已给 `total`／`hasMore`；前端只请求首屏一页 | ❌ 可立刻做（F-P1） |
| 有中文译题时保留英文原题；无译题时如实显示原题，不伪装中文 | 已做：`titleZh` 优先、`.card-original` 显示「原题：…」、译题标「人工核对译题」或「机器翻译·未经医学审核」 | ✅ 已满足 |

结论：**前端已完成的正是「展示层」；空栏目空的原因是后端还没有对应专区的来源**。

## 2. 任务清单（按「不依赖后端」优先排序）

### F-P1 分页 /「加载更多」（无后端依赖）
- `frontend/src/api/news.ts`：`page(category, { limit, offset })`，默认 `limit=20`（接口上限 50）。
- `frontend/src/views/PortalView.vue`：`items` 改为**追加式**加载；新增 `loadingMore`／`hasMore`；
  切换分区或分类时重置 `offset` 并丢弃在途响应（复用已有 `latestRequest` 竞态守卫）；列表下方给
  「加载更多」与「已到底」两种状态；加载更多失败时**保留已加载条目**并给受控中文提示。
- 验收：首屏 20 条 → 点一次追加第 2 页且顺序稳定、无重复；切分区回到第 1 页；1280/375 均无横向溢出。

### F-P2 来源明细与「最后成功时间」（无后端依赖）
- `.source-status` 每条来源补「最后成功 {相对/绝对时间}」；失败来源同时显示受控错误码。
- 不复述原始错误正文（后端只给受控码），不给用户看抓取日志。

### F-P3 加载态与空态一致性（无后端依赖）
- 切分区时先显示加载态，避免在响应返回前闪现「暂无新闻」。
- 明确「尚未接入来源」「该分区暂无新闻」「来源失败」「正在更新」四种状态的优先级与文案，避免互相覆盖。

### F-P4「重试更新」——**前端已按契约实现（2026-10-05，桩验证，后端一落地即可用）**
- 前端：仅在 `status=failed/stale` 或某来源 `status=failed/stale` 时、在「来源状态」下方显示「重试更新」；
  点击后 POST，**立即返回**，随后按 2/3/5/5 秒退避轮询 `GET /news`（共约 15 秒），直到 `asOf` 前进；
  结果用受控中文说明（已开始更新 / 今天已更新过 / 正在更新 / 功能未开启 / 没等到新结果）。
- **接口未落地时的行为（与原计划不同，已按实现改）**：不再保留「禁用按钮」——禁用按钮是假入口，而且后端一上线
  还得再改前端。现在的做法是：**后端返回 404/405 时自动收起按钮**，并说明「服务端暂未开放手动重试，将在下次
  自动更新时重试」，后端接口一落地就自动可用，不需要再改前端。
- 不做：前端直接抓取、显示抓取过程、无限连点（以服务端限流为准）；`accepted=true` 只代表「已开始一轮」，
  前端不谎报完成，必须等 `asOf` 真的前进。

### F-P5 验收补齐（无后端依赖）
- 单测（Vitest）+ e2e（Playwright，1280/375）+ `frontend/BROWSER_ACCEPTANCE.md` 的几何断言同步。
- 真实有内容的联调放在后端来源接入之后，届时重新登记占用。

## 3. 与后端的契约

**已有且前端已使用**（依据 `backend/app/api/routes/news.py` 当前实现）：
`limit`／`offset`／`total`／`hasMore`、`asOf`／`nextRefreshAt`／`refreshing`、
`sourceStatuses[].{id,name,categories,status,lastSuccessAt,lastErrorCode}`、`items[].{title,titleZh,titleZhSource,sourceName,canonicalUrl,publishedAt,retrievedAt,medicalReviewed}`。

**新增请求（已写进 `COORDINATION.md` §6，待 Codex 确认）**：
- `POST /api/v1/news/refresh`（`CurrentUser`，无请求体）
- 响应 `202`：`{"accepted": bool, "reason": "started" / "already_ran_today" / "busy" / "disabled", "nextRefreshAt": "…Z" 或 null}`
- 同一更新日已跑过 → `accepted=false` + `already_ran_today`（**不伪造新一轮**）；沿用现有租约与后台任务，
  **不等待抓取完成**；服务端限流；**不新增任何自启动**。

## 4. 入口位置（按 `AGENTS.md`「界面入口位置纪律」，需用户确认）

- 「加载更多」：列表**下方**、随内容流；不做悬浮按钮、不进输入框。
- 「重试更新」：放在「来源状态」行内、紧随失败来源；不做全局按钮、不进输入框。
- 同一功能只保留一个入口；位置确认后同步 `frontend/BROWSER_ACCEPTANCE.md` 与 `COORDINATION.md` §7.2。

## 5. 前端明确不做

- 不判断专区相关性、不做条目级筛选与去重、不核验与接入来源、不抓取外网。
- 不把「综合动态」硬塞进某个专区（分区由后端 `category_scope` 与条目 `category` 决定）。
- 不自编摘要、不做翻译（`title_zh` 由后端或人工灌入；用户已决定暂不启用付费翻译）。
- 不承诺「每日更新」以外的更新频率，也不把「触发了刷新」写成「已是最新」。

## 6. 顺序

1. 现在就能做（不依赖后端）：F-P1 → F-P3 → F-P2 → F-P5。
2. 等后端：F-P4 的接口；以及「专区真正有新闻」所需的来源核验与接入（`backend/docs/NEWS_SOURCE_EXPANSION.md`）。