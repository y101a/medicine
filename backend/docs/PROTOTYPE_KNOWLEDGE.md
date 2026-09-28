# 开发原型医学知识库

## 定位与边界

这组资料只用于个人开发阶段验证 Markdown 导入、向量生成、pgvector 召回和引用链路。
内容由项目开发者根据公开健康科普主题自行整理，没有完成版权专员或医疗专业人员审核，
不属于官方文档，也不能用于诊断、治疗或临床准确性声明。

数据库使用独立的 `prototype` 状态标记来源和文档。只有
`APP_ENVIRONMENT=development` 时，向量化与检索才会接纳这些记录；生产环境只允许
`approved` 来源和 `approved` 文档。

## 历史基线与第二批已向量化原型资料

2026-09-12 曾测得的数据库基线是 5 篇 Markdown，覆盖紧急危险表现、合理用药、
动物咬伤、慢性健康问题和呼吸道感染预防。2026-09-14 新增 8 篇独立原型资料，
文件与清单合计 13 篇；新增部分按人体系统分组：呼吸（过敏性鼻炎、哮喘），
消化（胃食管反流、诺如病毒急性胃肠炎），心血管（高血压、冠心病），
内分泌（糖尿病、甲状腺常见问题）。原有跨系统资料可保留多个系统标签，
通用安全资料不强行归类。`body_systems` 只用于归档，不会仅凭部位给用户诊断。

新资料的正文与 `manifest.json` 中的 `reference_urls` 可逐篇检查；它们是以官方公开
信息为线索的自编简要概述，不是所列网页的复制件，也未经专业医学内容审核。
官方 URL 是查阅线索，不等于来源已完成受控正式导入。正文与清单原先只存在于本机项目目录
（本文件此前即指出「仓库尚无提交，不能误以为已有 Git 版本备份」）；**2026-09-18 已纳入版本库**：
`backend/.gitignore` 改为 `data/*` + `!data/prototype_knowledge/`（其余 `data/` 仍属运行期数据，
继续忽略），同目录新增 `README.md` 把「未审核、仅开发原型」的边界随文携带。
**纳入版本库不等于完成审核，也不等于可用于生产**：数据库仍只以 `prototype` 状态接纳这些记录，
且仅 `APP_ENVIRONMENT=development` 时参与向量化与检索。
文档元数据明确保存 `medical_reviewed: false` 和 `production_eligible: false`。

**2026-09-15 当前库核对快照：**`developer_prototype_knowledge` 来源已有 13 篇文档、
41 个文本块和 41 个向量；`web_search_prototype` 保留 2 篇、2 块及 2 个向量。
43 个向量的模型均为 `qwen3.7-text-embedding-flash`、版本 `2026-09-01`、维度 1024。
首次运行 `embed-prototype` 在 14 个向量完成时出现 `EMBEDDING_TIMEOUT`，
一次幂等重试后全部完成。哮喘和甲状腺两条具体病名查询的预期原型文档排第 1；
相关导入、向量化、检索测试 17 项通过。未运行新增 8 篇的独立检索题集，也未经
医学和版权审核。数据库快照可能变化，下次操作前仍须重新核对。

**2026-09-18 复核结果：与上表一致。**首次核对时本机 Docker Desktop 未运行
（`docker compose ps` 报 `dockerDesktopLinuxEngine` 命名管道不存在），后端套件为
`10 failed / 123 passed / 61 errors`，失败与错误**逐条核对全部是数据库连接类**——是环境，
不是回归（当时只改 `.gitignore`、语料与文档，不含任何 Python 代码）。启动容器后重新核对：
`medical-assistant-postgres`（`pgvector/pgvector:0.8.6-pg17-trixie`，healthy）上的实际数量为
`developer_prototype_knowledge` **13 篇 / 41 块**、`web_search_prototype` **2 篇 / 2 块**，
向量共 **43** 个、模型 `qwen3.7-text-embedding-flash`、版本 `2026-09-01`、维度 1024，
与上表逐项吻合；后端套件 **194 passed**。
（DSH 沙箱下不放宽权限时会出现 8 项 `PermissionError` 的 setup 错误，属环境问题，
见 `COORDINATION.md` 第 4 节环境备注。）

## 可复现命令

在 `backend` 目录执行：

~~~powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m app.rag.cli seed-prototype
.\.venv\Scripts\python.exe -m app.rag.cli embed-prototype
.\.venv\Scripts\python.exe -m app.rag.cli evaluate-prototype --top-k 3
.\.venv\Scripts\python.exe -m app.rag.cli evaluate-prototype --dataset docs/medical_retrieval_evaluation_v2.json --mode keyword --top-k 3 --split tune
~~~

导入和向量化命令具有幂等性。当前阿里云兼容接口实测批量返回的 `index` 均为 0，
为了避免文本块与向量错配，暂时每次只发送一个文本块。
若 Docker Desktop 或 PostgreSQL 不在运行，先启动服务并在 `backend` 目录执行
`docker compose up -d`；执行导入前先核对当前连接的数据库和已有来源，避免误动
联网搜索原型数据。`embed-prototype` 会调用收费向量服务，后续新增或改版资料前仍须确认预算。

## 2026-09-12 基线（扩充前，不代表新语料效果）

- 原型来源：1 个。
- 当前原型文档：5 篇。
- 文本块：16 个，已有向量：16 个。
- 评测题：10 条，覆盖 education、urgent、emergency。
- 指标：`prototype_document_hit_at_k`。
- Hit@3：10/10（100%）；10 条预期文档均排在第 1 位。
- Top-1 平均余弦相似度：0.76509。

详细机器可读结果见 `prototype_retrieval_baseline.json`。题集和语料由同一开发过程设计，
样本也很小，因此该结果只能证明当前检索链路在这些题目上可工作，不能代表泛化能力、
回答正确率或医疗安全性。

## 检索模式对比（2026-09-18 起可用）

`search_knowledge(..., mode=...)` 支持三种模式，`evaluate-prototype` 通过 `--mode` 选择：

| 模式 | 含义 | 是否调用收费向量服务 |
| --- | --- | --- |
| `hybrid` | 关键词 + 向量两路召回后按向量 85%、关键词 15% 加权融合（线上默认） | 是（每题 1 次） |
| `keyword` | 只走 pg_trgm 关键词 | **否，零成本** |
| `vector` | 只走向量，忽略关键词命中 | 是（每题 1 次） |

单路模式直接按各自的原始相关度排序；非法模式返回 `RETRIEVAL_MODE_INVALID`。

**2026-09-18 三模式实测（独立题集 `medical_retrieval_evaluation_independent.json`，15 题，`--top-k 3`）：**

| 模式 | 命中 | 命中率 | 平均首位相似度 |
| --- | --- | --- | --- |
| `keyword` | 4/15 | 0.2667 | 0.113 |
| `vector` | 15/15 | 1.0 | 0.640 |
| `hybrid`（旧 RRF） | 15/15 | 1.0 | 0.613 |
| `hybrid`（85/15 加权，2026-09-19） | 15/15 | 1.0 | 0.640788 |

对照：同一套语料上，纯关键词在**同源题集**（`medical_retrieval_evaluation.json`，10 题，题目与
语料由同一过程设计）是 8/10，在**口语化独立题集**上只有 4/15，相差约 3 倍。这说明同源题集
确实会明显高估效果：**凡是要下「召回效果」结论的地方，都必须用独立题集**。独立题集刻意改用
患者口语问法（例如「手背被小区里的猫抓破出血」「体检查出脖子里有个结节」），不照抄语料标题词。

已知局限，不要当作普遍结论：
- 样本只有 15 题，且只测了一个向量模型（`qwen3.7-text-embedding-flash`）。
- 旧 RRF 的名次倒数求和会让双路弱命中压过强向量结果；改为 85/15 加权分数后，
  Hit@3 与 Top-1 数量不变，平均首位相似度由 0.613 提升至 0.640788，基本追平纯向量。
  90/10 也做了同题复测（15/15、Top-1 13/15），平均首位相似度为 0.639861，略低于
  85/15，因此没有保留。该小样本仍未证明 hybrid 优于 vector，不能外推为普遍结论。
- 本评测只判断「期望文档有没有进 top-k」，不评估回答质量，也不评估引用是否被正确标注。

## 独立题集 v2（2026-09-27）

`medical_retrieval_evaluation_v2.json` 冻结为 80 题：52 道单主题已覆盖题、12 道跨文档
混淆题、16 道当前知识库未覆盖题。题集按 `split` 固定分为 60 道 `tune` 与 20 道
`holdout`；日常调参只能运行 `tune`，方案冻结后才可运行 `holdout`。现有 13 篇原型
文档均至少有四道单主题题覆盖。

评测器保持旧题集兼容，并新增 Recall@1、Recall@3、MRR、总体通过率、未覆盖题误召回率，
以及按人体系统、问法、安全等级和分组统计。`unsupported` 题没有期望文档：检索返回任意
知识条目都记为误召回，用来区分「检索错误」和「知识库没有覆盖」。该规则评估的是检索层，
不代表聊天模型最终一定会引用召回结果。

**2026-09-27 零成本关键词基线（`top-k=3`）：**

| 分组 | 总题数 | 已覆盖题 | 未覆盖题 | Recall@1 | Recall@3 | MRR | 未覆盖题误召回率 | 总体通过率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `tune` | 60 | 48 | 12 | 0.3750 | 0.3958 | 0.3819 | 0.1667 | 0.4833 |
| `holdout` | 20 | 16 | 4 | 0.2500 | 0.2500 | 0.2500 | 0.0000 | 0.4000 |
| 全部 | 80 | 64 | 16 | 0.3438 | 0.3594 | 0.3490 | 0.1250 | 0.4625 |

本轮只运行 `keyword`，不调用阿里云、不产生向量费用，也没有据此调权重。结果说明精确
关键词可作为补充，但对口语化表达召回明显不足；后续需在用户确认费用后，用冻结的同一题集
依次运行 `vector` 与 `hybrid`。三模式对比前不得根据 `holdout` 逐题结果改语料、阈值或权重。

### 2026-09-28 三模式真实对比

用户确认后，使用当前开发库快照（5 个来源、15 篇文档、43 块、43 个当前模型向量）和
`qwen3.7-text-embedding-flash` 完成三模式全量评测。详细机器可读报告见
`medical_retrieval_evaluation_v2_results.json`。

| 模式 | Recall@1 | Recall@3 | MRR | 未覆盖题误召回率 | 总体通过率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `keyword` | 0.3438 | 0.3594 | 0.3490 | 0.1250 | 0.4625 |
| `vector` | 0.9375 | 0.9844 | 0.9609 | 1.0000 | 0.7875 |
| `hybrid` | 0.9219 | 0.9844 | 0.9531 | 1.0000 | 0.7875 |

结论不是“纯向量最好”。向量与混合模式显著改善口语问法召回，但在没有最低相关度门槛时，
会给 16 道当前未覆盖题全部返回资料。只用 `tune` 选择查询级近似阈值 0.55，再冻结到
`holdout`，得到 Recall@3 0.9375、未覆盖题误召回率 0、总体通过率 0.95。该分析只依据
每题首位相似度，尚不是线上实现；正式改阈值前要做逐候选过滤并重跑相同题集。

评测期间阿里云连接发生多次临时超时/不可用。CLI 现支持单题有限重试和原子断点，避免长任务
在第 N 题失败后重复前 N-1 题的费用：

```powershell
.\.venv\Scripts\python.exe -m app.rag.cli evaluate-prototype `
  --dataset docs/medical_retrieval_evaluation_v2.json `
  --mode hybrid --top-k 3 --split all --max-retries 2 `
  --checkpoint data/retrieval_evaluation_checkpoints/hybrid_v2_all.json
```

`data/` 下断点是本机运行数据，默认不入 Git。断点绑定题集内容哈希、模式、`top-k`、分组和
**相关度门槛（profile + 全部阈值）**；参数、题集或门槛变化时会拒绝复用，防止把不同实验的
结果混在一起。

### 2026-09-28 逐候选相关度门槛（机制已统一，线上未启用）

上表说明：没有最低相关度门槛时，16 道未覆盖题全部被返回（误召回率 1.0）。0.55 那组数字
只用了每题**首位**相似度，属于离线近似，不能直接上线。本轮把它做成逐候选实现：

1. 新增唯一门槛模块 `app/rag/relevance.py`。三种 profile：`none`（不过滤，评测基线）、
   `current-consultation`（精确复刻咨询图原有 0.72 / 网页来源 0.60 / 关键词 0.2）、
   `candidate-threshold`（待调门槛）。分数语义被写死：有 `vector_similarity` 时只与向量分
   比较；没有当前向量的候选走单独的关键词规则（避免误杀精确关键词命中）；`rerank_score`
   只排序、永不单独充当证据；只有 `similarity` 的 legacy 证据走兼容路径并单独记 reason。
2. 咨询图改为调用这同一份门槛，**行为逐位不变**（检索/图/联网 52 项测试全绿，网页来源
   0.60 那条继续成立）。数字只有一份，不再散落在业务代码里。
3. 评测器新增逐候选分数（`EvaluationCandidateScore`）、`filtered_count` 与过滤原因统计；
   断点身份包含门槛；并新增 `regate_case` / `sweep_gates` / `select_gate` 与 CLI
   `sweep-relevance-gate`，可以在**已保存的真实召回**上离线换门槛——扫参不再重复付费。
   `--split holdout` 必须同时给出冻结阈值，否则直接报错。

**本轮唯一一次真实 hybrid 复评（`top-k=3`，80 题，真实重试 4 次）：** 结果与 2026-09-28
三模式基线逐位一致（Recall@1 0.9219、Recall@3 0.9844、MRR 0.9531、误召回率 1.0、通过率
0.7875），说明语料与检索层没有漂移。机器可读结果见
`medical_retrieval_evaluation_v3_results.json`（含每题每个候选的分数与保留/否决原因，
但不含题目原文）。旧的 `medical_retrieval_evaluation_v2_results.json` 保留不覆盖。

**选参与冻结：** 只用 `tune`（60 题）扫 663 套门槛（向量 0.30–0.80 步长 0.01 ×
关键词 0.20–0.80 步长 0.05；「无向量关键词」档固定 0.2，这是**产品约束**而不是调参维度，
用来保证精确关键词命中不被误杀）。选择规则：未覆盖误召回率必须为 0 → 最大化总体通过率
→ Recall@3 不得低于 0.90；同分时取阈值更高（更保守）的一套。26 套达标，冻结为
**向量 0.56 / 关键词 0.2 / 无向量关键词 0.2 / 网页来源 0.60**。

| 分组 | 题数 | 误召回率 | Recall@3 | 总体通过率 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| `tune`（选参用） | 60 | 0.0000 | 0.9375 | 0.9500 | 达标 |
| `holdout`（冻结后只算一次） | 20 | 0.0000 | **0.8750** | 0.9000 | **未达标（Recall@3 < 0.90）** |
| 全部（仅记录） | 80 | 0.0000 | 0.9219 | 0.9375 | — |

holdout 的两处漏召回都发生在门槛边缘：`medicine_stop_early_holdout` 的 `medicine-use`
向量分 0.5539、关键词分 0.1667；`confusable_thyroid_or_diabetes_holdout` 的
`thyroid-conditions` 0.5497、`diabetes` 0.5315。前者正是下面要优先修的 `medicine-use`
（“家中剩药能否继续吃”）语料/表达缺口；且 0.55 与 0.56 在 `tune` 上指标完全相同，
差别落在 holdout 的这几分之内。

**线上状态：未启用。** 三条消费方（咨询图本地检索、`POST /api/v1/knowledge/search`、
PPT/Word 文档生成的知识检索）都保持现状；咨询链路继续使用原有 0.72/0.60/0.2，只是数字
已集中到同一模块。之所以不能“按现状数值统一”：把现有 0.72 门槛套到同一份召回上，
全部 80 题的 Recall@3 只有 0.25（`tune` 0.2917）——直接应用会造成严重漏召回，
所以正确资料在 0.5–0.65 区间、0.72 会把它全部丢掉。

复现扫参（不联网、不调用向量服务）：

```powershell
.\.venv\Scripts\python.exe -m app.rag.cli sweep-relevance-gate `
  docs/medical_retrieval_evaluation_v3_results.json --split tune
# holdout 只允许在冻结后复算：
.\.venv\Scripts\python.exe -m app.rag.cli sweep-relevance-gate `
  docs/medical_retrieval_evaluation_v3_results.json --split holdout `
  --frozen-vector-threshold 0.56 --frozen-keyword-threshold 0.2
```

下一步先验证逐候选拒答门槛，再补知识。现有知识唯一完全漏召回题为“家中剩药能否继续吃”，
应先增强 `medicine-use` 的同义表达或排序，不重复造文档。新增知识的顺序为：① 头痛/头晕、
血尿/尿路感染、儿童发热、荨麻疹/湿疹；② 腰痛、颈肩痛、腕扭伤、痛风；③ 结膜炎、
中耳炎、牙痛、痛经、失眠。新增正式资料仍必须逐篇完成来源许可与医学审核。

## 后续升级

正式使用前应把真实来源逐篇走受控导入流程，保留发布机构、原始 URL、版本、版权依据
和医学审核记录；随后使用独立题集重新评测。原型记录不应直接改状态冒充已审核文档。
