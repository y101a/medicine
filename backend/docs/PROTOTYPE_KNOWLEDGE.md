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
| `hybrid` | 关键词 + 向量两路召回后用 RRF 合并（**线上默认，行为未变**） | 是（每题 1 次） |
| `keyword` | 只走 pg_trgm 关键词 | **否，零成本** |
| `vector` | 只走向量，忽略关键词命中 | 是（每题 1 次） |

单路模式复用同一套 RRF 排序，因此会自然退化为该路自己的名次排序；非法模式返回
`RETRIEVAL_MODE_INVALID`。

**2026-09-18 三模式实测（独立题集 `medical_retrieval_evaluation_independent.json`，15 题，`--top-k 3`）：**

| 模式 | 命中 | 命中率 | 平均首位相似度 |
| --- | --- | --- | --- |
| `keyword` | 4/15 | 0.2667 | 0.113 |
| `vector` | 15/15 | 1.0 | 0.640 |
| `hybrid` | 15/15 | 1.0 | 0.613 |

对照：同一套语料上，纯关键词在**同源题集**（`medical_retrieval_evaluation.json`，10 题，题目与
语料由同一过程设计）是 8/10，在**口语化独立题集**上只有 4/15，相差约 3 倍。这说明同源题集
确实会明显高估效果：**凡是要下「召回效果」结论的地方，都必须用独立题集**。独立题集刻意改用
患者口语问法（例如「手背被小区里的猫抓破出血」「体检查出脖子里有个结节」），不照抄语料标题词。

已知局限，不要当作普遍结论：
- 样本只有 15 题，且只测了一个向量模型（`qwen3.7-text-embedding-flash`）。
- 本次 `hybrid` **没有跑出比 `vector` 更好的结果**：两者都是 15/15，排第 1 的都是 13/15，
  只是排第 2 的题目不同。其中 3 题（`lay_term_anti_inflammatory`、
  `drinking_and_urinating_a_lot`、`thyroid_function_abnormal`）hybrid 的首位相似度明显低于
  vector（0.41–0.51 对 0.63–0.70）。
  从代码看原因很明确：`rrf_score` 是关键词名次倒数与向量名次倒数**之和**，排序先比
  `rrf_score`、再比相关性（`app/rag/retrieval.py`）。因此**同时在两路出现的候选几乎总会排在
  只在单路出现的候选之前**，即使后者在单路排第 1、相似度更高。**RRF 的融合方式值得单独复核**
  （是否该给向量路更高权重，或改用加权分数融合），这是一项新待办。但这不等于线上 hybrid 更差：
  线上还有引用审计等环节，本评测只测召回。
- 本评测只判断「期望文档有没有进 top-k」，不评估回答质量，也不评估引用是否被正确标注。

## 后续升级

正式使用前应把真实来源逐篇走受控导入流程，保留发布机构、原始 URL、版本、版权依据
和医学审核记录；随后使用独立题集重新评测。原型记录不应直接改状态冒充已审核文档。
