# Neo4j 公共医学知识图谱独立实施方案

> 状态：规划稿，尚未实施
>
> 定位：把经过治理的公共医学知识组织为可追溯关系，用于概念导航、检索扩展和科普结构化；不保存任何用户私人数据。
>
> 独立性：Neo4j 是公共知识的可重建投影。PostgreSQL 仍是来源、审核、版本和发布状态的权威数据源；Neo4j 不可用时，现有公共 RAG 必须继续工作。

## 0. 建议先确认的产品决策

| 决策 | 推荐 | 原因与取舍 |
| --- | --- | --- |
| G1 图谱数据范围 | 第一版只放公共、已审核的医学科普关系 | 不复制用户病历、症状、健康记录或私人知识到第二套数据库 |
| G2 第一批关系 | 症状主题、红旗提醒、建议科室、自我照护主题、相关主题、证据来源 | 先增强解释与导航，不做药物剂量、治疗方案和疾病概率 |
| G3 运行时查询 | 只允许服务端参数化查询模板，禁止模型自由生成 Cypher | 防止注入、越权、全图扫描和不可控路径 |
| G4 权威来源 | PostgreSQL 审核记录是 source of truth；Neo4j 可整库重建 | 避免双写后无法判断哪个库正确 |
| G5 上线顺序 | 先做后台图谱检索增强，再做用户可视化探索页 | 先证明关系准确、有来源且不伤害现有回答，再增加界面复杂度 |

## 1. 明确非目标

第一版不做：

- 患者节点、用户节点、病历节点、个人症状边、健康记录边；
- “症状 → 疾病概率”排序、诊断推理或治疗决策；
- 药物剂量、停药/换药、相互作用或儿童剂量图谱；
- 自动把大模型抽取结果直接发布到生产图谱；
- 让前端或模型直接连接 Neo4j；
- 以 Neo4j 替代 PostgreSQL、pgvector、红旗规则或来源审核；
- 把用户专属知识库内容导入 Neo4j；
- 安装本机计划任务、Windows 服务或开机自启。

## 2. 适合图谱解决的问题

现有 pgvector + `pg_trgm` 擅长找相关段落，但不天然表达：

- 一个科普主题有哪些常见表现、需要补充哪些信息；
- 哪些红旗提醒与主题有关；
- 用户通常应咨询哪个科室；
- 两个医学概念如何关联；
- 一条关系由哪份已审核资料、哪个文本块支持。

Neo4j 的价值是“关系导航与检索扩展”，不是让图数据库替代语言模型作医学判断。

## 3. 安全架构

```text
公共知识文档（PostgreSQL，approved）
  └─ 关系候选抽取（离线）
      └─ 人工医学审核（PostgreSQL）
          └─ 发布事件 / outbox
              └─ 图谱发布 worker
                  └─ Neo4j 公共只读图

用户问题
  ├─ 红旗确定性预检（先执行，现有规则不变）
  ├─ 公共 RAG（现有 PostgreSQL + pgvector）
  └─ 图谱查询服务（参数化模板、1–2 跳、限节点数）
      └─ 带证据 chunkId 的关系结果
          └─ 与公共 RAG 证据一起进入回答，但分开标记来源
```

核心约束：

- 只有 `approved` 公共文档能够产生 `published` 图谱事实；
- 每条图谱事实至少绑定一个仍有效的公共 `KnowledgeChunk`；
- 撤销或替换文档时，相关事实必须撤回或重新审核；
- 图谱返回的关系不能绕过现有相关度门槛、引用核验和医疗安全提示；
- 图谱故障、超时或版本落后时静默降级到现有 RAG，并留下不含用户问题的最小审计。

## 4. 为什么不用“直接关系边”作为唯一事实

医疗关系需要状态、证据和审核记录。建议将一条关系建模为 `Claim` 节点，而不是只写一条无法挂完整来源的边：

```text
(subject:Concept)-[:SUBJECT_OF]->(claim:Claim)
(claim)-[:OBJECT]->(object:Concept)
(claim)-[:SUPPORTED_BY]->(evidence:Evidence)
```

`Claim.predicate` 表示关系类型。这样可以：

- 给每条关系保存稳定 `claimId`、审核状态、版本和发布时间；
- 一条关系绑定多份证据；
- 来源撤销时精确找到受影响关系；
- 同一对概念存在不同语境时不互相覆盖；
- 避免把模型抽取的候选直接伪装成已确认事实。

## 5. 图模型 v1

### 5.1 节点

#### `Concept`

```text
conceptId       全局稳定 UUID
conceptType     topic | symptom | department | red_flag | self_care
canonicalName   规范名称
normalizedName  规范化检索名
status          active | retired
version         模型版本
```

可按类型附加标签（如 `:Concept:Symptom`），但查询逻辑以受控 `conceptType` 为准，避免无限增长动态标签。

#### `Alias`

```text
aliasId / text / normalizedText / language / status
```

关系：`(Alias)-[:ALIAS_OF]->(Concept)`。别名也必须来自审核资料或人工维护，不能由用户输入永久写入。

#### `Claim`

```text
claimId
predicate
status          candidate | reviewed | published | retired
reviewVersion
reviewedAt
publishedAt
sourceRevision
```

第一批允许的 `predicate`：

- `MAY_INCLUDE_SYMPTOM`
- `HAS_RED_FLAG`
- `SUGGESTS_DEPARTMENT`
- `HAS_SELF_CARE_TOPIC`
- `RELATED_TOPIC`

名称刻意避免 `CAUSES`、`DIAGNOSES`、`TREATS` 等容易被理解为确定医疗结论的词。

#### `Evidence`

```text
evidenceId      建议等于 PostgreSQL chunk UUID
documentId
sourceKey
title
sectionTitle
versionLabel
contentHash
status
```

Neo4j 只保存定位与必要展示元数据。完整正文继续由 PostgreSQL 提供；图谱查询拿到 `chunkId` 后，再通过现有授权和审核条件读取正文。

### 5.2 约束和索引

至少建立：

- `Concept.conceptId` 唯一；
- `Claim.claimId` 唯一；
- `Evidence.evidenceId` 唯一；
- `Alias.aliasId` 唯一；
- `Concept(normalizedName, conceptType)` 组合索引；
- `Alias.normalizedText` 文本或全文索引；
- `Claim(predicate, status)` 查询索引。

Neo4j 官方支持属性唯一约束以及 range/text/full-text/vector 等索引。本方案 v1 只需唯一约束与名称检索索引；语义向量继续由现有 pgvector 承担，暂不在 Neo4j 再复制一套向量索引。

## 6. PostgreSQL 治理表

Neo4j 只存发布结果，候选、审核和发布状态仍在 PostgreSQL。建议新增：

### `graph_concepts`

- 稳定 ID、规范名、类型、别名候选、状态、版本；
- 规范名变更不改变 ID；
- 删除改为 retired，避免历史引用漂移。

### `graph_claims`

- `subject_concept_id / predicate / object_concept_id`；
- `status / extraction_model / extraction_version`；
- `medical_reviewed_by / medical_reviewed_at`；
- `published_revision / retired_at`。

### `graph_claim_evidence`

- claim 与 `knowledge_chunks` 多对多；
- 至少一条有效证据才能发布；
- 文档 superseded/expired 时阻止继续发布。

### `graph_publication_jobs`

- outbox 与发布任务合一或分表；
- `idempotency_key / target_revision / status / lease / retry / error_code`；
- 不保存用户问题、聊天内容或私人资料。

迁移编号在开工时根据实际 Alembic head 分配；当前代码目录最新为 `20260928_0026`，不得预占旧编号。

## 7. 关系生产与发布流程

### 7.1 候选抽取

- 只读取已审核公共知识块；
- 规则/模型只生成候选，不自动发布；
- 候选必须包含 subject、predicate、object、原始 chunkId 和原文证据范围；
- 无法映射规范概念时进入人工待处理队列，不临时造生产节点；
- 模型响应、提示词和供应商错误不写入 Neo4j。

### 7.2 医学审核

审核界面要同时展示：

- 关系三元组的通俗中文；
- 支持它的原文片段与来源；
- 概念合并/别名冲突；
- 是否属于首批允许关系；
- 发布、拒绝、退回修改和撤回。

一名审核者不能只看模型概括就批准，必须能打开来源定位。是否要求双人审核属于上线前合规决策；原型阶段至少保存明确审核人和时间。

### 7.3 发布

- PostgreSQL 事务内写入 `published_revision` 和 outbox；
- worker 使用幂等 `MERGE` 按稳定 ID 写 Neo4j；
- 发布完成后回写成功 revision；
- Neo4j 写入失败不回滚已审核事实，但线上只使用“PostgreSQL 期望 revision 与 Neo4j 当前 revision 一致”的图；
- 提供全量重建命令：新建空图 → 导入指定 revision → 校验数量/哈希 → 切换读流量；
- 本地开发 worker 由用户显式运行，项目停止即停止。

## 8. 运行时查询

### 8.1 禁止自由 Cypher

聊天模型、用户请求和前端都不能提交 Cypher。服务端只暴露参数化模板，例如：

1. 规范概念解析：名称/别名 → 最多 5 个候选；
2. 主题概览：一个 topic 的 1 跳 published claims；
3. 红旗与科室：topic → red_flag / department；
4. 相关主题：topic → related topic，最多 10 个；
5. 证据回溯：claimId → evidence chunk IDs。

所有模板固定：

- 最大深度 2；
- 最大节点、关系和 evidence 数量；
- 查询超时；
- 只读事务；
- 允许的 label、predicate 和返回字段白名单。

### 8.2 触发条件

图谱适合：疾病/症状主题概览、相关概念、科室导航、红旗提醒结构化补充。

以下情况跳过：

- 问候、模型身份、产品操作、闲聊；
- 红旗预检已命中（直接走固定紧急分流）；
- 用户只要求总结其附件或私人知识；
- 无法解析公共概念；
- Neo4j revision 落后、超时或不可用。

### 8.3 与 RAG 合成

- 图谱用于扩展检索词、组织回答结构和找到证据 ID；
- 正文仍从 PostgreSQL 的有效 approved chunk 读取；
- 图谱 claim 没有有效证据时不得送入模型；
- 图谱事实与普通 RAG 引用使用同一公共来源编号体系，避免重复引用；
- 图谱关系不能降低现有公共检索门槛；无足够证据时保持空上下文。

## 9. API 契约草案

运行时接口只接受受控字段：

```text
GET  /api/v1/knowledge-graph/concepts?query=...
GET  /api/v1/knowledge-graph/concepts/{conceptId}
POST /api/v1/knowledge-graph/explore
```

`explore` 示例：

```json
{
  "conceptId": "uuid",
  "relationshipTypes": ["HAS_RED_FLAG", "SUGGESTS_DEPARTMENT"],
  "depth": 1,
  "maxNodes": 30
}
```

响应只返回受控图元素和来源定位，不返回内部 Neo4j ID、Cypher、数据库地址或凭据。

管理/审核接口后续放在管理员端，并与普通用户 API 分离；没有管理员端前，可先提供受控 CLI，不开放公网写接口。

## 10. 前端规划

### 10.1 第一阶段：无独立图谱界面

- 图谱只在后台增强公共科普回答；
- 用户仍看到普通来源引用；
- 可在回答中用简单列表展示“相关症状主题 / 红旗提醒 / 建议科室”，但不画疾病概率图。

### 10.2 第二阶段：知识图谱探索页

在准确性和来源覆盖达标后，再增加独立页面：

- 以一个公共医学主题为中心；
- 只显示 1–2 跳、最多 30 个节点；
- 节点按类型而不是风险等级着色；
- 每条关系可以展开“依据来源”；
- 明确标注“科普关系，不代表对个人的诊断”；
- 不把用户输入的症状保存为节点，也不显示“你可能患有”。

可视化应支持键盘和列表替代视图，不能只靠颜色和拖拽表达关系。

## 11. 安全与运维

- Neo4j 只允许后端私网访问，不向浏览器暴露 Bolt/HTTP；
- 应用使用独立只读账号；发布 worker 使用独立写账号；管理员凭据不进入应用进程；
- 按最小权限配置角色。Neo4j 官方 RBAC 文档同样强调 least privilege；若部署版本不支持所需细粒度角色，则以网络隔离、独立实例和应用层模板白名单补足，并把限制写进部署文档；
- 密钥进入服务端环境配置，不入 Git、日志或错误响应；
- 查询记录只保留模板名、耗时、结果数量、revision 和受控状态，不记录用户原问题；
- 限制查询并发、超时、最大返回量和熔断；
- 健康检查区分“应用可用”和“图谱增强可用”，图谱故障不得让聊天整体不健康；
- 备份与恢复围绕 PostgreSQL 权威数据和可重建流程，Neo4j 备份是加速恢复，不是唯一真相。

## 12. 测试与评测

### 12.1 图模型与发布

- 唯一约束、幂等发布、重复证据、概念合并、撤回和文档 supersede；
- PostgreSQL revision 与 Neo4j revision 一致性；
- 中断重试、部分写入、全量重建与切换；
- 未审核、无证据、过期或 prototype 文档绝不能出现在生产图。

### 12.2 查询安全

- 用户输入 Cypher、超长路径、未知 predicate、恶意 label 均被 schema 拦截；
- 所有查询模板深度、节点数、超时和字段白名单生效；
- 前端永远拿不到连接信息与内部 ID；
- 图谱不可用、慢响应、revision 落后时正确降级。

### 12.3 医学质量评测

建立独立于抽取样本的冻结集，至少覆盖：

- 一个主题的症状、红旗、科室和自我照护关系；
- 同名词、别名、缩写和易混概念；
- 否定关系、条件关系和过期资料；
- 无覆盖概念必须返回空；
- 来源撤回后关系消失；
- 图谱扩展是否导致公共 RAG 误召回。

上线门槛建议：

- published claim 的来源可追溯率 100%；
- 无证据关系为 0；
- 未审核关系泄漏为 0；
- 关系精确率 ≥ 0.95；
- 无覆盖误返回率为 0；
- 红旗固定规则召回不下降；
- 图谱失败时普通 RAG 成功率不下降。

## 13. 分阶段实施

### G0 图模型与评测冻结

- 冻结 G1–G5、概念类型、predicate 白名单和证据规则；
- 编写小型人工金标准，不部署 Neo4j。

### G1 PostgreSQL 治理层

- 新表、迁移、候选抽取、审核状态、证据绑定、发布 outbox；
- 先用 CLI 审核，不接聊天。

### G2 Neo4j 投影与只读服务

- 本地可选 Neo4j、约束/索引、幂等发布、revision 校验、全量重建；
- 参数化查询模板、超时、熔断与可观测性；
- 不接用户回答。

### G3 离线评测与影子运行

- 同一批真实查询同时跑现有 RAG 和“RAG + graph”，但图谱结果不送模型；
- 比较召回、误召回、延迟和证据完整性；
- 不达门槛则不启用线上增强。

### G4 咨询接入

- 只对允许意图启用；
- 图谱结果必须回溯有效 chunk 后再进上下文；
- 失败自动降级；
- 灰度开关与一键关闭。

### G5 图谱探索页

- 关系展示、来源展开、列表替代视图和人工验收；
- 不展示个体化疾病概率或患者节点。

每阶段都能独立回滚；G0–G4 不依赖用户专属知识库。

## 14. 文件级实施清单（开工时细化）

后端建议新增：

- `backend/app/models/knowledge_graph.py`
- `backend/app/schemas/knowledge_graph.py`
- `backend/app/services/knowledge_graph_publication.py`
- `backend/app/services/knowledge_graph_query.py`
- `backend/app/api/routes/knowledge_graph.py`
- `backend/app/ai/graph_context.py`
- `backend/app/cli/knowledge_graph.py`
- 独立迁移、专项测试和 `backend/docs/KNOWLEDGE_GRAPH.md`

部署建议新增：

- Neo4j 环境变量占位（URI、database、只读/发布账号分别配置）；
- 开发环境显式启动的 Docker Compose profile；
- schema/constraint 初始化脚本与 revision 健康检查；
- 不创建计划任务、Windows 服务或开机自启。

前端第二阶段建议新增：

- `frontend/src/types/knowledgeGraph.ts`
- `frontend/src/api/knowledgeGraph.ts`
- `frontend/src/views/KnowledgeGraphView.vue`
- 小规模图形组件、列表替代视图和 Vitest/Playwright。

## 15. 完成定义

以下全部满足才可宣称“Neo4j 知识图谱增强已实现”：

- 图谱只含已审核公共关系，不含任何用户私人数据；
- 每条线上关系都有有效公共证据并能定位到原文；
- 运行时不存在自由 Cypher，所有模板有限深、限量、只读和超时；
- PostgreSQL 与 Neo4j revision 可校验，图可全量重建；
- 图谱不可用时现有咨询与公共 RAG 正常工作；
- 独立关系评测达标，未审核/无证据/无覆盖误返回均为 0；
- 红旗预检、医疗边界、引用核验和免责声明不被图谱绕过；
- 真实部署完成凭据隔离、网络隔离、备份恢复和熔断演练；
- 如上线探索页，来源、边界、键盘操作和列表替代视图完成人工验收。

## 16. 参考依据

- [Neo4j 约束文档](https://neo4j.com/docs/cypher-manual/current/schema/constraints/)：节点和关系属性唯一性、存在性、类型与 key 约束。
- [Neo4j 索引文档](https://neo4j.com/docs/cypher-manual/current/indexes/)：range、text、full-text 和 vector 等索引类型；本方案 v1 不重复建设向量索引。
- [Neo4j RBAC 文档](https://neo4j.com/docs/operations-manual/current/authentication-authorization/manage-privileges/)：角色与最小权限原则。
