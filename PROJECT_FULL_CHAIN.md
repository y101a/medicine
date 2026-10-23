# 项目全链路拆分（面试用）

> 目的：让你能在面试里从「一次请求」讲到「整套系统」，并且每一跳都能说出**文件位置**。
> 依据：仓库当前代码（路径与行数均为本机实测）。凡我没读过实现的地方，一律标「待自查」，不写成结论。

## 0. 怎么用这份文档

- **先背主线**（第 2 节）：问诊一次请求的 13 跳。面试时先讲这条，90 秒能讲完。
- **再挑一条分支深讲**（第 3 节）：建议选 B（检索+评测）或 C（异步任务可靠性），这两条最能体现工程能力。
- **横切问题**（第 4 节）按需引用：并发、安全、迁移、测试。
- **第 6 节是自查清单**：面试前把标注「待自查」的地方自己打开读一遍，别在追问里露怯。

## 1. 一张图（全局）

```
浏览器 (Vue 3 + TS + Pinia)
   │  HTTP / 流式
   ▼
FastAPI 路由层  backend/app/api/routes/*.py  (17 个模块, 70 个端点)
   │  依赖注入：Cookie 会话、当前用户、数据库会话
   ▼
Service 层  backend/app/services/*.py  (48 个模块；news / document_renderers / sms_providers 三个子包)
   │
   ├─► LLM 编排   app/ai/graph/*        LangGraph 状态图（triage / retrieval_gate / retrieve / web_search / generation_ready）
   ├─► 检索       app/rag/*             pgvector 余弦 + pg_trgm 关键词 → 加权融合 → 门槛判定
   ├─► 数据       app/models/*(16) → SQLAlchemy 2.0 Async → PostgreSQL(pgvector, pg_trgm) ← Alembic(30 个迁移)
   ├─► 外部工具   app/ai/mcp/*          PubMed / 高德（仅开发环境挂载）
   ├─► 抓取       app/services/news/*   受控抓取器（逐跳 HTTPS 校验）+ 目录/适配器/刷新
   └─► 异步任务   数据库任务表 + FOR UPDATE SKIP LOCKED + 租约 + pg_try_advisory_xact_lock
                    由 CLI 入口驱动：app/*_cli.py / knowledge_graph_worker.py
```

## 2. 主线：一次问诊请求的 13 跳（★必须能白板画出来）

| # | 跳 | 位置 | 讲什么 |
| --- | --- | --- | --- |
| 1 | 输入与交互 | `frontend/src/views/HomeView.vue`（1369 行） | 输入框、附件、模型选择、语音模式、私人知识选择器；入口位置有纪律（不往输入框里堆按钮） |
| 2 | 会话 API 封装 | `frontend/src/api/consultations.ts`、`stores/consultations.ts` | 会话列表/分页/消息、失败重试、状态放 Pinia |
| 3 | 建立会话 | `POST /consultations` → `api/routes/consultations.py:48`（201） | 幂等与并发：`services/consultations.py` 里用 `with_for_update()` 控竞争 |
| 4 | 发消息 + 流式回答 | `POST /consultations/{cid}/stream` → `routes/consultations.py:84`（449 行文件） | 流式返回；前端边收边渲染（`AssistantAnswerCard.vue`） |
| 5 | 红旗预检（安全闸门） | `app/safety/triage.py` + 图节点 `triage` | 危险症状走 `emergency` 分支直出就医分流，**不进入生成**；这是产品边界的技术兜底 |
| 6 | 查询脱敏 | `app/core/privacy.py` | 进模型前去掉可识别信息 |
| 7 | 检索门槛 | 图节点 `retrieval_gate` → `app/ai/graph/retrieval_gate.py` + `rag/relevance.py`（284 行） | 三 profile（`none`/`current-consultation`/`candidate-threshold`）；**有向量分只比向量分**、无当前向量走独立关键词规则、`rerank_score` 只排序**不算证据**、legacy 只有 `similarity` 走兼容路径并单独记 reason |
| 8 | 混合检索 | `app/rag/retrieval.py`（358 行） | pgvector 余弦 + `pg_trgm`（GIN 索引，事务内 `SET LOCAL pg_trgm.word_similarity_threshold`）→ `HYBRID_VECTOR_WEIGHT`/`HYBRID_KEYWORD_WEIGHT` **加权分数融合** |
| 9 | 证据不足处理 | `app/ai/no_evidence.py` | 检索不到合格证据时降级/拒答，不硬编答案 |
| 10 | 上下文装配 | `ai/attachment_context.py`、`ai/private_knowledge_context.py`、`ai/health_context.py`、`ai/card_intent.py`、`ai/follow_up.py`、`ai/generated_image_context.py` | 附件、私人知识库、健康记录、结构化追问卡片分别装配 |
| 11 | 生成 | `app/ai/provider.py` + `ai/registry.py` | OpenAI 兼容 Chat Completions 协议 + 流式增量；模型凭据独立管理（`services/model_credentials.py`、`models/model_credential.py`） |
| 12 | 引用核验 | `app/rag/citation_audit.py` | 回答里的引用编号逐条核验（编号存在性/来源一致性），核验不通过要有处理 |
| 13 | 落库与审计 | `models/consultation.py`、`services/audit_logs.py`、`models/audit_log.py` | 消息持久化 + 审计留痕；前端 `ReferenceSources.vue` 展示引用来源 |

**一句话主线讲法（背下来）**：
「用户在前端发起问诊，请求先过红旗症状预检——危险信号直接走就医分流分支，不交给模型；其余查询脱敏后进入
LangGraph 工作流：先做相关度门槛判定，再用 pgvector 余弦 + pg_trgm 关键词两路召回加权融合，证据不足就降级；
生成后用引用编号核验；结果落库并写审计日志，前端流式渲染并展示引用来源。」

## 3. 分支链路（每条都要能讲到「文件在哪、为什么这么设计」）

### A. 注册 / 登录 / 会话刷新（安全主线）
- 端点：`api/routes/auth.py`（发码、校验、`/register` 201、`/login`、`/password-reset` 204、`/refresh`、`/logout` 204）；
  手机号相关另见 `routes/phone_verification.py`（4 个端点，含 `/change` 换绑）。
- 实现：`services/auth.py`（登录/刷新）、`core/security.py`（`argon2.PasswordHash.recommended()` 哈希 + `encrypt_sensitive` 加密敏感字段）、
  `models/auth_session.py`、`services/phone_verification.py`（限流、一次性 token）、`services/sms_providers/{base,fake}.py`（开发用假短信）。
- 亮点：HttpOnly Cookie；登录态刷新时轮换刷新令牌、撤销旧刷新会话记录，但已签发的访问令牌仍有效至到期；重置密码时提升 `auth_version` 并撤销该用户的刷新会话，使旧访问令牌在下次鉴权时失效；未注册号码返回**同形状诱饵响应**防账户枚举。

### B. 附件 → 私有知识库 → 向量检索（最有技术含量的一条）
- 上传：`routes/attachments.py`（POST/GET/DELETE）+ `core/attachment_upload_middleware.py` + `services/attachments.py`（`with_for_update()` 控并发）。
- 抽取：`services/document_extract.py` + `document_extract_worker.py`（任务表驱动）+ `rag/markdown_importer.py`。
- 私有知识：`routes/private_knowledge.py`（10 个端点：collections CRUD、documents 上传/重试/删除、`/search`）+ `services/private_knowledge.py`。
- 向量化：`rag/vectorizer.py`、`rag/embeddings.py` + `models/private_knowledge.py`（pgvector 列）。
- 检索：`rag/private_retrieval.py`（按 similarity 排序 + 文档名/locator 稳定次序）。
- 讲点：为什么用户私有资料与公共知识库**分开检索**（数据隔离 + 引用来源不同）；失败重试入口在文档粒度。

### C. 医学图片与 AI 配图（异步任务可靠性 + 合规）
- 上传分析：`routes/images.py`（POST/GET）+ `services/image_analysis.py`（**版本化判定**，如 `medical-image-auto-category-v5`）+ `image_validation.py`。
- 存储与删除：`services/medical_image_storage.py`（加密保存）、`image_deletion.py`、`models/image_deletion_job.py`、
  `medical_image_cleanup.py`（`pg_try_advisory_xact_lock` 保单例）、`app/image_cleanup_cli.py`。
- AI 配图：`routes/image_generations.py`、`services/image_generation_intent.py`（自然语言触发，**不新增按钮**）、
  `image_generation_provider.py`、`generated_image_storage.py`、前端 `composables/useImageGeneration.ts`、`components/GeneratedImageCard.vue`。
- 讲点：**删除意图与业务删除同一事务**（迁移 `20260923_0020`）→ 支持重试与磁盘孤儿对账；AIGC 标识与「未经医学审核」是产品硬约束。

### D. 文档生成（DOCX / PPTX，含用户模板）
- 端点：`routes/document_generations.py`（JSON 与 multipart 两条创建路径、查询/列表/文件下载/删除）。
- 实现：`services/document_generation_intent.py`（必须同时命中「生成动作 + 明确格式 + 医学主题」）、
  `document_generation_content.py`、`document_generation_provider.py`、`document_renderers/{docx,pptx}.py`、
  `presentation_template.py`（用户上传 .pptx 模板）、`generated_document_storage.py` / `_deletion.py` / `_validation.py`。
- 前端：`composables/useDocumentGeneration.ts`、`DocumentGenerationNoticeDialog.vue`、`GeneratedDocumentCard.vue`。
- 讲点：用户方案里明确「**不给假进度、不给预计剩余时间**」，只给真实阶段与已等待时长——这是「不编造事实」的工程化。

### E. 新闻门户（对外内容 + 合规）
- 抓取：`services/news/fetcher.py`（逐跳 HTTPS/SSRF 校验、`httpx`）、`catalog.py`、`adapters.py`、`feeds.py`、`refresh.py`、`auto.py`、`updates.py`、`validation.py`、`repository.py`。
- 接口：`routes/news.py`（`GET /news` 分页 + `POST /news/refresh` 202 异步受理）、`models/news.py`、迁移 `20261004_0029_news_portal`、`20261005_0030_news_titles`。
- 前端：`views/PortalView.vue`（513 行）+ `api/news.ts`；分区空状态、来源状态「最后成功」、分页「加载更多」、手动重试与退避轮询。
- 讲点：来源准入双硬标准（**许可明确允许署名转载 + 抓取器可读**）；只存标题/日期/同域链接，不复制正文图片；卡片强制「未经医学审核」。

### F. 语音（输入与输出）
- `routes/voice.py`（转写）、`routes/speech.py`（音色预设 + 消息朗读）、`services/voice_transcription.py`、`speech_synthesis.py`、
  `speech_limits.py`（咨询锁限流）、`audio_validation.py`、`core/voice_upload_middleware.py`；前端 `useVoiceRecorder.ts`、`useSpeechOutput.ts`、`SpeechModeControl.vue`。

### G. 健康记录与图表
- `routes/health_records.py`（8 个端点：采集开关、首次采集、增量抽取、列表、修改、删除）、
  `ai/health_extract.py`、`ai/health_eligibility.py`、`services/health_records.py`（含 `asyncio.create_task` 的计划抽取）；
  前端 `HealthRecordView.vue` + ECharts `HealthRecordCharts.vue` + `utils/healthCharts.ts`。

### H. 就医导航（外部工具）
- `routes/navigation.py`（就近医院、按区域）、`ai/mcp/{server,amap,pubmed,validation,models}.py`；
  前端 `components/HospitalNavigator.vue`。
- 讲点：MCP 只在**开发环境**挂载，生产不挂载；外部返回要过校验再进模型。

### I. 知识图谱（治理流程，尚未接前端）
- `app/knowledge_graph_cli.py`、`knowledge_graph_worker.py` + `services/knowledge_graph_*.py`（候选/评审/发布/快照/词表/注册/Neo4j 共 7 个）+ `models/knowledge_graph.py` + 迁移 `20261002_0028`。
- 讲点：**人工评审 + 发布 + 快照回滚**的治理链路；worker 领取任务带租约。

### J. 检索评测（面试最值钱的一条）
- `rag/evaluation.py`（832 行）+ `rag/cli.py`；冻结 80 题（60 tune / 20 holdout）。
- 实测：keyword R@1 **0.3438** / R@3 0.3594 / MRR 0.3490；vector **0.9375** / 0.9844 / 0.9609；hybrid **0.9219** / 0.9844 / 0.9531。
- 讲点：指标涨了但**未覆盖题误召回 1.0** → 引出统一门槛模块 + 离线扫描 CLI（holdout 必须给冻结阈值，结构上禁止调参泄漏）。

## 4. 横切关注点（被追问时按需展开）

- **配置与错误**：`core/config.py`（Pydantic Settings）、`core/errors.py`（统一错误响应 `{code,message,details}`）。
- **数据层**：`db/`（session/base）、`models/` 16 个模型、30 个 Alembic 迁移（含 up/down 往返验证）。
- **并发与多实例**：`FOR UPDATE SKIP LOCKED` 领取任务（见 `MQ_DECISION.md` 汇总）、租约、`pg_try_advisory_xact_lock` 保单例、业务层 `with_for_update()`。
- **安全**：Argon2 哈希、敏感字段加密、HttpOnly Cookie + refresh + `auth_version`、限流、审计日志、上传中间件校验。
- **外部依赖边界**：MCP 仅开发、抓取器逐跳 HTTPS 校验、代理环境差异（`trust_env`）。
- **质量基线**：后端 54 个测试文件；前端 347 项单测 / 29 文件 + 15 个 Playwright e2e；`frontend/BROWSER_ACCEPTANCE.md` 人工验收清单。
- **协作纪律**：`COORDINATION.md`（所有权、7.1 登记/7.2 报告）、显式暂存提交、互审。

## 5. 面试讲法（三段式）

1. **90 秒主线**：用第 2 节末尾那段话，讲完立刻停，等面试官挑方向。
2. **5 分钟深入**：面试官问检索就讲第 3J（含那个「指标涨了但误召回 1.0」的转折）；问可靠性就讲第 3C（同事务 + 租约 + 孤儿对账）；问安全就讲第 3A（诱饵响应 + auth_version）。
3. **主动给取舍**：每条链路都要能说「为什么不选另一种方案」（不上 MQ、不给假进度、不做自动翻译、不用 RRF 而用加权融合——**注意文档旧文写 RRF，代码是加权融合**）。

## 6. 自查清单（我未验证，面试前请自己读一遍）

- `/consultations/{cid}/stream` 的具体分帧方式（SSE / chunked）——**未验证**。
- `ai/graph/workflow.py` 两套图的完整状态字段与条件边判定细节——我只确认了节点名与条件边存在，**逐条分支未读**。
- `services/consultations.py`（518 行）内部的消息状态机与重试细节——**未读**。
- `rag/evaluation.py`（832 行）的评分与断点身份实现细节——**未读**（数字来自项目文档与 DSH 历史实跑）。
- `ai/mcp/*` 的工具契约与校验规则——**未读**。
- 后端完整测试套件的当前数字（384 项为历史报告）——**本轮未跑**。
- 真实并发下「两个 worker 抢同一任务」的行为——**未实测**（建议面试前跑一次）。
