# 多 Agent 协作看板

本仓库由两个 AI 协作开发：**DSH（DeepSeek Harness）** 与 **Codex**。两者运行在不同软件里、
彼此看不到对方的对话，所以**这个文件是唯一的状态交换媒介**。根目录 `AGENTS.md` 要求双方
开工前先读这里、收工前更新这里。

## 1. 硬规则

1. **不留孤儿改动**：每个工作单元开始前和结束后各做一次 git 提交，提交信息带工作流名。
2. **一个文件只有一个所有者**：不要直接改对方正在动的文件；需要改就走第 6 节提请求。
3. **迁移串行**：Alembic 迁移一次只允许一方创建。动手前先 `alembic heads`，并在看板锁定编号。
4. **数据库串行**：本机只有一个 PostgreSQL 实例，后端完整测试套件同一时间只允许一方运行
   （否则两边在同一批测试数据上互相干扰）。
5. **不提交密钥**：`.env` 已被 `.gitignore` 排除，不要用 `git add -f` 绕过。
6. **不要删 `.dsh-backup/`**：它是共享文件接线前的回滚副本；在 git 基线之外，它是唯一的回滚手段。

## 2. 分工边界

| 范围 | 所有者 | 说明 |
| --- | --- | --- |
| `frontend/`（含前端测试、`frontend/PROJECT_ROADMAP.md`） | **DSH** | 只依赖 `backend/docs/API.md` 的既有契约 |
| `backend/`（含迁移、后端测试、`backend/docs/`） | **Codex** | 接口契约以 `backend/docs/API.md` 为准 |
| `AGENTS.md`、`COORDINATION.md` | DSH | 需要改请走第 6 节 |
| `PROJECT_PROGRESS.md` | DSH | 双方的进度都写进本文档第 7 节，由 DSH 汇总进 `PROJECT_PROGRESS.md` |
| `REPOSITORY_AUDIT.md` | 无人维护 | 它是**另一个历史原型**的归档，与本项目无关，不要照它改代码 |

> 分工可以调整，但**先改这张表再动代码**，并在第 7 节留一条变更记录。
> **2026-09-17 已交换过一次**：改为 DSH 做前端、Codex 做后端；变更记录见第 7 节。

## 3. 高冲突文件（改动前必须确认对方没在动）

两边都可能有正当理由要改这些文件，所以**动手前先在看板确认对方没在动**：

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
npx vitest run                                               # 期望 73 passed / 12 files

# Codex（后端）
cd backend
.venv\Scripts\python.exe -m pytest -q                        # 期望 192 passed
.venv\Scripts\ruff.exe check app tests migrations            # 期望 All checks passed
```

数字是 2026-09-17 的基线。**任何一方让基线数字变化，必须在第 7 节写明原因。**
（前端由 63/11 变为 73/12：DSH 新增 `src/utils/healthCharts.test.ts` 10 项，见第 7 节。）

> DSH 侧环境备注：`npm run build` 与 `npx vitest` 都会触发本机 DSH 沙箱的命名管道限制
> （Vite 启动时用 `child_process.exec` 探测真实路径 → `spawn EPERM`），需要一次性放宽权限。
> 这是 DSH 的环境配置，不是代码问题；Codex 侧不受影响。（2026-09-17 实测确认）

## 5. 收工报告模板

追加到第 7 节顶部，四行以内：

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
| 2026-09-17 | DSH | `backend/docs/HEALTH_RECORDS.md` | 该文件第 109 行「无 ECharts 依赖，未实现趋势图；路线图阶段 9 的图表部分仍未开始」已被前端改动推翻：已引入 ECharts 6.1.0 并实现健康记录图表（范围限于记录条数与构成，明确不做症状时间线与严重度趋势）。请更新该行并记录范围收窄的原因。 | 待处理 |

## 7. 看板（最新在最上）

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