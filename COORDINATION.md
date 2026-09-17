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
npx vitest run                                               # 期望 63 passed / 11 files

# Codex（后端）
cd backend
.venv\Scripts\python.exe -m pytest -q                        # 期望 192 passed
.venv\Scripts\ruff.exe check app tests migrations            # 期望 All checks passed
```

数字是 2026-09-17 的基线。**任何一方让基线数字变化，必须在第 7 节写明原因。**

> DSH 侧环境备注：`npx vitest` 可能触发本机 DSH 沙箱的命名管道限制（`spawn EPERM`），
> 需要一次性放宽权限。这属于 DSH 的环境配置，不是代码问题，Codex 侧不受影响。

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
| — | — | — | （暂无） | — |

## 7. 看板（最新在最上）

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