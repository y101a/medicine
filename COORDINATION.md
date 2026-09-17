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
| `backend/`（含迁移、后端测试、`backend/docs/`） | DSH | 接口契约以 `backend/docs/API.md` 为准 |
| `frontend/`（含前端测试、`frontend/PROJECT_ROADMAP.md`） | Codex | 只依赖 `backend/docs/API.md` 的既有契约 |
| `AGENTS.md`、`COORDINATION.md` | DSH | 需要改请走第 6 节 |
| `PROJECT_PROGRESS.md` | DSH | Codex 的进度写进本文件第 7 节即可，由 DSH 汇总 |
| `REPOSITORY_AUDIT.md` | 无人维护 | 它是**另一个历史原型**的归档，与本项目无关，不要照它改代码 |

> 分工可以调整，但**先改这张表再动代码**，并在第 7 节留一条变更记录。

## 3. 高冲突文件（改动前必须确认对方没在动）

- `backend/app/api/router.py`
- `backend/app/api/routes/consultations.py`
- `backend/app/ai/provider.py`
- `frontend/src/router/index.ts`
- `frontend/src/layouts/WorkspaceLayout.vue`
- `frontend/src/views/HomeView.vue`

## 4. 验收基线（提交前必须跑）

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q                        # 期望 192 passed
.venv\Scripts\ruff.exe check app tests migrations            # 期望 All checks passed
cd ..\frontend
npx vue-tsc --noEmit -p tsconfig.app.json                    # 期望退出码 0
npx vitest run                                               # 期望 63 passed / 11 files
```

数字是 2026-09-17 的基线。**任何一方让基线数字变化，必须在第 7 节写明原因。**

> DSH 侧环境备注：`npx vitest` 与 pytest 的临时目录可能触发沙箱限制，需要一次性放宽权限；
> 这属于本机 DSH 的配置，不是代码问题。

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

### 2026-09-17 DSH 初始化协作机制
- 改动：新增 `.gitignore`、`COORDINATION.md`；`AGENTS.md` 增加协作条款；建立首次 git 提交基线
- 验证：`git status` 确认 `.env`、`node_modules`、`.venv`、`dist`、头像目录均未被纳入
- 阻塞：无
- 下一步：Codex 首次开工前先读本文件，确认第 2 节分工边界；如有异议先改表再动代码