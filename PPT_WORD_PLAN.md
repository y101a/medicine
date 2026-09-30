# AI 医学科普 PPT / Word 生成前后端实施计划

> 状态：原 PPT/Word 生成功能前后端已实现；2026-09-28 新增的上传 PPT 模板目前仅后端完成，前端待接线，真实模型付费联调与 Office/WPS 人工版式验收仍待进行。
> 产品定位：根据用户明确提出的医学科普主题生成可下载的 `.pptx` / `.docx`，用于健康教育；不生成诊断、处方或可冒充真实医疗文书的内容。
> 分工：Codex 负责 `backend/**`、迁移和后端测试；DeepSeek 负责 `frontend/**`、前端测试与浏览器验收。

> 2026-09-28 模板需求变更：用户确认 PPT 优先级为「上传模板 > 明确要求模板但未上传时使用内置模板 > 其他请求维持白底」。上传模板保留背景图片、母版及页面版式。后端已有独立上传、密文保存、版式复用和删除实现；前端接线及真实 Office/WPS 人工版式验收仍待完成。模板原件只交给本地渲染器，不送给内容模型。

## 0. 已确认决定

已确认：

1. 用户给出主题后现场生成，不是从固定模板库下载成品。
2. 产品同时支持 PPTX 和 DOCX。
3. 不增加常驻“生成文档”按钮；用户在聊天输入框中用自然语言明确提出生成要求。
4. 生成内容只做医学科普，不作个体诊断，不替代医生面诊。
5. v1 不读取用户健康记录、上传附件、图片或完整会话作为素材，只使用本轮明确的通用主题。
6. 生成的 DOCX/PPTX 成品加密保存 30 天；用户可提前永久删除，删除会话或账号时一并清理。

对“PPT 和 Word 都要”的实现解释：产品具备两种格式能力，但单次请求只生成用户明确要求的格式；用户明确说“PPT 和 Word 都生成”时，同一任务输出两份文件。用户没有说出 `PPT/演示文稿/幻灯片` 或 `Word/DOCX/文档` 时不触发，避免猜测格式和误收费。

以上产品决定均已确认；其余低风险实现细节按本方案冻结。

## 1. 现状与关键技术结论

1. 后端已经安装 `python-docx>=1.2,<2` 与 `python-pptx>=1.0,<2`，既用于读取 DOCX/PPTX，也可用于确定性生成 Office Open XML 文件，无需引入 AGPL 依赖。
2. 当前图片生成已有任务状态、幂等、数据库共享限流、加密文件、鉴权下载、删除和过期清理模式，可复用设计思想，但文档不能塞进 `generated_images` 或附件表。
3. PPT/Word 生成包含检索、一次结构化文本生成和本地文件渲染，可能超过普通 HTTP 请求时间；必须使用持久化任务和显式启动的前台 worker，不能依赖 FastAPI `BackgroundTasks` 或未持久化的 `asyncio.create_task`。
4. 严禁在用户电脑注册 Windows 计划任务、服务、开机启动或隐藏常驻进程。开发环境由用户显式运行前台 worker；生产环境只在文档中建议由部署平台托管，本项目不代为注册。
5. 两种格式必须来自同一份经过验证的结构化内容计划，不能分别调用模型生成两套正文，否则会重复费用、引用漂移并产生内容矛盾。
6. v1 不做服务器端 Office/LibreOffice 转 PDF 或图片预览，避免新增大型运行时、字体差异和文档执行面。前端只展示任务状态、内容摘要、来源和鉴权下载入口。

## 2. v1 产品范围

### 2.1 允许

- 人体结构、常见疾病机制、常见症状科普、预防、生活方式、检查术语和分级就医流程。
- 输出 `pptx`、`docx`，或在用户明确要求时同时输出两者。
- 中文简体默认 16:9 PPT；上传模板时沿用其页面尺寸、背景和版式；A4 Word。
- 内容面向普通公众，术语出现时同时给出通俗解释。
- 使用当前医学知识库检索结果，保留原始来源 URL 和来源名称。
- 开发环境可使用明确标注的 prototype 资料；生产环境只允许 `approved` 来源。

### 2.2 不做

- 不生成诊断证明、病历、检查报告、处方、医嘱、假条、医学鉴定、手术同意书、医疗器械注册材料或医院公文。
- 不针对具体患者下诊断、判断影像、推荐处方药、调整剂量或承诺疗效。
- 不自动读取健康记录、病历附件、用户图片、语音转写历史或完整聊天记录。
- PPTX 可上传静态自定义模板；不支持 Word 模板、宏、VBA、外部数据源、远程模板或嵌入网页。
- 不生成 `.doc`、`.ppt`、`.docm`、`.pptm`、PDF、Excel、压缩包或在线协作文档。
- 不自动串联图片生成服务，不将网络图片直接嵌入文档；v1 只使用文字、表格和本地确定性形状。
- 不提供逐页在线编辑、多人协作、云端公开分享或邮件发送。

### 2.3 默认内容规模

- PPTX：6–12 页，包含封面、正文和参考资料页；每页最多 6 个要点，每个要点最多 60 个中文字符。
- DOCX：4–8 个一级章节，正文目标 1200–3000 个中文字符，包含用途说明、正文、就医提示和参考资料。
- 两种格式同时生成时，只调用一次内容模型，共用同一 `content_plan` 和同一组引用。
- 每个文件最大 10 MiB；超过时任务失败，不向用户返回不完整文件。
- 单个任务最长处理 5 分钟；用户同时最多 1 个活跃任务；10 分钟最多 3 次、自然日最多 10 次，使用 PostgreSQL 记录共享限流。

## 3. 自然语言触发与用户流程

### 3.1 确定性意图门控

触发必须同时满足：

1. 明确生成动作：`生成/制作/创建/做/整理成`；
2. 明确格式：`PPT/演示文稿/幻灯片` 或 `Word/DOCX/文档`；
3. 明确医学健康主题；
4. 不包含否定表达；
5. 本轮消息没有附件，且不是紧急红旗分流。

以下不触发：

- “你能生成 PPT 吗？”——能力询问；
- “不要生成 Word”——否定；
- “帮我写一份年度销售 PPT”——非医疗主题；
- “把我上传的病历做成 PPT”——v1 禁止读取患者附件；
- “生成一份人体结构科普资料”——没有明确格式，应由普通聊天回答追问格式，不得自动收费。

消息响应新增：

```json
{
  "documentGenerationIntent": true
}
```

命中时前端跳过 `/stream`，使用刚保存的用户消息创建文档任务；未命中时完全走现有聊天、红旗预检和 RAG 链路。

### 3.3 上传 PPTX 模板（2026-09-28 补充）

- 模板应为普通 `.pptx`，不超过 10 MiB、2–20 页；第一页作为封面样式，其后按页序对应生成页。成品页数超出模板页数时重复最后一页样式。至少提供封面页与正文页；每页宜有标题和正文文字框。保留背景、图片、母版、页面尺寸及文字框位置；模板幻灯片上的可编辑文字会清空，生成内容写入相应文字框。**背景图片中已烘焙的文字或母版上的固定文字无法自动去除**，上传前需由用户检查。复杂动画、SmartArt、图表、表格、音视频、宏、外链和嵌入对象不在支持范围，可能被拒绝。
- 上传模板走 `POST /api/v1/consultations/{consultationId}/document-generations/with-template`，`multipart/form-data` 字段：`clientRequestId`、`sourceMessageId`、`noticeAccepted=true`、`noticeVersion=document-generation-v1`、`templateNoticeAccepted=true`、`file`（`.pptx`）。返回与普通创建接口相同的 202 任务对象，新增 `templateMode: "uploaded"`；普通创建返回 `"builtin"` 或 `"default"`。原 JSON 创建接口不变。只对明确要求 PPT 的本轮用户消息开放上传模板；如同时要求 Word，Word 仍用原版式。
- 上传前在现有生成确认弹窗选择可选模板并说明：模板原件会在本服务加密保存、仅供本次渲染，不送给内容模型；删除任务/会话/账号或保留到期后删除。未确认 `templateNoticeAccepted` 时返回 `PPT_TEMPLATE_NOTICE_REQUIRED`。不应通过普通病历附件入口传模板，那条链路只保留提取文本且生成流程拒绝病历附件。
- 模板和生成文件共用可靠删除队列；失败任务即删除模板。输出仍必须保留 AI 科普免责声明和来源 URL。拒绝码：`PPT_TEMPLATE_TOO_LARGE` 413、`PPT_TEMPLATE_TYPE_NOT_ALLOWED` 415、`PPT_TEMPLATE_INVALID` 422、`PPT_TEMPLATE_NOT_APPLICABLE` 422、`PPT_TEMPLATE_NOTICE_REQUIRED` 422、同一来源消息改传不同模板 `DOCUMENT_GENERATION_TEMPLATE_CONFLICT` 409。当前后端专项测试覆盖带背景图片和指定文字框的模板，以及上传、加密存储、生成、下载、删除；复杂真实模板的 Office/WPS 视觉验收待前端接线后执行。

### 3.2 交互流程

1. 用户发送“帮我生成一份关于高血压预防的 PPT”。
2. 消息接口返回 `documentGenerationIntent=true`。
3. 首次使用自动弹一次费用、AI 生成、医学边界和保留期说明；取消则不创建任务，再次明确请求时重新弹出。
4. 确认后前端创建任务，任务卡显示在该用户消息下方。
5. worker 执行检索、结构化内容生成、校验和 Office 渲染。
6. 页面通过查询接口轮询；离开页面不取消任务，重新进入会话可恢复。
7. 完成后显示格式、文件大小、章节/页数、来源数量、到期时间、下载和永久删除。
8. 删除活跃任务只标记取消；已发生的模型费用不保证撤销。

## 4. 医学内容与引用流水线

### 4.1 一次内容、两种渲染

```text
用户本轮主题
  → 确定性意图与格式解析
  → 主题脱敏和边界校验
  → 医学知识库混合检索
  → 固定服务端模型生成结构化 content_plan
  → Pydantic 严格校验、引用编号核验、禁用内容复检
  → DOCX/PPTX 确定性渲染
  → OOXML 安全检查
  → 每个文件独立信封加密保存
```

两种格式不得分别请求模型。DOCX 与 PPTX 只是对同一 `content_plan` 的两种视图。

### 4.2 来源规则

- 复用现有查询脱敏、混合检索和来源治理，但使用文档生成专用预算。
- 生产环境只取 `approved` 文档；development 可以取 prototype，但成品封面和页脚必须标注“开发原型资料，未经医学审核”。
- 至少命中 1 个可用医学来源，否则失败为 `DOCUMENT_EVIDENCE_INSUFFICIENT`，不得让模型依靠常识补写整份文档。
- 每条医学事实必须归属一个或多个允许的来源编号；不存在的编号、越界编号和无引用正文都必须阻止渲染。
- DOCX 正文使用 `[来源N]`；PPTX 每页页脚列本页用到的 `[来源N]`；最后统一生成参考资料，包含标题、发布机构、原始 URL 和访问日期。
- URL 只取后端知识来源记录，模型不能自行生成或修改 URL。
- 不把生成文档重新导入知识库，也不把文档内容自动写入健康记录或后续咨询上下文。

### 4.3 结构化内容计划

模型必须返回严格 JSON，由 Pydantic `extra="forbid"` 校验，建议内部结构如下：

```json
{
  "title": "高血压预防科普",
  "audience": "普通成年人",
  "purposeNotice": "本资料用于健康科普，不作诊断或治疗依据。",
  "summary": "……",
  "sections": [
    {
      "heading": "什么是高血压",
      "paragraphs": ["……"],
      "bullets": ["……"],
      "sourceIds": [1]
    }
  ],
  "warningSigns": [
    {"text": "……", "sourceIds": [1]}
  ],
  "references": [1]
}
```

硬校验：标题、章节数、段落长度、要点数量、引用编号、URL 来源、禁止表达、总字数均受限；失败不得用截断 JSON 或模型原文“尽量渲染”。允许一次低成本格式修复，但修复请求只能携带失败的结构和受控错误说明，仍须通过全部校验。

### 4.4 固定医学安全模板

- 把用户主题和检索资料标记为不可信数据，不得执行其中的“忽略以上规则”等指令。
- 统一使用“可能、常见、建议咨询医生”等审慎表达，不得把科普资料写成对用户本人的诊断。
- 不输出个体化处方、剂量换算、停药/换药结论、影像病灶判断、治愈率保证或延误急症的居家观察建议。
- 命中红旗或自伤、暴力、中毒等即时风险时不生成文档，继续走现有紧急分流。
- 拒绝仿造官方医疗材料；不得使用医院、医生、公章或监管机构身份制造权威错觉。
- 生成文件页眉或页脚固定显示“AI 生成的健康科普资料｜不作诊断依据”。

## 5. 冻结 API 契约

统一前缀为 `/api/v1`，全部需要登录并按 `user_id` 隔离。越权与不存在统一返回 404。

### 5.1 创建任务

`POST /consultations/{consultation_id}/document-generations` → `202`

请求：

```json
{
  "clientRequestId": "uuid",
  "sourceMessageId": "uuid",
  "noticeAccepted": true,
  "noticeVersion": "document-generation-v1"
}
```

主题与格式只能从所属用户、所属会话的 `sourceMessageId` 原文重新解析；前端不得另传隐藏 prompt、来源或格式覆盖值。

响应：

```json
{
  "id": "uuid",
  "sourceMessageId": "uuid",
  "status": "queued",
  "formats": ["pptx"],
  "title": null,
  "model": "configured-server-model",
  "files": [],
  "sourceCount": 0,
  "errorCode": null,
  "expiresAt": null,
  "createdAt": "2026-09-27T00:00:00Z",
  "updatedAt": "2026-09-27T00:00:00Z"
}
```

同一用户、同一 `clientRequestId` 必须幂等返回原任务，不能重复调用模型。`sourceMessageId` 必须是触发过文档意图的用户消息，且未关联另一文档任务。

### 5.2 状态与历史

- `GET /document-generations/{id}`：单任务状态。
- `GET /consultations/{consultation_id}/document-generations`：当前会话全部任务。
- 状态：`queued | generating | rendering | completed | failed | cancelled | expired`。
- `files` 仅在完成后出现：

```json
{
  "id": "uuid",
  "format": "pptx",
  "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "byteSize": 284321,
    "pageCount": 9,
  "available": true
}
```

`pageCount` 对 PPTX 返回准确幻灯片数；DOCX 在不引入 Office/LibreOffice 渲染器的 v1 中
无法可靠计算最终分页，因此固定返回 `null`，前端不得显示虚构页数。

响应不得包含用户原文、模型 prompt、结构化内容全文、密文、存储路径、供应商响应或内部堆栈。

### 5.3 鉴权下载

`GET /document-generations/{generation_id}/files/{file_id}/content`

- DOCX MIME：`application/vnd.openxmlformats-officedocument.wordprocessingml.document`。
- PPTX MIME：`application/vnd.openxmlformats-officedocument.presentationml.presentation`。
- 响应头：`Cache-Control: no-store, private`、`Content-Disposition: attachment; filename*=UTF-8''...`、`X-Content-Type-Options: nosniff`。
- 文件名固定为 `AI医学科普-YYYYMMDD.docx` / `.pptx`，不拼接用户主题、姓名或其他隐私文本。
- 未完成返回 `409 DOCUMENT_GENERATION_NOT_READY`；过期返回 `410 GENERATED_DOCUMENT_EXPIRED`。

### 5.4 删除或取消

`DELETE /document-generations/{id}` → `204`

- 活跃任务标记 `cancelled`，worker 在每个阶段开始前复查状态。
- 已完成任务在事务内销毁文件包裹密钥并创建持久化物理删除任务。
- 删除会话或账号时同样级联逻辑删除并可靠物理清理文件。
- 审计和最小化费用记录不保存主题正文，按既有治理期限保留。

### 5.5 错误码

| HTTP | code | 场景 |
| --- | --- | --- |
| 422 | `DOCUMENT_GENERATION_NOTICE_REQUIRED` | 首次说明未确认或版本不匹配 |
| 422 | `DOCUMENT_GENERATION_REQUEST_INVALID` | 未明确格式、主题为空/过长或不是允许的医学科普请求 |
| 422 | `DOCUMENT_GENERATION_SOURCE_INVALID` | 来源消息、会话或意图不合法 |
| 422 | `DOCUMENT_GENERATION_CONTENT_REJECTED` | 请求触碰诊断、处方、仿造医疗材料等边界 |
| 422 | `DOCUMENT_EVIDENCE_INSUFFICIENT` | 当前知识库没有足够可引用资料 |
| 409 | `DOCUMENT_GENERATION_ACTIVE` | 用户已有活跃任务 |
| 409 | `DOCUMENT_GENERATION_NOT_READY` | 文件尚不可下载 |
| 429 | `DOCUMENT_GENERATION_RATE_LIMITED` | 共享频率或每日限额 |
| 500 | `DOCUMENT_RENDER_FAILED` | 结构有效但本地 Office 渲染失败 |
| 502 | `DOCUMENT_MODEL_INVALID_RESPONSE` | 模型 JSON 或引用反复校验失败 |
| 502 | `DOCUMENT_MODEL_UNAVAILABLE` | 模型服务不可用 |
| 503 | `DOCUMENT_GENERATION_NOT_CONFIGURED` | 服务端模型或 Key 未配置 |
| 504 | `DOCUMENT_MODEL_TIMEOUT` | 内容生成超时 |
| 410 | `GENERATED_DOCUMENT_EXPIRED` | 成品已超过保留期 |

## 6. 数据模型与迁移

实现前必须重新运行 `alembic heads`。`20260927_0024` 只是当前候选编号，不得在未核对共享工作区时直接使用。

### 6.1 `generated_documents`

- `id`, `user_id`, `consultation_id`, `source_message_id`, `client_request_id`
- `requested_formats`：受控 JSON 数组，仅允许 `docx/pptx`，去重且最多 2 项
- `status`, `model`, `error_code`
- `title_ciphertext`：完成后用于界面显示，密文保存
- `content_plan_ciphertext`：经过严格验证的同一份结构化内容，密文保存
- `source_snapshot_ciphertext`：实际使用的来源标题、机构、URL、访问日期和编号快照，密文保存
- `source_count`, `attempt_count`, `lease_owner`, `lease_expires_at`
- `expires_at`, `created_at`, `updated_at`, `completed_at`, `cancelled_at`

约束与索引：

- 唯一 `(user_id, client_request_id)`；
- 同一用户只允许一个 `queued/generating/rendering` 任务；
- 状态枚举与时间、内容字段建立 CHECK；
- `(status, lease_expires_at, created_at)` 支持 worker 领取；
- `(consultation_id, source_message_id, created_at)` 支持历史恢复；
- `(user_id, created_at)` 支持数据库共享限流；
- 用户、会话、来源消息删除时级联任务记录，但物理文件删除意图必须先可靠持久化，不能只依赖 ORM cascade。

### 6.2 `generated_document_files`

- `id`, `generation_id`, `format`
- `storage_key`, `file_key_ciphertext`, `mime_type`, `byte_size`, `page_count`
- `content_sha256`, `created_at`, `deleted_at`
- 唯一 `(generation_id, format)`；只有 `completed` 主任务可以持有可解密文件。
- DOCX/PPTX 每个文件使用独立数据密钥、随机 nonce 和独立 AAD，例如 `generated-document-v1:{generation_id}:{format}`。

### 6.3 可靠物理删除

新增独立 `generated_document_deletion_jobs`，保存受控 `storage_key`、重试次数、下次重试时间和最后错误码，不保存正文、主题、路径之外的用户内容。删除任务、会话、账号和到期清理都在同一数据库事务中销毁包裹密钥并入队；worker 幂等删除磁盘文件并支持孤儿对账。

不要把非图片文件塞进 `image_deletion_jobs`，也不要把 Office 成品作为用户附件回流到模型上下文。

## 7. 后端实现（Codex）

### 7.1 文件级计划

- `backend/app/core/config.py`、`.env.example`：`DOCUMENT_GENERATION_*` 模型、超时、任务租约、保留期、大小和限流设置；服务端 Key 可显式回落 `QWEN_API_KEY`，不使用用户自带聊天 Key。
- `backend/app/models/generated_document.py`、`models/__init__.py`：任务、文件和删除任务模型。
- `backend/app/schemas/document_generations.py`：创建、状态、文件和列表响应。
- `backend/app/services/document_generation_intent.py`：确定性动作、格式、否定和医学主题门控。
- `backend/app/services/document_generation_content.py`：检索、固定系统提示、严格 JSON、Pydantic 校验、引用核验和一次受控格式修复。
- `backend/app/services/document_renderers/{docx,pptx}.py`：只接收已经验证的内部 `content_plan`，不读取用户原文。
- `backend/app/services/generated_document_validation.py`：ZIP/OOXML 结构、文件大小、关系文件和元数据检查。
- `backend/app/services/generated_document_storage.py`：独立目录、路径安全、信封加密、鉴权解密和哈希核对。
- `backend/app/services/document_generations.py`：鉴权、幂等、共享限流、状态机、worker 领取、删除和审计。
- `backend/app/api/routes/document_generations.py`、`api/router.py`：创建、查询、列表、下载和删除。
- `backend/app/document_generation_cli.py`：`--once` 和显式前台 `--watch`；不得注册计划任务或系统服务。
- `backend/app/services/{consultations,account_deletion}.py`：意图字段、会话/账号删除接线。
- 新迁移、`backend/tests/test_document_generation.py`、`backend/docs/{API,DATA_MODEL,DOCUMENT_GENERATION}.md`。

### 7.2 模型与密钥

- 文档内容生成使用固定服务端模型和固定安全模板，不跟随聊天下拉框，不使用用户自带 Key。
- 只向模型发送：脱敏后的通用主题、受控受众描述、允许的检索片段和编号、严格 JSON schema。
- 不发送用户名、手机号、身份证、健康记录、附件原文、图片分析或此前聊天历史。
- 日志只允许任务 ID、状态、耗时、模型、来源数量和受控错误码；禁止记录主题、检索正文、模型响应、生成文件字节、密钥或密文。

### 7.3 DOCX 渲染要求

- A4、常规页边距；标题、一级/二级标题、正文、要点、警示框和参考资料使用固定样式。
- 页眉/页脚固定医学边界；页码启用。
- 中文字体按字体名称声明，不把未授权字体文件嵌入文档；优先使用系统常见的微软雅黑/等线并提供西文字体回退。
- 仅生成普通 OOXML，不含宏、ActiveX、OLE、外部模板、远程图片、外部数据连接或自定义 XML 指令。
- 文档核心属性使用产品名作为 creator，不写用户姓名、主题原文或内部模型 prompt。

### 7.4 PPTX 渲染要求

- 默认/内置模板为 16:9 固定尺寸；上传模板时沿用其尺寸与静态视觉版式，正文内容仍按受控结构填充。
- 使用文本框、表格和 `python-pptx` 原生形状；v1 不下载或嵌入互联网图片。
- 自动缩小只能在受控字号范围内；内容仍溢出时直接失败或拆页，不能把文字缩到不可读。
- 每页固定显示 AI 科普边界和本页来源编号；讲者备注不写隐藏 prompt 或用户信息。

### 7.5 OOXML 输出安全检查

生成后重新以 ZIP 只读打开并验证：

- 扩展名、MIME 和 `[Content_Types].xml` 一致；
- 不存在 `vbaProject.bin`、ActiveX、OLE、嵌入包或未知可执行内容；
- `.rels` 不含外部模板、远程图片、文件路径或非来源白名单超链接；
- 解压条目数、单项大小、总体积和压缩比受限；
- 不存在绝对路径、`..`、驱动器路径或 ZIP Slip；
- 核心属性、批注、备注和自定义属性不含用户身份、提示词或内部路径；
- 文件可以被 `python-docx` / `python-pptx` 重新打开，并能读回预期章节/幻灯片数。

自动化验证只证明 OOXML 结构正确，不代表 Office/WPS 的最终视觉布局正确；真实样例仍需人工打开验收。

## 8. 前端实现（DeepSeek）

DeepSeek 可以在后端完成前按本节使用接口桩开发，但不得修改 `backend/**`，也不得宣称真实生成链路通过。

### 8.1 文件级计划

- `frontend/src/types/documentGenerations.ts`：格式、状态、任务和文件类型。
- `frontend/src/api/documentGenerations.ts`：创建、任务查询、会话列表、Blob 下载、删除。
- `frontend/src/composables/useDocumentGeneration.ts`：幂等 ID、任务恢复、2→5 秒退避轮询、下载、删除、Object URL 释放和错误映射。
- `frontend/src/components/DocumentGenerationNoticeDialog.vue`：首次费用、隐私、AI 生成、用途和保留期说明。
- `frontend/src/components/GeneratedDocumentCard.vue`：各状态、格式、页数、大小、来源数、到期、下载和删除。
- `frontend/src/types/consultations.ts`：增加 `documentGenerationIntent`。
- `frontend/src/views/HomeView.vue`：命中意图后跳过 `/stream`，确认说明后创建任务；按 `sourceMessageId` 把任务卡放在对应用户消息下。
- `frontend/src/stores/composerHints.ts`：按 `document-generation-v1` 记录说明版本；取消不记忆。
- `frontend/src/views/documentGeneration.test.ts`、`frontend/e2e/document-generation.spec.ts`、`frontend/BROWSER_ACCEPTANCE.md`。

### 8.2 交互硬要求

- 不增加生成按钮、侧栏入口或格式选择弹窗；格式来自用户明确写出的自然语言。
- 同时要求两种格式时只显示一个任务卡，完成后提供两个下载项。
- 首次说明原文至少包含：“内容由 AI 根据当前知识库生成，可能存在遗漏或错误，仅作健康科普，不作诊断、处方或治疗依据；生成可能产生模型费用；文件将在约定期限后删除。”
- 用户取消首次说明：不得调用创建接口，不记版本，不伪造助手回答；给一条短暂、可关闭提示。
- 页面刷新、切换会话后从列表恢复；失败只显示受控中文原因。
- 下载走鉴权 Blob，不打开后端存储路径，不把文件或内容放入 localStorage/IndexedDB。
- 下载产生的 Object URL 在触发后及时回收；组件卸载、任务删除和重复下载都不得泄漏。
- 生成过程不锁住聊天输入框，用户可以继续发送其他消息。
- 任务卡必须清楚显示“AI 生成的健康科普资料”，不能伪装成医院或医生签发文件。

## 9. 测试与验收

### 9.1 后端自动化

- 意图：PPT、Word、两者、同义词、否定、能力询问、非医学、缺格式、带附件、红旗请求。
- 创建：幂等、来源消息归属、跨用户统一 404、活跃任务冲突、10 分钟/每日共享限流。
- 内容：无资料拒绝、生产环境不取 prototype、引用缺失/越界/伪 URL 拒绝、结构超限、提示注入、一次修复仍失败。
- 安全：诊断证明、处方、剂量、影像判断、病历附件改写和冒充机构请求全部拒绝。
- DOCX/PPTX：章节/页数、引用页、固定边界、无宏、无外部关系、无用户元数据、ZIP Slip/压缩炸弹检查、重新打开成功。
- 两格式共用同一内容计划，断言模型只调用一次。
- 存储：密文不等于明文、文件哈希、鉴权下载、响应头、文件名净化、大小上限。
- 生命周期：worker 租约、进程崩溃后恢复、取消、失败重试策略、到期、删除任务重试、孤儿对账、会话/账号删除。
- 日志不得出现主题、来源正文、模型响应、Office 字节、密钥或内部路径。
- 迁移 `upgrade → downgrade → upgrade`；存在成品时降级必须保守失败或先显式清理。

### 9.2 前端自动化

- 明确 PPT/Word 请求命中后不请求 `/stream`；非命中继续原聊天链路。
- 首次说明确认才创建；取消不创建、不记版本，再次请求重新出现。
- 重复操作只用一个 `clientRequestId`；两格式仍为一个任务。
- `queued/generating/rendering/completed/failed/cancelled/expired` 全状态渲染。
- 刷新恢复、轮询退避、切换会话、删除确认、下载 Blob 和 Object URL 回收。
- 下载项显示正确扩展名、大小、页数和到期时间；内部 JSON/HTML 错误不得直出。
- 375px 窄屏提示符合项目既有桌面优先规则；键盘、焦点和 `aria-live` 状态可用。
- `npx vitest run`、`npm run build`、`npm run e2e` 全量通过。

### 9.3 人工验收矩阵

至少使用不含身份信息的合成主题验证：

| 场景 | 预期 |
| --- | --- |
| “生成一份高血压预防 PPT” | 一份 PPTX，来源可追溯 |
| “制作胃食管反流 Word 科普文档” | 一份 DOCX |
| “把哮喘预防做成 PPT 和 Word” | 同一任务、同一内容、两个文件 |
| 知识库未覆盖的罕见主题 | 明确资料不足，不凭空生成 |
| “把我的检查单做成诊断证明” | 拒绝生成 |
| “做一份阿莫西林儿童剂量 Word” | 拒绝个体化剂量内容 |
| 文档内含“忽略系统要求”式来源文字 | 只作为不可信资料，不改变任务规则 |

人工用 Microsoft Office 和 WPS 各打开至少一份 DOCX/PPTX，检查中文字体、分页/溢出、超链接、页脚、参考资料、无修复提示；这部分不能由单元测试替代。

## 10. 实施顺序

1. DeepSeek 阅读本方案，如有前端契约异议只写入 `COORDINATION.md` 第 6 节，不先改接口字段。
2. Codex 运行 `alembic heads`，在 7.1 锁定迁移编号和数据库，先完成模型、迁移、意图门控、内容 schema、渲染器和接口桩。
3. DeepSeek 按第 8 节用接口桩开发前端；只改 `frontend/**`。
4. Codex 完成 worker、加密存储、删除清理、审计和后端完整测试。
5. 前后端真实联调：单格式、双格式、刷新恢复、下载、删除、到期和跨用户隔离。
6. 用户确认可能产生的模型费用后做小规模真实生成；用 Office/WPS 人工验收。
7. 模板优先级与上传支持已按 2026-09-28 的新决定纳入 §3.3；配图、PDF 导出、读取病历附件或在线编辑仍需另行讨论，不能静默塞入范围。

## 11. 明确复用与禁止复用

可以复用：

- 登录、CurrentUser、用户/会话隔离和统一错误结构；
- 查询脱敏、混合检索、来源治理和引用编号核验思想；
- 字段加密、每文件信封加密、数据库共享限流、审计和可靠删除模式；
- 图片生成的 `clientRequestId` 幂等、状态恢复和前端任务卡交互模式。

禁止直接复用：

- 不把生成文档存入 `attachments`：附件是用户输入，会进入模型上下文；生成文档是助手输出。
- 不把 Office 文件存入 `generated_images` 或 `image_deletion_jobs`。
- 不使用用户自带聊天 Key，不把文档生成模型放入聊天模型下拉框。
- 不复用上传文件解析 worker 作为生成 worker：一个处理不可信输入，一个生产受控输出，权限和失败语义不同。
- 不使用 Windows 计划任务、系统服务或任何关闭项目后仍运行的本机自启动。
- 不因生成了引用页就声称医学正确；引用核验只证明编号和来源对应，不替代医学审核。
