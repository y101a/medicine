# 知识图谱治理层与 G2 全量投影

## G2 只读查询与 G4 受控接线（2026-10-06）

后端现有 `GET /api/v1/knowledge-graph/concepts?query=...` 和
`POST /api/v1/knowledge-graph/explore`（仅登录用户）。查询端只接收 PostgreSQL
登记的公共概念 UUID，使用固定 Cypher 模板和枚举关系类型；Neo4j 返回值必须与
PostgreSQL 期望 revision 一致，且每条关系再次核对发布状态、医学审核和当前有效的
公共知识证据。图谱故障、版本落后、证据撤回时返回 `available=false` 和空关系列表，
不泄露数据库地址、Cypher 或用户原文。首版探索限制 1 跳、最多 30 个节点。

`NEO4J_READ_ENABLED`、`NEO4J_SHADOW_ENABLED`、`NEO4J_CONSULTATION_ENABLED`
均默认 `false`。影子模式只记录匹配关系数量，不送给模型；咨询开关即使开启，也只
能把**证据 chunk ID 已经出现在本轮审核 RAG 来源编号中**的关系作为组织回答的附加提示，不另造
来源编号、不能越过 RAG 相关度门槛。没有正式医学资料和 G3 独立评测前不得开启
咨询开关。读取使用单独配置的 `NEO4J_READ_USERNAME`/`NEO4J_READ_PASSWORD`；
Community Edition 无细粒度只读角色时，不得把发布账号凭据直接交给线上读服务。
图谱探索前端页面仍归 DSH，需按协作协议交接并确定入口位置。

## G2 增量说明（2026-10-03）

已增加 `app/knowledge_graph_worker.py`：从 PostgreSQL 已发布且证据有效的公共 Claim 构造完整快照，用固定参数化 Cypher 在**单个 Neo4j 写事务**里替换旧图。概念改名、关系撤回、已审核文档被取代、来源注册表降级都会产生新 revision；空图也可投影以清除旧知识。图中只含概念、关系、证据定位 ID，不复制正文，不含用户/患者或健康记录。

新审核文档的四层用途分类见 `KNOWLEDGE_CLASSIFICATION.md`。分类不等于审核，未审核候选不能投影。

本地已安装 `neo4j` Python driver 6.3.1，并拉取 `neo4j:5-community` 镜像。`compose.yaml` 的 `neo4j` profile 默认关闭、只监听 `127.0.0.1`，`restart: "no"`；联调后容器已停止。启动时必须由操作者在当前 shell 设置 `NEO4J_AUTH=neo4j/<强密码>`，同时向 worker 提供 `NEO4J_URI`、`NEO4J_USERNAME`、`NEO4J_PASSWORD`（可选 `NEO4J_DATABASE`），不要将密码写进仓库。对已初始化的 Docker volume，重新设置 `NEO4J_AUTH` **不会更改旧密码**。运行 `docker compose --profile neo4j up -d --no-deps neo4j` 后，可前台运行 `python -m app.knowledge_graph_worker --owner neo4j-worker`；该命令一次只处理一个 outbox 任务，部署时需另配与项目同生共死的调度。漏掉事件或需手动重建时运行 `python -m app.knowledge_graph_cli rebuild-snapshot --actor 管理员`。G3–G5 仍未接入线上问答，原有 RAG 不受影响。Neo4j Community Edition 不具备细粒度读写角色隔离时，必须仅本地监听并限制网络访问。

2026-10-03 的真实联调：显式开启 `NEO4J_TEST_ALLOW_RESET=1` 后跑 `tests/test_knowledge_graph_neo4j_integration.py`，验证 PG 审核事实 → outbox 领任务 → Neo4j 5 条 Claim 全量快照 → 撤回后只剩 4 条 → 故障时任务失败且保留事实 → 恢复后重试成功 → 空图清除旧事实。测试结束再次清空测试图节点（`PublicMedicalGraph` 数量 0），停止容器。**不要将这个重置开关用于有正式投影的 Neo4j 实例。**

以下章节保留 G1 建成时的历史说明，其中“G2 未做”是当时状态，不代表当前代码状态。

对应规划稿 `NEO4J_KNOWLEDGE_GRAPH_PLAN.md` 的 **G0 + G1**。本文只描述**已经落地**的部分，
以及 G2 需要接着做什么；没有落地的一律写成「未做」，不要按规划稿的将来时理解现状。

## 1. 边界与事实源

- 只存放**审核后的公共医学知识**：概念（Concept）、关系（Claim）、证据（Evidence）。
- **禁止**存入任何用户/患者数据：图谱表不引用 `users`、`consultations`、`messages`、
  `health_records`、`private_knowledge_*`。这条由测试
  `tests/test_knowledge_graph_governance.py::test_graph_tables_never_reference_user_data`
  在外键与列名两个方向强制。
- **PostgreSQL 是唯一事实源**，图数据库只是「可以随时重建的投影」：删掉投影、按 revision
  重建，都不影响审核结论。
- 关系类型刻意限制为「表现/红旗提醒/咨询科室/自我照护主题/相关主题」五类，**不存在**
  `CAUSES`/`DIAGNOSES`/`TREATS` 这类会被读成医疗结论的关系（测试冻结了这一点）。

## 2. 当前状态（2026-10-02）

| 阶段 | 状态 |
| --- | --- |
| G0 模型冻结 + 小型金标准 | 已落地（见第 3 节与 `tests/test_knowledge_graph_candidates.py` 的 `GOLD_*`） |
| G1 PostgreSQL 治理层 | 已落地：5 张表、迁移 `20261002_0028`、规则式候选抽取、审核状态机、发布 outbox、受控 CLI、测试、冒烟脚本 |
| G2 Neo4j 投影 | **未做**：本机没有 Neo4j 服务，`pyproject.toml` 里没有 driver，没有 worker。**用户 2026-10-02 决定：暂不安装/下载 Neo4j**，等进入 G2 时再拉 `neo4j:5-community` 镜像并加默认关闭的 compose profile（见 `PROJECT_PROGRESS.md` ADR-012） |
| G3 运行时接线 / G4 上下文注入 / G5 前端探索器 | **未做** |

因此现在**没有任何用户可见行为依赖图谱**：它不影响问答，也不影响检索。回答仍走原有
公共 RAG；图谱故障不可能影响线上问答，因为线上根本没读它。

## 3. 数据模型（`app/models/knowledge_graph.py`，迁移 `20261002_0028`）

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `graph_concepts` | 概念：topic/symptom/department/red_flag/self_care | `(concept_type, normalized_name)` 唯一；停用不删除 |
| `graph_concept_aliases` | 别名 → 概念 | `(concept_id, normalized_text)` 唯一；**`normalized_text` 故意不全局唯一** |
| `graph_claims` | 三元组 | `(subject, predicate, object)` 唯一；`subject <> object`；published 必须同时有审核人与发布时间 |
| `graph_claim_evidence` | 证据：指向知识块与字符区间 | `(claim_id, chunk_id)` 唯一；**不复制正文**，只存 `chunk_content_hash` + span |
| `graph_publication_jobs` | 发布 outbox | `idempotency_key` 唯一、`target_revision` 唯一、租约 + 重试计数 |

与规划稿的四处有意细化：

1. **多了一张 `graph_concept_aliases`**（规划稿 §5.1 把 Alias 列为一等实体，但没有给它表）。
   别名不全局唯一是刻意的：同一个词形可能属于多个概念（例如「结节」），解析时返回候选让人
   判断，而不是让系统偷偷选一个。
2. **多了 `review_decision`**（pending/approved/rejected/returned）。规划稿的四个
   `GraphClaimStatus` 是冻结的，如果让「拒绝」直接占用状态值，就会污染冻结词表；分开之后
   「候选被拒绝」既不下线也不消失，只是结论不同。
3. **证据不存正文**：正文只在 PostgreSQL 的知识块里存一份，证据只记 chunkId + 区间 +
   当时的正文哈希。哈希对不上就必须重新审核。
4. **G1 没有对外 API schema**：只有 CLI 的输入模型（`app/schemas/knowledge_graph.py`）。
   写接口要等管理员端（G2/G3）一起设计，避免先放出一个没有权限模型的写入口。

## 4. 状态机与发布门槛

```
抽取 → candidate/pending ──approve──→ reviewed/approved ──publish──→ published(revision=N)
             │  ▲                              │
      reject │  │ return                       └──retire──→ retired
             ▼  │
        candidate/rejected | candidate/returned          （不删除行，保留 revision）
```

`approve` 必须全部满足，否则报错并说明原因（`list_review_queue` 会把原因直接显示出来）：

- 至少一条**仍然有效**的证据：来源文档仍是 `approved`，且知识块正文哈希与证据记录一致；
- 两端概念都在用（未停用），且两端类型符合 predicate 的冻结规则；
- 审核人与审核时间落库。

`publish` 只发布「已审核 + approved + 有效证据」的关系，写成一个新 revision 并登记 outbox
任务。**重复发布是幂等的**：没有新的可发布关系时直接报错，不会新建任务。

投影失败**不回滚已审核事实**：任务置 `failed` 并记 `error_code`，重启 worker 会自动重试，
超过 3 次停手等人工处理。`verify` 会区分「数据违规」（issues）与「还没投影完」
（`revision_in_sync=false`），不会把后者当成数据问题。

## 5. 运维命令

受控 CLI（没有公网写接口，写操作只走这个前台命令）：

```powershell
cd backend
$py = ".\.venv\Scripts\python.exe"
& $py -m app.knowledge_graph_cli seed-concepts --file .\scripts\knowledge_graph_smoke_concepts.json
& $py -m app.knowledge_graph_cli register-concept --type topic --name 肺癌 --alias 支气管肺癌
& $py -m app.knowledge_graph_cli rename-concept --concept <uuid> --name 原发性支气管肺癌
& $py -m app.knowledge_graph_cli extract-candidates --all-approved --limit 20   # 加 --dry-run 只报数量
& $py -m app.knowledge_graph_cli review-queue --limit 10
& $py -m app.knowledge_graph_cli approve-claim --claim <uuid> --actor 李医生 --note "与原文一致"
& $py -m app.knowledge_graph_cli reject-claim  --claim <uuid> --actor 李医生 --note "表述不一致"
& $py -m app.knowledge_graph_cli return-claim  --claim <uuid> --actor 李医生 --note "请补充来源"
& $py -m app.knowledge_graph_cli retire-claim  --claim <uuid> --actor 李医生 --reason "来源已更新"
& $py -m app.knowledge_graph_cli retire-stale  --actor 李医生
& $py -m app.knowledge_graph_cli bind-evidence --claim <uuid> --chunk <uuid> --span-start 0 --span-end 12
& $py -m app.knowledge_graph_cli publish --actor 李医生
& $py -m app.knowledge_graph_cli status
& $py -m app.knowledge_graph_cli verify                  # 有违规时退出码 1
& $py -m app.knowledge_graph_cli publication-status
& $py -m app.knowledge_graph_cli claim-job --owner graph-worker-1 --lease-seconds 300
& $py -m app.knowledge_graph_cli complete-job --job <uuid> --owner graph-worker-1
& $py -m app.knowledge_graph_cli fail-job --job <uuid> --owner graph-worker-1 --code NEO4J_UNAVAILABLE --message "..."
```

约定（与 `app/rag/cli.py` 一致）：一行 JSON `{"ok": true, "command": ..., "result": {...}}`，
失败为 `{"ok": false, "error": "中文原因"}` 且退出码 1；字段名是 **snake_case**（dataclass
走 `asdict`），`verify` 有违规时也返回退出码 1，便于脚本判定。

`rename-concept` 是改名的**唯一**入口：按名字登记无法表达改名（新名字找不到旧行，会被当成
新概念），而改名必须保住 ID——历史 claim 与证据都挂在 ID 上。旧名会自动留成别名，否则线上
正文里写的旧名会突然匹配不上。登记时若新规范名已经是别人的别名，直接报错，不静默造重复概念。

## 6. 候选抽取规则（`rule_v1`）

- 只处理 `review_status = 'approved'` 的公共文档；未审核文档直接报错。
- 只认**已登记**的概念与别名：没有登记的概念不会凭空造节点，这类知识块会被列进
  `chunks_without_concepts`，提示人去登记概念。
- 匹配与正文都用同一套逐字符规范化（NFKC + casefold + 去空白），因此「肺 癌」「ＮＳＣＬＣ」
  与「肺癌」「NSCLC」等价；证据区间记录的是**原文下标**，测试断言切片里必须真的包含两端概念名。
- 确定性：同一份输入永远得到同一批候选；同一三元组只建一条 claim，重复抽取只补证据。
- 已被拒绝/退回的关系**不会**因为再次抽取而复活。
- 目前**不调用任何模型**：模型抽取属于规划稿 §7.1 的另一条支路，接入前先要有像样的评测集，
  而 G0 的小型金标准不足以支撑它上线。

## 7. 验收

```powershell
cd backend
$py = ".\.venv\Scripts\python.exe"
& $py -m pytest -q                     # 535 passed（含 38 项图谱治理测试）
& $py -m ruff check .                  # All checks passed
& $py -m alembic downgrade 20261001_0027
& $py -m alembic upgrade head          # 0028 可往返
powershell -ExecutionPolicy Bypass -File .\scripts\run_knowledge_graph_smoke.ps1
```

冒烟脚本在**一次性数据库 `kg_cli_smoke`** 里跑完整链路（建库 → 迁移 → 造一篇已审核文档 →
登记概念 → 抽候选 → 审核 → 发布 → 取任务 → 回写成功 → verify → 制造正文漂移 → verify 退出码 1
→ retire-stale → verify 恢复干净），结束后删库，**再连回真实开发库**逐张打印五个 `graph_*` 表的
行数（应为 0，证明整轮没有写进 dev 库）。当前结果：**21 步全通过**；dev 库 `medical_assistant`
停在迁移 `20261002_0028`，`graph_concepts` / `graph_concept_aliases` / `graph_claims` /
`graph_claim_evidence` / `graph_publication_jobs` 均为 **0 行**。

已知的既有问题（**不是**本轮引入）：`alembic check` 在仓库范围内并不干净——它报告
`generated_documents`/`message_private_knowledge_citations` 的 CHECK 约束命名漂移，以及
`knowledge_chunks`/`knowledge_documents` 上 pg_trgm 索引未在模型里声明。差异里**没有**任何
`graph_*` 条目，说明本轮迁移与模型一致；上述漂移属于既有状态，需要时另行处理。

## 8. G2 要接着做的事（未做）

1. **Neo4j 只有企业版/ Aura 才有细粒度角色管理**（已核对官方运维手册）：规划稿「读写账号
   分离」在社区版做不到，应落在它自己给出的退路上——只监听回环 + 网络隔离 + 应用层
   参数化模板白名单（规划稿 §8.1：禁止模型自由生成 Cypher）。
2. 投影 worker：按 `claim-job` → 幂等 `MERGE` → `complete-job`/`fail-job` 的顺序接上即可，
   编排逻辑（revision、租约、重试）已经在 G1 里写好并测过。
3. 约束与索引按 Neo4j 官方文档建，别照抄规划稿的示例文本（未逐条核对）。
4. 运行时接线与上下文注入必须复用 `app/ai/private_knowledge_context.py` 的有界 JSON 渲染
   与「不可信数据」声明模式，并保留「图不可用就退回现有 RAG」的降级路径。
