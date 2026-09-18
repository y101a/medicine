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

**2026-09-18 复核尝试失败（环境原因，不是回归）：**本机 Docker Desktop 未运行
（`docker compose ps` 报 `dockerDesktopLinuxEngine` 命名管道不存在），PostgreSQL 连不上，
因此**未能复核上面的文档 / 文本块 / 向量数量**。后端套件实测 `10 failed / 123 passed / 61 errors`，
失败与错误**逐条核对后全部是数据库连接类**（`test_auth_flow`、`test_consultations`、
`test_embeddings`、`test_prototype_seed`、`test_retrieval`、`test_web_search_integration`、
`test_controlled_ingestion`、`test_health_records`、`test_navigation_api`、`test_profile`），
与当时的改动无关：那次只改 `.gitignore`、语料文件与文档，不含任何 Python 代码。
**恢复数据库后请先 `docker compose up -d`，重新核对上述数量，再据实更新本节**；
在此之前不要把上面的数字当作实时现状。

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

## 后续升级

正式使用前应把真实来源逐篇走受控导入流程，保留发布机构、原始 URL、版本、版权依据
和医学审核记录；随后使用独立题集重新评测。原型记录不应直接改状态冒充已审核文档。
