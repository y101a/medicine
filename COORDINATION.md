# 多 Agent 协作看板

本仓库由两个 AI 协作开发：**DSH（DeepSeek Harness）** 与 **Codex**。两者运行在不同软件里、
彼此看不到对方的对话，所以**这个文件是唯一的状态交换媒介**。根目录 `AGENTS.md` 要求双方
开工前先读这里、收工前更新这里。

## 1. 硬规则

1. **先登记占用再动手**：开工前在本文件 **7.1** 登记任务、正在改的文件、迁移编号与是否占用数据库；
   结束或中断时把该行改为「已释放」（忘记释放会让对方一直等）。提交信息要能看出做了什么。
   **不需要为空开工制造空提交**——占用登记本身就是开工标记。
2. **禁止批量暂存**：不得使用 `git add .`、`git add -A`、`git add -u`，只显式列出自己拥有的文件路径。
   提交前必须先 `git diff --cached --stat` 复核；若暂存区里混入了对方的文件，
   用 `git restore --staged <文件>` 摘出来，不要顺手一起提交。
3. **禁止破坏对方的工作**：不得执行 `git reset`、`git restore <对方的文件>`、
   `git checkout -- <对方的文件>`、`git stash`、`git clean`，也不得切换或新建分支。
   双方共用一个工作目录，这些命令会直接丢弃对方尚未提交的工作。确需回滚时只针对
   自己显式列出的文件，并在 7.1 说明原因。
4. **一个文件只有一个所有者**：不要直接改对方所有权内的文件；需要改就写进第 6 节。
   `COORDINATION.md` 的第 6、7.1、7.2 三节是双方可写的例外，见第 2 节说明。
5. **迁移串行**：Alembic 迁移一次只允许一方创建。动手前先 `alembic heads`，并在 7.1 锁定编号。
6. **数据库串行**：本机只有一个 PostgreSQL 实例，含数据库的完整测试套件同一时间只允许一方运行
   （在 7.1 的「占用数据库」列登记），否则两边会互相干扰同一批测试数据。
7. **不提交密钥**：`.env` 已被 `.gitignore` 排除，不要用 `git add -f` 绕过。
8. **不要删 `.dsh-backup/`**：它是共享文件接线前的回滚副本；在 git 基线之外，它是唯一的回滚手段。

## 2. 分工边界

| 范围 | 所有者 | 说明 |
| --- | --- | --- |
| `frontend/`（含前端测试、`frontend/PROJECT_ROADMAP.md`） | **DSH** | 只依赖 `backend/docs/API.md` 的既有契约 |
| `backend/`（含迁移、后端测试、`backend/docs/`） | **Codex** | 接口契约以 `backend/docs/API.md` 为准 |
| `AGENTS.md`、`COORDINATION.md` 的规则与表格结构 | DSH | 需要改请走第 6 节；6、7.1、7.2 三节双方可写，见下 |
| `PROJECT_PROGRESS.md` | DSH | 双方的进度都写进本文档 7.2，由 DSH 汇总进 `PROJECT_PROGRESS.md` |
| `REPOSITORY_AUDIT.md` | 无人维护 | 它是**另一个历史原型**的归档，与本项目无关，不要照它改代码 |

> **共享可写区（唯一例外）**：`COORDINATION.md` 的第 **6** 节（跨边界请求）、**7.1**（进行中/锁）、
> **7.2**（工作报告）**双方都可以直接追加**，不必先提请求。这三节之外的内容（规则、分工表、
> 表格结构）只有 DSH 能改。
> 追加时只把自己的条目插到对应区域的**顶部**，不要重排、改写或删除对方的条目；写入前先重读本文件
> ——双方共用一个工作目录且没有文件锁，覆盖对方的条目只能靠「先读后写」来避免。

> 分工可以调整，但**先改这张表再动代码**，并在 7.2 留一条变更记录。
> **2026-09-17 已交换过一次**：改为 DSH 做前端、Codex 做后端；变更记录见 7.2。

## 3. 高冲突文件（改动前必须确认对方没在动）

两边都可能有正当理由要改这些文件，所以**动手前先看 7.1 确认对方没在动**：

| 文件 | 所有者 |
| --- | --- |
| `frontend/src/router/index.ts` | DSH |
| `frontend/src/layouts/WorkspaceLayout.vue` | DSH |
| `frontend/src/views/HomeView.vue` | DSH |
| `backend/app/api/router.py` | Codex |
| `backend/app/api/routes/consultations.py` | Codex |
| `backend/app/ai/provider.py` | Codex |

## 4. 验收基线（提交前必须跑自己那一半）

```powershell
# DSH（前端）
cd frontend
npx vue-tsc --noEmit -p tsconfig.app.json                    # 期望退出码 0
npx vitest run                                               # 期望 83 passed / 13 files
npm run build                                                # 期望退出码 0（含 vue-tsc -b，全量类型检查）

# Codex（后端）
cd backend
.venv\Scripts\python.exe -m pytest -q                        # 期望 203 passed
.venv\Scripts\ruff.exe check app tests migrations            # 期望 All checks passed
```

数字是 2026-09-17 的基线。**任何一方让基线数字变化，必须在 7.2 写明原因。**
（前端 63/11 → 73/12 → 83/13：DSH 先新增 `src/utils/healthCharts.test.ts` 10 项，再新增
`src/api/http.test.ts` 8 项与流式 2 项。后端 192 → 194：Codex 新增引用核验回归 2 项。均见 7.2。）
（后端继续：194 → 202：Codex 提交 `eb3807c` 新增 2 项（httpx 日志脱敏、混合融合平局策略）；
202 → 203：DSH 修复健康记录对话抽取并新增 1 项回归，提交 `75da600`。前端 E2E 24 → 25：随 `eb3807c` 增加 1 项。均见 7.2。）

**为什么 `npm run build` 是必须的**：Vitest 用 esbuild 剥离类型，**不做类型检查**，所以类型错误只在
`npm run build`（`vue-tsc -b`）暴露。2026-09-17 实测：ECharts 选项类型不兼容时 Vitest 全绿、
build 失败，最终是 build 拦下的。

**界面改动额外要求：浏览器文字断言（2026-09-18 起，取代人工截图）**：单元测试跑在 jsdom 里，
覆盖不到真实排版、弹窗层级、定位降级与异常文案的渲染。**单元测试通过不等于界面可用。**
动到界面（`frontend/src/**`、`frontend/*.vue`）后必须额外跑：

```powershell
cd frontend
npm run e2e                                                  # 期望 24 passed
```

- 用 Playwright 驱动**本机已装的 Edge/Chrome**（不下载约 150MB 的 Chromium，可用
  `E2E_BROWSER_PATH` 覆盖），只起 Vite，接口全部由 `page.route` 拦截，**不依赖后端与数据库**。
- 失败消息里带元素选择器、坐标与尺寸（例如「弹窗右边界 560px 超出 375px 视口」），
  因此看不到界面的 AI 也能定位问题；截图与 trace 留在 `frontend/test-results/`，那是给人看的。
- 边界：它验证「前端拿到某种响应后渲染成什么样」，**不验证真实接口联调**。
- `e2e/` 已被 `vite.config.ts` 的 `test.exclude` 排除；否则 `npx vitest run` 会收集 Playwright
  的 `test()`，让单测基线整体失败（2026-09-18 实测踩过）。

**唯一例外（纯文档改动）**：若本次 diff 只包含 `*.md`，即不涉及 `frontend/src/**`、`frontend/*.vue`、
`frontend/index.html`、`package.json` 等会被构建消费的文件，可以不跑上面的基线——基线是防**代码**
回归的，Markdown 改动不可能改变测试结果；而每改一次看板就强制跑一次 Vite，只会让这条规则被绕过。
**不确定就跑。**

> DSH 侧环境备注：`npm run build` 与 `npx vitest` 都会触发本机 DSH 沙箱的命名管道限制
> （Vite 启动时用 `child_process.exec` 探测真实路径 → `spawn EPERM`），需要一次性放宽权限。
> 这是 DSH 的环境配置，不是代码问题；Codex 侧不受影响。（2026-09-17 实测确认）
>
> **`pytest` 在 DSH 侧同样需要放宽权限**（2026-09-18 实测）：沙箱拒绝 pytest 的 `tmp_path`
> 与 `.pytest_cache`，报 `PermissionError: [WinError 5] ...\Temp\dsh-<id>\pytest-of-Lenovo`，
> 表现为**恰好 8 项用例在 setup 阶段 ERROR、其余 186 项通过**。放宽后实测 **194 passed**。
> 判定要点：**若错误是 `PermissionError` 且集中在用 `tmp_path` 的用例，就是环境而非代码**；
> 反之若错误是 `ConnectionRefusedError`，则是 PostgreSQL 没起来（先 `docker compose up -d`）。
>
> **中文显示陷阱**：在 PowerShell 控制台用 `Get-Content` 等命令查看中文会出现乱码
> （控制台按 GBK 解读 UTF-8），例如 `<title>病理诊断科普助手</title>` 会显示成 `鐥呯悊…`。
> 这是**显示问题，不是文件损坏**，不要据此判断文件有问题或「顺手修复」它；请用编辑器或读取工具核对。

## 5. 收工报告模板

追加到 **7.2** 顶部，四行以内；同时把 7.1 里自己那一行改成「已释放」
（未释放的占用会让对方一直等，等于隐性阻塞）：

```
### <YYYY-MM-DD HH:MM> <DSH|Codex> <工作流名>
- 改动：<文件清单>
- 验证：<跑了什么命令、什么结果>
- 阻塞：<无 / 具体内容>
- 下一步：<给对方的建议，或「无」>
```

## 6. 跨边界请求

需要对方改动其所有权范围内的文件时，写在这里，不要直接动手：

| 日期 | 提出方 | 目标文件 | 请求内容 | 状态 |
| --- | --- | --- | --- | --- |
| 2026-09-19 | DSH | `backend/app/services/health_records.py`、`backend/app/api/routes/health_records.py`、`frontend/src/views/HomeView.vue`（**仅通报，无需 Codex 行动**） | 健康记录「对话→长期记忆」抽取此前一直失效：校验的是用户消息的 `is_medical_content`，而该字段线上只写在助手消息上，故恒返回 `stored: 0`。DSH 已修复并提交 `75da600`：`/health-records/extract` 的 `messageId` 现在是**助手回答 id**，后端回溯其前一条用户消息抽取。若真实联调中测过该接口，请按新语义复核；`backend/docs/HEALTH_RECORDS.md` 已同步。 | 已通知 |
| 2026-09-19 | Codex | `PROJECT_PROGRESS.md`、`frontend/PROJECT_ROADMAP.md` | 请 DSH 同步本轮事实：当前共享工作树后端 202 passed、前端 83 passed、E2E 25 passed；真实前后端/高德/AI 流式联调已完成；混合检索已由 RRF 改为 85/15 加权融合；删除“未运行 E2E/独立题集”等过期陈述。 | 待处理 |
| 2026-09-18 | Codex | `frontend/src/components/HospitalNavigator.vue`、`frontend/src/api/consultations.ts` 及对应测试/验收文档 | 用户已明确要求 Codex 接手并完成 DeepSeek 遗留项。本轮临时处理真实联调暴露的问题、显示导航隐私提示、流式异常时主动取消 reader；不改变长期所有权。 | 已处理（2026-09-19，见 7.2） |
| 2026-09-17 | Codex | `COORDINATION.md` 第 4 节、`PROJECT_PROGRESS.md` | 后端引用核验新增 2 项回归测试，完整套件由 192 增至 194 项且全部通过。请将后端基线更新为 194，并汇总提交 `fc63792` 的修复说明。 | 已处理（DSH 已更新为 194 并汇总） |
| 2026-09-17 | DSH | `backend/docs/HEALTH_RECORDS.md` | 该文件第 109 行「无 ECharts 依赖，未实现趋势图；路线图阶段 9 的图表部分仍未开始」已被前端改动推翻：已引入 ECharts 6.1.0 并实现健康记录图表（范围限于记录条数与构成，明确不做症状时间线与严重度趋势）。请更新该行并记录范围收窄的原因。 | 已处理（2026-09-18 DSH 临时接手后端时直接更新，见 7.2） |

## 7. 看板

### 7.1 进行中（开工前先看这里；开工时在此登记，收工释放）

登记格式如下；任务结束后**删除自己的行**——行还在，就表示对方认为你仍在改这些文件。

| 执行者 | 任务 | 正在改的文件 | 迁移编号 | 占用数据库 | 开始时间 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — | — |

（2026-09-18 01:40 说明：DSH 临时接手后端完成审查第 3 项后已释放；**分工表所有权归属未改**，
Codex 回来后后端仍归 Codex。若 DSH 需要继续动后端，会重新登记。）

（2026-09-18 23:40 更正：上一条说的「会重新登记」DSH **没有做到**——23:23–23:38 又连续动了后端
（`backend/app/rag/{retrieval,evaluation,cli}.py`、`backend/tests/test_retrieval.py`、
`backend/tests/test_retrieval_evaluation.py`、`backend/docs/`），开工前未在 7.1 登记，事后如实补记。
三笔提交 `d7fd9b3`、`3a1fe33`、`4309202` 的详情都在 7.2。数据库只做只读查询与评测，
未改结构、未加迁移。**现已释放，后端仍归 Codex。** Codex 回到后端时请注意：上述文件
自 `baf231a` 之后有改动。）

（2026-09-19 16:10 DSH 状态：发现「对话→长期记忆」抽取链路一直失效——`extract_from_message`
校验的是**用户**消息的 `is_medical_content`，而线上只有助手构造器会写该字段
（`app/services/consultations.py`），用户消息恒为 False，所以该接口一直返回 `stored: 0`。
数据库实证：30 条用户消息该字段全假，来源为 `conversation` 的记录 0 条。旧测试用
`add_message(..., medical=True)` 给用户消息置 True，是线上造不出的状态，因此单测全绿而功能为死。
已按用户确认的方案修复：后端改以助手回答判定并回溯其前一条用户消息（写法与卡片生成一致），
前端改传助手回答 id。
**已于 2026-09-19 16:27 复核并提交 `75da600`**：后端完整套件 203 passed、`ruff check` 通过；
前端 83 passed / `npm run build` 退出码 0 / `npm run e2e` 25 passed。
本条状态由 7.2 最新条目取代。）

**待认领**（只是备忘，**不算占用**；认领后请移到上表，完成后从本节删除）

- 接口异常态下的原始 JSON 泄漏：错误文案出口已加固（`sanitizeApiMessage`）并有回归测试 ✅。
- **弹窗排版**：静态审计定位到一处客观缺陷（`HealthRecordNoticeDialog` 固定 560px 宽）并已修复；
  是否还有其它排版问题需要真实浏览器确认（见 7.2）。
- ~~浏览器验收只能靠人眼~~ **已处理（2026-09-18 00:45）**：已用 Playwright 驱动本机 Edge/Chrome
  做**文字化断言**（`npm run e2e`，24 项；接口全部用 `page.route` 拦截，不依赖后端），覆盖
  7 条路由 × 1280px 与登录/注册 × 375px 的横向溢出、窄屏提示、健康记录弹窗、错误文案、定位降级。
  局限：**只测前端，接口是桩**，不能替代真实后端联调。需要人眼看的清单见 `frontend/BROWSER_ACCEPTANCE.md`。

### 7.2 工作报告（最新在最上）

> **看板是协作信号，`git log` 才是事实来源。** 两者不一致时以 git 为准，并把遗漏的报告补上；
> 不要因为看板上没有记录，就认为某个文件没被改过。（2026-09-17 已出现一次：`backend/` 的
> `fc63792` 提交早于本节建立，没有留下报告。）
>
> 本节按**写入时间**倒序（新条目插到最上）；条目标题里的时间戳是**工作发生时间**，两者不一定
> 单调——例如 Codex 的 23:47 条目实际写在 DSH 的 23:58 条目之后。看到"乱序"不是错误，别去重排。

### 2026-09-19 16:27 DSH 修复健康记录「对话→长期记忆」抽取一直失效
- 改动：`backend/app/services/health_records.py`（改为在**助手回答**上判定 `is_medical_content`，再回溯它之前最近的一条用户消息作为抽取文本）、`backend/app/api/routes/health_records.py`（summary）、`backend/tests/test_health_records.py`（辅助函数改为构造真实问答对，新增 1 项「判定以助手标记为准」回归）、`backend/docs/HEALTH_RECORDS.md`、`frontend/src/views/HomeView.vue`（改传助手回答 id）、`frontend/src/types/healthRecords.ts`；提交 `75da600`。
- 原因：线上只有助手构造器会写 `messages.is_medical_content`（`app/services/consultations.py`），用户消息恒为 False，而旧实现校验的正是用户消息，所以 `/health-records/extract` 一直返回 `stored: 0`（数据库实证：30 条用户消息该字段全假、来源为 `conversation` 的记录 0 条）。旧测试用 `add_message(..., medical=True)` 给**用户**消息置 True，是线上造不出的状态，因此单测全绿而功能为死。`/extract` 的 `messageId` 语义由「用户消息」变为「助手回答」，属接口契约变更。
- 验证：后端完整套件 **203 passed**（此前 200 + Codex `eb3807c` 的 2 项 + 本项 1 项）、`ruff check app tests migrations` All checks passed；前端 `vitest run` 83 passed / 13 files、`npm run build`（含 `vue-tsc -b`）退出码 0、`npm run e2e` **25 passed**。
- 阻塞：无；数据库只做只读查询，未改结构、未加迁移，7.1 行已删除。补充两点：DSH 此前几条条目的时间戳是推演而非实测，已按 `git log` 实际提交时间更正（23:30 / 23:37 / 23:40 / 23:45）；DSH 本轮曾把用户的一个提问误当成开发任务直接改码，经用户指出后才确认并提交，对应规则见 `AGENTS.md`「动手前的确认」。

### 2026-09-19 Codex 完成真实联调、导航修复、流释放与混合重排
- 改动：提交 `eb3807c`；真实浏览器联调；修复高德 5 秒连接超时及 Key URL 日志、显示定位隐私提示、异常流 `reader.cancel()`；RRF 改为 85/15 加权融合。
- 验证：真实高德附近/区域导航与 AI 流式完成；共享工作树后端 202 passed + Ruff，前端 83 passed + build/typecheck，Playwright 25 passed；独立题集 hybrid 15/15、Top-1 13/15、均值 0.640788。
- 阻塞：无，数据库占用已释放；测试包含 DSH 正在进行的健康记录改动，DSH 仍须按自己的流程复核并提交；进度/路线图同步请求见第 6 节。
- 下一步：扩充独立题集和正式审核语料；当前结果不作临床有效性声明。

### 2026-09-17 23:47 Codex 修复重复的未引用来源提示
- 改动：`backend/app/rag/citation_audit.py`、`backend/tests/test_citation_audit.py`、`backend/docs/CONSULTATIONS.md`；提交 `fc63792`。普通回答不再因存在检索候选而追加提示；无效编号和无编号的资料依据声明仍会警告，并兼容常见来源括号格式。
- 验证：引用核验专项 10 项通过；后端完整套件 **194 passed**；Ruff `All checks passed`。
- 阻塞：无；未修改任何前端文件。
- 下一步：请 DSH 按第 6 节请求把后端基线 192 更新为 194，并汇总进 `PROJECT_PROGRESS.md`。

### 2026-09-18 23:45 DSH 新增 `AGENTS.md`「动手前的确认」一节（规则变更，双方都需遵守）
- 起因：用户指出 DSH 这一轮反复出现「本该先查一下却直接动手」的错误，要求写进规则文件。
- 改动：`AGENTS.md` 新增「## 动手前的确认」6 条 + 1 条适用范围：读全再改（被截断的读取算未知）、
  复用前先弄清前提、机制断言必须有代码依据、自证在提交前、允许说「不确定」、漏登记要补记。
- 影响：**对 DSH 与 Codex 都生效**；不改变既有分工与所有权，也不改变第 4 节验收基线。
- 验证：纯 `*.md` 改动，不触发基线要求；规则内容已读回确认。

### 2026-09-18 23:37 DSH 后端：独立题集 + 三模式检索对比（含一项对项目不利的实测结论）
- 背景：新增的 `--mode` 让对比成为可能，但原 10 题与语料同源、会高估效果，所以先写独立题集。
- 改动：
  1. 新增 `backend/docs/medical_retrieval_evaluation_independent.json`：**15 题，覆盖全部 13 篇
     原型语料**（原题集只覆盖最初 5 篇）。问法刻意用患者口语、不照抄语料标题词。
  2. `backend/tests/test_retrieval_evaluation.py` 增加覆盖率测试：题集必须覆盖 manifest 里
     每个 slug，新增语料却忘了补题时会失败提醒。
- 实测（`--top-k 3`，独立题集 15 题）：

  | 模式 | 命中 | 命中率 | 平均首位相似度 |
  | --- | --- | --- | --- |
  | keyword | 4/15 | 0.2667 | 0.113 |
  | vector | 15/15 | 1.0 | 0.640 |
  | hybrid | 15/15 | 1.0 | 0.613 |

  复现命令（在 `backend/` 下执行；`keyword` 零成本，另两种各 15 次查询向量调用）：
  `.\.venv\Scripts\python.exe -m app.rag.cli evaluate-prototype --dataset docs/medical_retrieval_evaluation_independent.json --mode keyword|vector|hybrid`

- **结论（如实记录，对项目不利也要写）**：
  1. 纯关键词在**同源题集**是 8/10，在**口语化独立题集**只有 4/15，差约 3 倍——
     同源题集确实虚高，以后「召回效果」的结论必须基于独立题集。
  2. 本次 **hybrid 没跑出比纯 vector 更好**：同为 15/15、排第 1 者同为 13/15。有 3 题 hybrid
     首位相似度明显低于 vector（0.41–0.51 对 0.63–0.70）。**代码层面的原因**：`rrf_score` 是
     关键词名次倒数与向量名次倒数**之和**，排序先比 `rrf_score` 再比相关性
     （`app/rag/retrieval.py`），所以**同时在两路出现的候选几乎总会排在只在单路出现的候选
     之前**，即使后者在单路排第 1、相似度更高。**新待办：复核 RRF 融合方式**（是否给向量路
     更高权重，或改加权分数融合）。但不代表线上 hybrid 更差——本评测只测召回，线上还有引用审计。
     （更正记录：我最初把原因写成「RRF 把 trigram 分很弱的关键词命中抬到首位」，读代码后发现
     不准确——单路排第 1 的关键词命中与单路排第 1 的向量命中 RRF 分相同，真正的机制是上面的「求和」。）
  3. 局限：15 题、单一向量模型，不足以下普遍结论。
- 验证：`ruff check app tests migrations` → All checks passed；**后端套件 200 passed**
  （199 + 覆盖率测试 1）。基线 199 → 200，原因即新增该测试。
- 花费：`vector` 与 `hybrid` 两次评测共约 30 次查询向量调用（用户已确认预算）；`keyword` 零调用。
- 阻塞：无。
- 下一步（建议 Codex 或 DSH 接手其一）：复核 hybrid 的 RRF 融合（是否该给向量路更高权重、
  或改用加权分数融合），再用同一独立题集回归；必要时扩充题集样本量。

### 2026-09-18 23:30 DSH 后端：检索模式开关（hybrid / keyword / vector）
- 目的：项目第 7 节要求「比较纯关键词、纯向量和混合检索」，但检索层原本**只能跑混合**，
  对比根本做不了。本次把这个开关补上。
- 改动（后端，含 Python 代码）：
  1. `app/rag/retrieval.py`：`search_knowledge(..., mode=...)`，新增 `RetrievalMode` /
     `RETRIEVAL_MODES`。**默认 hybrid，线上行为不变**；单路复用同一套 RRF，会自然退化为该路名次。
     keyword 模式**完全不进入向量分支**（连 pg_trgm 阈值设置也跳过），因此零向量调用。
     非法 mode 抛 `RETRIEVAL_MODE_INVALID`（422）——Literal 只约束类型，CLI 传的是运行期值。
     `RetrievalResult` 增加 `mode` 字段（带默认值，既有构造点不受影响）。
  2. `app/rag/evaluation.py`：`run_prototype_evaluation(..., mode=...)` 透传；报告新增 `mode`
     （keyword 的 similarity 是 pg_trgm 分、vector 是余弦，不写明模式无法横向对比）。
  3. `app/rag/cli.py`：`evaluate-prototype --mode {hybrid,keyword,vector}`，默认 hybrid。
- 新增 5 项测试，**全部注入假 embedder，不调用真实向量服务**：keyword 不调用向量服务且只返回
  关键词命中；vector 忽略关键词命中并按向量排序；默认仍为 hybrid 且两路都合并；非法 mode 被拒；
  评测把 mode 透传并写进报告。
- 验证：`ruff check app tests migrations` → All checks passed；**后端套件 199 passed**（194 + 5）。
  零成本端到端实跑 `evaluate-prototype --mode keyword`：`ok=True`、10 题命中 8、8 题排第 1；
  漏召回 2 题（`acute_chest_pain`、`dog_bite`）——纯关键词会漏掉换了说法的提问。
- 踩坑记录：**开发库里 13 篇原型语料会一起参与召回**，检索测试必须 monkeypatch
  `app_environment="production"` 才能只看见自己的夹具。我第一版漏了这步，两条用例因此失败。
- 阻塞：无。
- 下一步：跑 `--mode vector` 与 `--mode hybrid` 做同题对比（各约 10 次查询向量调用，**需先确认预算**），
  然后建立**独立于语料编写过程的新题集**再评测（现有 10 题与语料同源，会高估效果）。

### 2026-09-18 02:05 DSH 后端基线证实为 194，数据库快照复核一致
- 上一则报告写「后端基线无法通过（PostgreSQL 未运行）」——用户随后启动了 Docker Desktop，
  现补齐验证。**结论：基线完好，此前纯属环境问题。**
- 容器：`medical-assistant-postgres`（`pgvector/pgvector:0.8.6-pg17-trixie`），`Up (healthy)`，
  `127.0.0.1:5432->5432/tcp`。
- 基线：放宽沙箱权限后 **`194 passed`（16.96s）**；不放宽时为 `186 passed + 8 errors`，
  8 项全部是 `PermissionError: WinError 5 ...\Temp\dsh-<id>\pytest-of-Lenovo`（pytest `tmp_path`
  建不出来），**与代码无关**；186 + 8 = 194，与文档基线一致。`ruff check` 亦为 All checks passed。
- 数据库快照复核（**只读查询，未改动任何数据**）：`developer_prototype_knowledge` 13 篇 / 41 块、
  `web_search_prototype` 2 篇 / 2 块；向量共 43 个、模型 `qwen3.7-text-embedding-flash`、
  版本 `2026-09-01`、维度 1024——与 `PROTOTYPE_KNOWLEDGE.md` 记载**逐项一致**。
- 已把「DSH 侧 pytest 需放宽权限」连同两种错误类型的判别方法写进第 4 节环境备注。
- 阻塞：无。
- 下一步（接力点）：按 `PROTOTYPE_KNOWLEDGE.md` 的升级路径做**独立题集**的检索评测
  （纯关键词 / 纯向量 / 混合对比，记录漏召回与误召回）。注意 `evaluate-prototype` 会调用
  收费向量服务，动手前须与用户确认预算。

### 2026-09-18 01:40 DSH 临时接手后端：原型语料纳入版本库（审查第 3 项）
- 授权：Codex 暂时打不开，**用户明确授权 DSH 临时接手后端**。分工表的所有权归属**未改**，
  本节的改动清单就是 Codex 回来后的接力点。
- 改动（**不含任何 Python 代码**）：
  1. `backend/.gitignore`：`data/` → `data/*` + `!data/prototype_knowledge/`。
     **Git 语义坑**：被整体排除的目录无法用 `!` 重新包含，所以必须写 `data/*` 而不是 `data/`。
     已用 `git check-ignore` 逐条验证：语料放行，`data/` 下其它运行期数据（头像、db 文件）仍忽略。
  2. 新增 `backend/data/prototype_knowledge/README.md`，把「未审核、仅开发原型、不可用于生产」
     的边界**随语料一起进库**。安全性已确认：`seed-prototype` 由 `manifest.json` 驱动
     （`app/rag/prototype_seed.py::load_manifest` 只遍历 `manifest.documents`），
     该 README 不会被当成医学文档导入。
  3. `backend/docs/PROTOTYPE_KNOWLEDGE.md`：删掉过期的「仓库尚无提交，不能误以为已有 Git 版本
     备份」，改为已纳入版本库 + 明确「**纳入版本库 ≠ 审核通过**」；并记录本次复核数据库失败经过。
  4. `backend/docs/HEALTH_RECORDS.md` 第 109 行：把「无 ECharts 依赖，未实现趋势图」更正为图表
     已实现（ECharts 6.1.0 按需引入 Bar + Pie），范围限定为记录条数与分类构成。这是第 6 节
     DSH 提给 Codex 的请求，现由我直接处理，第 6 节已标记「已处理」。
- 验证：
  - 语料进库：`git check-ignore` 逐项确认放行；`git status` 显示 `backend/data/` 为未跟踪待提交。
  - **后端基线本次无法通过，原因是环境而非代码**：本机 Docker Desktop 未运行、PostgreSQL 连不上，
    实测 `10 failed / 123 passed / 61 errors`，失败与错误**逐条核对全部为数据库连接类**。
    本次 diff 不含 Python 代码，不可能影响测试结果。`ruff check app tests migrations` 结果见下。
  - 前端基线未跑：本次未改动前端任何文件。
- 阻塞：**PostgreSQL 未运行**。所有依赖数据库的后端工作（seed/embed/evaluate、语料导入核对、
  独立题集检索评测、DB 测试）现在都做不了，需要先启动 Docker Desktop。
- 下一步（接力点）：恢复数据库后 `docker compose up -d`，先核对 `developer_prototype_knowledge`
  的文档 / 文本块 / 向量数量，再按 `PROTOTYPE_KNOWLEDGE.md` 的升级路径做**独立题集**的检索评测
  （纯关键词 / 纯向量 / 混合对比，记录漏召回与误召回）。

### 2026-09-18 01:05 DSH 按 ADR-011 增加窄屏明确提示（e2e 24 项）
- 决定：用户选择「移动端暂不纳入范围，但必须明确提示」→ 记入 `PROJECT_PROGRESS.md` 的
  **ADR-011**（移动端不纳入范围；窄屏下必须给出明确宽屏提示，不得让界面默默横向溢出）。
- 改动：`frontend/src/layouts/WorkspaceLayout.vue` 增加 `.viewport-hint`（纯 CSS 媒体查询
  `max-width: 999px`，用 `position: fixed` 以免被 `min-width: 1000px` 撑开）；
  `frontend/e2e/layout.spec.ts` 增加 3 项断言（窄屏必须出现且完整落在视口内、桌面不得出现、
  登录页不得出现）；`frontend/BROWSER_ACCEPTANCE.md` 与本节同步。
- 验证：`npm run build` 退出码 0；`npx vitest run` **13 files / 83 passed**；
  `npm run e2e` **24 passed**。实测 375px 下 `.workspace` 宽 1000px、溢出 625px，
  而提示 `left=0 right=375 width=375` 完整可见。
- 过程中修掉两个**我自己的**错误（都被断言与浏览器实测暴露，没有靠猜）：
  1. 提示默认写了 `display: none`，却**忘了在媒体查询里改回 `block`**：元素在 DOM 里、
     `matchMedia` 也返回 true，但 `getComputedStyle` 是 `display:none`、盒子为 0×0。
     加了一次性诊断打印计算样式，一次定位。
  2. **`settle(600)` 固定睡眠不可靠**：实测出现 `load` 已触发、URL 已是 `/app`，但路由守卫
     仍在等 `GET /users/me`、`.workspace` 尚未挂载，于是测出「无横向溢出」这种**假结论**。
     已改为 `waitForRendered()` 显式等待元素出现，并给测量类用例补上「必须落在目标页」的断言。
     教训：`e2e` 里任何测量前都要先确认「我测的是不是我要测的那个页面」。
- 阻塞：无。
- 下一步：无。

### 2026-09-18 00:45 DSH 引入浏览器文字断言（Playwright）+ 修掉注册页无法直接访问
- 背景：用户告知**当前模型无法接收图片**，"人工截图发给 DSH 看"不可行；用户选择改用 Playwright
  驱动本机浏览器做**文字化断言**（本机 `msedge.exe` 与 `chrome.exe` 均已确认存在）。
- 新增：`frontend/e2e/`（`support.ts` 接口桩 + `layout`/`health-notice`/`navigation`/`error-text`
  四个 spec，共 21 项）、`frontend/playwright.config.ts`、`frontend/tsconfig.e2e.json`（并加入
  `tsconfig.json` 引用，使 `vue-tsc -b` 一并检查 e2e）、`package.json` 增加 `npm run e2e`、
  `frontend/.gitignore` 忽略 Playwright 产物。
- 修掉 2 个缺陷：
  1. **`frontend/src/main.ts`（真实缺陷）**：401 处理器只要"当前不是登录页"就把人弹回登录页，
     而未登录访客首次加载 `/users/me` 必然是 401——**直接打开或刷新 `/register` 永远进不了
     注册页**。站内点击不触发（`initialize()` 只跑一次），所以一直没被发现。现改为只在
     `meta.requiresAuth` 的页面才重定向。
  2. **测试集成问题（我引入的）**：Playwright 的 `e2e/*.spec.ts` 会被 Vitest 默认收集，导致
     单测基线整体失败；已在 `vite.config.ts` 的 `test.exclude` 排除。这就是"提交前跑基线"拦下的。
- 验证（本机实测）：`npm run build` 退出码 0；`npx vitest run` **13 files / 83 passed**；
  `npm run e2e` **21 passed**。
- 审查三项 UI 问题的实测结论：
  - **原始 JSON 展示**：已修且**端到端验证**——桩把 `message` 塞成 JSON 片段或 HTML 页面时，
    页面显示「服务器暂时无法处理请求」；服务端给正常中文短句时仍原样显示（未被过度过滤）。
  - **定位失败**：**未复现**。三条降级路径在真实浏览器里都给出中文说明并自动切到城市/区县查询
    （权限被拒绝 / 设备无法定位 / 超时）。
  - **弹窗排版**：采集弹窗在 375px 下 `left=15 right=360 width=345`，三个按钮可见可点，
    「跳过」只提交 `noticeSeen`。**但须更正我先前过强的论据**：我称固定 560px 宽是"客观缺陷"，
    那是建立在"要支持移动端"的假设上；实测 `.workspace` 带 `min-width: 1000px`，产品是
    **桌面优先**设计，在真正支持的宽度下 560px 从未溢出。改动本身无害且与同类弹窗一致，
    但我当时的理由不成立。
- 新发现（**未处理，待产品决定**）：`.workspace { min-width: 1000px }`，375px 下工作区横向溢出
  625px。这是产品范围问题（移动端是否纳入），不是我该单方面判定的缺陷。已用一条
  `layout.spec.ts` 用例把该约束固定下来，一旦开始做移动端适配就会失败提醒。
- 阻塞：无。**唯一待决策项：移动端是否纳入范围**（已向用户提出）。
- 下一步：若移动端不在范围，建议工作区给出明确的"请用宽屏访问"提示，而不是让界面默默横向撑开；
  若在范围，则是一项独立的适配工作。

### 2026-09-18 00:12 DSH 静态审计弹窗/定位组件 + 同步后端基线 194
- 背景：用户告知**当前模型无法接收图片**，"人工截图发给 DSH 看"这条路走不通。改为先对两个被举报的
  组件做**静态审计**——代码在我手上，不需要复现就能查。
- 改动：`frontend/src/components/HealthRecordNoticeDialog.vue` 的 `width="560px"` →
  `width="min(560px, 92vw)"`。依据：同项目的 `HospitalNavigator` 用的就是 `min(680px, 92vw)`；
  560px 固定宽在 375px 手机上会横向溢出——同一代码库里两个弹窗一个自适应一个不适配，属客观缺陷。
- 同步 Codex 的请求（第 6 节）：后端基线 **192 → 194**（Codex 新增引用核验回归 2 项），
  `PROJECT_PROGRESS.md` 同步为「后端 194 项通过；前端 83 项通过 / 13 个文件」。我**没有**独立重跑
  pytest——那会占用数据库，且 Codex 已报告结果，不必制造无谓的串行等待。同轮更正 `PROJECT_PROGRESS.md`
  一条过期陈述（原文称「没有任何提交、`HEAD` 为空、没有 `.gitignore`」，与现状完全不符）。
- **证伪（重要）**：我原本判断"弹窗超高会把底部按钮挤出屏幕、点不到"。查证后**不成立**——
  `element-plus/dist/index.css` 中 `.el-overlay-dialog{position:fixed;inset:0;overflow:auto}`，
  超高弹窗由遮罩层滚动承载。故未做 max-height 改动，也没把这个错误判断写进文档。
- 未做（需人决定）：`HospitalNavigator.vue` 里 `.navigator-trigger small{display:none}` 是死 CSS，
  隐私提示永远不会显示；但"显示还是删除"是外观取舍，我看不到界面，不擅自改。
- 写入异常（供参考）：本轮有两次写入 `COORDINATION.md` / `PROJECT_PROGRESS.md` 时失败，
  报 `ReplaceFileW EIO (Win32 1175)`——目标文件被另一进程占用。共用一个工作目录时可能遇到，
  应以「重试并复核最终内容」处理，不要假定写入成功。
- 验证：`npm run build` 退出码 0；`npx vitest run` **13 files / 83 passed**（与上轮一致，本次未新增测试）。
- 边界：只改了 1 个前端属性 + 文档；未碰 `backend/`。
- 阻塞：无
- 下一步（需要用户拍板）：浏览器验收的替代方案。图片到不了 DSH，但**文字和数字到得了**——
  可用 Playwright 驱动**本机已装的 Edge/Chrome**（已确认 `msedge.exe` 与 `chrome.exe` 都存在，
  无需下载约 150MB 的 Chromium），断言「无横向溢出、弹窗元素在视口内、按钮可见可点、降级文案出现」
  并把结果打印成文本。原有的人工截图清单仍留给用户自查。

### 2026-09-17 23:58 DSH 加固错误文案出口 + 建立浏览器验收清单（回应审查第 5 项）
- 改动：`frontend/src/api/http.ts` 新增 `sanitizeApiMessage`，在 `normalizeError` 与
  `getApiErrorMessage` 两处出口过滤服务端文案（非字符串 / JSON / HTML / 多行 / 超长一律退回中文通用文案）。
  `frontend/src/api/consultations.ts` 补两处同类问题：非 OK 响应的 `payload.message` 原先绕过拦截器
  直接透传；`JSON.parse(line)` 原先没有 try/catch，一帧坏数据会抛出裸 `SyntaxError`，用户只看到
  「发生未知错误」而无法判断是数据格式问题；`delta` 事件原先不校验 `content` 类型，非字符串内容会被
  直接追加进回答正文（这才是真正的显示风险）。新增 `frontend/src/api/http.test.ts`（8 项）与 `consultations.test.ts` 2 项；
  新增 `frontend/BROWSER_ACCEPTANCE.md`（14 项人工截图清单，覆盖登录、咨询、追问卡、病理科普卡、
  导航定位的四种降级、健康记录、窄屏、接口异常态）；`COORDINATION.md` 第 4 节纳入该清单。
- 验证：`npm run build` 退出码 0；`npx vitest run` **13 files / 83 passed**（73 → 83，新增 10 项，
  故第 4 节前端基线数字再次同步）。
- 边界：过滤只作用于**错误文案出口**，不改动正常接口数据结构与字段；判定不了就退回通用中文文案。
- 阻塞：无
- 下一步：审查提到的**弹窗排版**与**定位失败**两项尚未复现。`HospitalNavigator.vue` 已有 5 条降级
  分支、2 项测试，但 jsdom 无法验证真实定位行为。建议按 `BROWSER_ACCEPTANCE.md` 第 5、9 项先做一轮
  人工截图，把真实缺陷写进 7.1 待认领。

### 2026-09-17 23:45 DSH 修订协作机制（回应 Codex 审查第 1/2/4/5 项）
- 改动：`COORDINATION.md`：第 1 节硬规则重写并加入共享工作目录的 Git 纪律；第 2 节明确
  第 6/7.1/7.2 节为双方可写区（解除「看板归 DSH 却要求 Codex 写入」的矛盾）；第 7 节拆为
  7.1 进行中（含迁移编号与数据库占用列）与 7.2 工作报告；第 4 节纳入 `npm run build` 并说明理由；
  补充中文显示陷阱备注。`AGENTS.md` 同步上述要点。
- 验证：纯文档改动，未触碰任何代码。前端基线仍为 73 passed / 12 files（本轮已复核）；后端 192 项本轮未重跑。
- 更正：审查认为 `frontend/index.html` 有未提交改动 —— 实际工作树干净，该改动已在 `2d390b3` 提交，
  `git diff HEAD -- frontend/index.html` 为空。当时并不存在 DSH 的在途工作，可放心继续。
- 阻塞：无
- 下一步：审查第 3 项（原型语料纳入版本库）归 Codex；第 5 项的浏览器冒烟方案待定（见 7.1 待认领）。
  建议 Codex 先跑一次第 4 节后端基线（期望 192 passed），并回应第 6 节的请求。

### 2026-09-17 23:40 DSH 实现健康记录图表（ECharts）
- 改动：新增 `frontend/src/utils/healthCharts.ts`（数据派生 + 图表配置纯函数）、
  `frontend/src/components/HealthRecordCharts.vue`、`frontend/src/utils/healthCharts.test.ts`（10 项）；
  `frontend/src/views/HealthRecordView.vue` 接入；`package.json` 增加 `echarts ^6.1.0`；
  同步 `frontend/PROJECT_ROADMAP.md` 阶段 9 与 `PROJECT_PROGRESS.md`。
- 验证：`npm run build` 退出码 0；`npx vitest run` **12 files / 73 passed**（原 63/11，新增 10 项，
  故第 4 节前端基线数字已同步）。主包仍为 862.87 kB 未变，ECharts 全部落在懒加载的健康记录
  路由分块（534.60 kB / gzip 181.68 kB），未进入首屏包。
- 边界：图表只表达「记录条数与构成」，纵轴为「记录条数」，不出现严重程度、症状频率或病情趋势；
  边界文案与配置有测试回归保护（断言配置里不得出现临床口径词）。
- 阻塞：无。已按第 6 节就 `backend/docs/HEALTH_RECORDS.md` 第 109 行的过期说明提出跨边界请求。
- 下一步：Codex 接手后端时先跑第 4 节后端基线（期望 192 passed），并回应第 6 节的请求。

### 2026-09-17 23:27 DSH 前端热身：修掉 index.html 两处脚手架残留
- 改动：`frontend/index.html`（`lang="en"` → `zh-CN`；`<title>frontend</title>` → 产品名「病理诊断科普助手」）；
  `COORDINATION.md` 第 4 节环境备注更正为「`npm run build` 与 `npx vitest` 都受影响」。
- 验证：`npm run build` 退出码 0（11.79s）；`npx vitest run` **11 files / 63 passed**，基线不变。
- 阻塞：无。DSH 会话跑 Vite 需一次性放宽沙箱（见第 4 节备注），Codex 侧不受影响。
- 下一步：待定——ECharts 健康趋势图要先定「图表允许表达什么」，趋势类图表容易触碰
  「不作确诊、不替代医生」的产品红线，需先与用户确认范围再动手。

### 2026-09-17 DSH 交换分工：前端 ↔ 后端
- 改动：第 2 节分工表交换为 **DSH 拥有 `frontend/`、Codex 拥有 `backend/`**；第 3 节高冲突文件
  补上逐文件所有者；第 4 节验收基线按所有者拆开；`PROJECT_PROGRESS.md` 增加分工说明段。
- 验证：纯文档改动，未触碰任何代码；测试基线仍为后端 192 / 前端 63。
- 阻塞：无
- 下一步：Codex 按新分工接手 `backend/`（含迁移与后端测试）；DSH 从 `frontend/` 起步。
  下面「初始化协作机制」条目仍然有效，仅其分工归属已被本条取代。

### 2026-09-17 DSH 初始化协作机制
- 改动：新增根 `.gitignore`、`COORDINATION.md`；`AGENTS.md` 增加协作条款；建立首次 git 提交 `b7c4e88`（203 个文件 / 24001 行）
- 验证：203 个已跟踪文件全量密钥扫描无命中；`backend/.env`、`.venv`、`node_modules`、`dist` 均未纳入。
  更正一处误判：`.env` 与 `.venv/` 其实是被**原有的** `backend/.gitignore` 排除的（`frontend/.gitignore` 同理早已存在），
  根 `.gitignore` 只是补齐 `.dsh-backup/`、`report-work/`、`*.docx` 与全局兜底规则。
- 已知缺口：`backend/.gitignore` 的 `data/` 规则把 `backend/data/prototype_knowledge/`（13 篇语料 + manifest）
  一并排除了，语料未进版本库；数据库里已播种，不影响本机运行，但新克隆的仓库缺这份语料。
- 阻塞：无
- 下一步：Codex 首次开工前先读本文件，确认第 2 节分工边界；如有异议先改表再动代码
