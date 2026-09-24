# AI 图片生成前后端实施计划

> 状态：2026-09-24 方案已起草，尚未实现代码、迁移或付费调用。
> 产品边界：面向健康科普的 AI 示意图，不作诊断，不生成可冒充真实医疗资料的图片。
> 当前基线：后端 FastAPI + PostgreSQL，前端 Vue 3；已有用户上传图片识别与加密保存链路，但没有图片生成链路。

## 0. 实施前只需确认的一项产品决定

第一版入口和范围二选一：

- **A（推荐）医学科普配图**：只在已完成的医疗类 AI 回答底部显示“生成科普配图”；用户在弹窗中确认或修改一段短提示词后生成。图片与来源回答关联，不自动生成，不阻塞文字回答。
- **B 通用文生图**：在输入区增加独立“生成图片”入口，允许生成与医疗无关的普通图片。这会扩大内容审核、费用治理、UI 和产品定位范围。

本计划其余部分按 **A** 编写。若用户选择 B，需要先扩写普通内容审核规则和独立图库交互，不能直接照搬 A。

## 1. 现状与技术结论

1. 当前 `qwen3.8-flash` 只用于上传图片的分类、OCR 和受限视觉理解，不是图片生成模型。
2. 图片生成必须使用独立的服务端模型和原生 API；不得根据聊天页当前所选模型决定，也不得使用用户自行填写的聊天模型 API Key。
3. 第一版固定使用阿里云百炼 `wan2.6-t2i`，每次只生成 1 张 1K 图片。官方将其列为推荐文生图模型，并支持同步和异步 HTTP 调用。
4. 采用阿里云异步任务协议：任务 ID 与供应商结果 URL 只保留 24 小时，因此成功后必须由后端立即下载、校验、重编码、加密保存，前端永远不能直接拿供应商 URL。
5. 阿里云不同地域的 API Key 与请求地址不能混用；图片生成使用独立的原生 MaaS 地址，不能复用当前 `QWEN_BASE_URL=/compatible-mode/v1`。
6. 输入提示词和输出图片会经过供应商内容审核；供应商失败之外，本项目仍需做本地边界校验、审计和费用限流。

官方依据（核对日期 2026-09-24）：

- [万相文生图 V2 API：模型、地域、同步/异步协议](https://help.aliyun.com/zh/model-studio/text-to-image-v2-api-reference)
- [阿里云百炼文本生成图像总览：模型与分辨率](https://help.aliyun.com/zh/model-studio/text-to-image)
- [万相 2.6：内容审核、24 小时时效与按成功图片计费](https://help.aliyun.com/zh/model-studio/wan-image-generation-api-reference)

## 2. v1 产品范围

### 2.1 允许

- 人体结构、疾病机制、预防、生活方式和就医流程的非诊断性科普插画。
- 三种固定风格：`medical_illustration`（医学科普插画）、`flat_illustration`（简洁扁平插画）、`friendly_cartoon`（友好卡通示意）。
- 四种固定比例：`1:1`、`4:3`、`3:4`、`16:9`。
- 用户编辑短提示词，后端脱敏并附加固定安全约束后发送。
- 生成结果显示在来源 AI 回答下方，可查看、下载和删除；刷新后恢复。

### 2.2 不做

- 不做图片编辑、局部重绘、参考图生图、多图融合或批量组图。
- 不生成或仿造 CT、MRI、X 光、病理切片、检验单、处方、诊断证明、药盒/说明书、医院公章等可能被误认为真实医疗证据的图片。
- 不生成个体化病灶、手术方案、用药剂量或治疗效果前后对比。
- 不承诺图中解剖结构、比例或文字绝对准确；v1 提示词明确要求图内不出现关键剂量、诊断或操作文字。
- 不自动读取健康记录、附件 OCR、原始图片或完整对话来生成图片；只发送用户在生成弹窗中确认的短提示词。
- 不把生成图片注入 RAG、红旗预检、健康记录抽取或后续医学回答上下文。

### 2.3 固定默认值

- 每次 `n=1`，禁止前端改变数量。
- 1K 固定尺寸映射：`1:1=1280*1280`、`16:9=1696*960`、`3:4=1104*1472`、`4:3=1472*1104`。
- `watermark=true`，保留供应商“AI生成”水印；界面另显示“AI 生成·科普示意，不作为诊断依据”。
- 提示词最多 500 字；用户不能自定义 negative prompt，反向提示词由后端固定。
- 成品加密保存 90 天，与现有医学图片保留期一致；删除会话或账号时一并删除。
- 每用户同时最多 1 个未完成任务；10 分钟最多 3 次、自然日最多 10 次。按数据库记录共享限流，不能复用现有进程内 `upload_limits.py` 作为唯一保障。

## 3. 用户流程

1. 医疗 AI 回答正常完成，文字回答先显示，不等待图片。
2. 回答底部显示“生成科普配图”；追问卡、失败/停止回答、紧急分流、普通闲聊不显示。
3. 点击后打开弹窗：短提示词、风格、比例、一次性隐私/费用说明。
4. 用户确认后创建任务，卡片显示“等待生成 / 正在生成”。关闭页面不会取消任务。
5. 前端轮询任务；成功后通过鉴权内容接口加载 Blob，不使用公开 URL/Base64/localStorage。
6. 失败显示受控中文原因和“重新生成”；重新生成必须创建新的 `clientRequestId`，避免误认为原任务免费重试。
7. 用户可以下载或永久删除。删除进行中的任务只表示不再保留结果；供应商若已开始处理，不承诺取消计费。

## 4. 冻结 API 契约

### 4.1 创建任务

`POST /api/v1/consultations/{consultation_id}/image-generations`

请求：

```json
{
  "clientRequestId": "uuid",
  "sourceMessageId": "uuid",
  "prompt": "一张展示呼吸道与肺部关系的友好医学科普插画",
  "style": "medical_illustration",
  "aspectRatio": "4:3",
  "noticeAccepted": true,
  "noticeVersion": "image-generation-v1"
}
```

响应 `202`：

```json
{
  "id": "uuid",
  "sourceMessageId": "uuid",
  "status": "submitted",
  "style": "medical_illustration",
  "aspectRatio": "4:3",
  "model": "wan2.6-t2i",
  "imageAvailable": false,
  "imageExpiresAt": null,
  "createdAt": "2026-09-24T00:00:00Z",
  "updatedAt": "2026-09-24T00:00:00Z"
}
```

相同用户和 `clientRequestId` 必须幂等返回同一任务，绝不能重复调用收费接口。

### 4.2 查询与历史恢复

- `GET /api/v1/image-generations/{id}`：返回单个任务状态；查询时可机会式推进一次供应商状态轮询。
- `GET /api/v1/consultations/{id}/image-generations`：返回该会话全部任务，前端按 `sourceMessageId` 放到对应回答下。
- 状态：`submitted | running | completed | failed | cancelled | expired`。
- 供应商原始错误、任务 URL、提示词和内部请求 ID不得出现在响应中。

### 4.3 获取成品

`GET /api/v1/image-generations/{id}/content`

- 仅所属用户可读；返回规范化后的 `image/webp`。
- 响应头：`Cache-Control: no-store, private`、`Content-Disposition: inline`、`X-Content-Type-Options: nosniff`。
- 未完成返回 `409 IMAGE_GENERATION_NOT_READY`；已过期返回 `410 GENERATED_IMAGE_EXPIRED`；越权与不存在统一 404。

### 4.4 删除/取消

`DELETE /api/v1/image-generations/{id}` → `204`

- 已完成：事务内移除包裹密钥并加入现有持久化物理删除任务。
- 未完成：标记 `cancelled`，后续即使供应商完成也不下载或保存；不承诺撤销供应商费用。

### 4.5 错误码

| HTTP | code | 场景 |
| --- | --- | --- |
| 422 | `IMAGE_GENERATION_NOTICE_REQUIRED` | 未确认处理与费用说明 |
| 422 | `IMAGE_GENERATION_PROMPT_INVALID` | 空、超长或不属于允许的科普配图范围 |
| 422 | `IMAGE_GENERATION_SOURCE_INVALID` | 来源消息不是本会话内已完成的医疗回答 |
| 409 | `IMAGE_GENERATION_ACTIVE` | 用户已有未完成任务 |
| 409 | `IMAGE_GENERATION_NOT_READY` | 成品尚不可读取 |
| 429 | `IMAGE_GENERATION_RATE_LIMITED` | 10 分钟或每日共享限额 |
| 502 | `IMAGE_GENERATION_PROVIDER_REJECTED` | 内容审核或确定性拒绝 |
| 502 | `IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE` | 供应商返回结构错误 |
| 502 | `IMAGE_GENERATION_PROVIDER_UNAVAILABLE` | 网络或服务不可用 |
| 503 | `IMAGE_GENERATION_NOT_CONFIGURED` | 服务端密钥/原生地址未配置 |
| 504 | `IMAGE_GENERATION_PROVIDER_TIMEOUT` | 创建或查询任务超时 |
| 410 | `GENERATED_IMAGE_EXPIRED` | 90 天保留期结束 |

## 5. 数据模型与迁移

实现前先运行 `alembic heads`；当前基线为 `20260923_0021`，候选迁移号为 `20260924_0022`，不得提前假定仍可用。

新增 `generated_images` 表：

- `id`, `user_id`, `consultation_id`, `source_message_id`, `client_request_id`
- `prompt_ciphertext`：保存脱敏后的实际外发提示词，Fernet 加密；不得保存明文或写日志
- `style`, `aspect_ratio`, `status`, `model`, `provider_task_id_ciphertext`
- `storage_key`, `image_key_ciphertext`, `mime_type`, `width`, `height`, `byte_size`
- `image_expires_at`, `image_deleted_at`, `error_code`
- `next_poll_at`, `poll_count`, `created_at`, `updated_at`, `completed_at`

约束与索引：

- 唯一 `(user_id, client_request_id)`；同一用户最多一个 active 状态由事务锁/部分唯一索引保证。
- 用户、会话删除级联；来源消息必须属于同一会话且为已完成医疗助手回答，服务层再次校验。
- 状态与存储字段必须有 CHECK：仅 `completed` 可以持有可解密成品；`expired/cancelled/failed` 不得保留密钥。
- 索引：`(user_id, created_at)` 用于共享限流，`(status, next_poll_at)` 用于恢复轮询，`(consultation_id, source_message_id, created_at)` 用于历史展示。
- 降级若仍有行必须保守失败，要求先通过应用删除，避免遗留加密文件。

生成图片沿用现有图片加密思路，但实施时先从 `medical_image_storage.py` 抽出中性的 `encrypted_image_storage.py`，使用不同 AAD（`generated-image-v1`）。现有 `image_deletion_jobs` 增加存储命名空间或安全分派；孤儿对账必须把 `attachments.image_storage_key` 与 `generated_images.storage_key` 一起视为有效引用，不能误删新成品。

## 6. 后端实现（Codex）

### 6.1 文件级改动

- `backend/app/core/config.py`、`.env.example`：新增 `IMAGE_GENERATION_API_KEY`、原生 `IMAGE_GENERATION_BASE_URL`、模型、超时、轮询、下载大小、90 天保留、10 分钟/每日限额；Key 可显式决定是否回落 `QWEN_API_KEY`，但地址绝不能回落兼容模式 URL。
- `backend/app/models/generated_image.py`、`models/__init__.py`：任务/成品模型与严格状态约束。
- `backend/app/schemas/image_generations.py`：请求、任务状态、历史列表响应。
- `backend/app/services/image_generation_provider.py`：创建异步任务、查询任务；不自动重试“创建任务超时”，避免未知状态下重复计费；查询可安全重试。
- `backend/app/services/image_generations.py`：鉴权、幂等、共享限流、状态机、任务锁、审计、下载与最终入库。
- `backend/app/services/generated_image_validation.py`：供应商 URL 防 SSRF、HTTPS/443、禁止重定向或逐跳复核、DNS 私网地址拒绝、大小上限、真实图片解码、像素上限、去元数据、WebP 重编码。
- `backend/app/services/encrypted_image_storage.py`：从医学图片存储中抽取带命名空间/AAD 的通用能力；保持现有上传图片兼容。
- `backend/app/api/routes/image_generations.py`、`api/router.py`：四个接口。
- `backend/app/image_generation_cli.py`：恢复无人轮询的活跃任务；部署每分钟运行，必须在供应商 24 小时任务/URL 时效内完成下载。
- `backend/app/services/{image_deletion,medical_image_cleanup,consultations,account_deletion}.py`：统一删除、90 天清理、会话/账号级联和孤儿对账。
- `backend/migrations/versions/<new>_image_generation.py`：表、索引、约束及安全降级。
- `backend/tests/test_image_generation.py`：完整回归。
- `backend/docs/{API,DATA_MODEL}.md`、新增 `backend/docs/IMAGE_GENERATION.md`。

### 6.2 提示词与安全

- 用户提示词先 `strip`、长度校验、身份信息脱敏，再作为不可信内容嵌入后端固定模板。
- 固定模板强制：科普插画、非诊断、无患者身份、无医院/医生/公章、无真实检查结果、无处方和剂量、无血腥细节、图内不放关键医学文字。
- 固定 negative prompt；前端不能覆盖安全模板、模型、数量、水印或分辨率。
- 本地先拒绝仿造医疗文件、真实患者病灶、处方剂量、未成年人不当内容、色情、暴恐、自伤指导、违法和冒充真人等请求；供应商审核是第二层，不是唯一防线。
- 只记录受控错误码、状态、耗时、模型和安全请求 ID；禁止记录 prompt、供应商 URL、图片字节、Base64、密钥和响应正文。

### 6.3 任务可靠性

- POST 先写本地幂等行，再创建供应商任务并保存 task ID。
- 创建调用一旦超时且未知供应商是否已受理，标记受控失败，不自动重发；用户明确点击重试才产生新任务和潜在费用。
- GET 与恢复 CLI 使用行锁/租约避免多 worker 同时轮询和重复下载。
- 成功时下载结果到内存，验证、重编码、加密落盘，再在同一数据库事务中切换 `completed`；任一步失败都不暴露临时文件或解密密钥。
- 供应商 URL 不入库；只保存加密 task ID，成品落地后清除 task ID。

## 7. 前端实现（DeepSeek）

DeepSeek 可在后端完成前使用接口桩开发，但不得宣称真实链路通过，也不要修改 `backend/**`。

### 7.1 文件级改动

- 新增 `frontend/src/types/imageGenerations.ts`：请求、状态、风格、比例和错误类型。
- 新增 `frontend/src/api/imageGenerations.ts`：创建、会话列表、查询、鉴权 Blob、删除；创建/查询使用独立长超时。
- 新增 `frontend/src/composables/useImageGeneration.ts`：任务状态机、2→5 秒退避轮询、页面恢复、删除、错误映射、Object URL 创建/释放。
- 新增 `frontend/src/components/ImageGenerationOffer.vue`：回答底部“生成科普配图”入口。
- 新增 `frontend/src/components/ImageGenerationDialog.vue`：提示词、三种风格、四种比例、一次性说明与费用提示；提交后不重复点击。
- 新增 `frontend/src/components/GeneratedImageCard.vue`：等待/生成/成功/失败/过期/删除状态，AI 生成标识、能力边界、查看、下载、删除。
- 修改 `frontend/src/views/HomeView.vue`：仅符合条件的助手回答显示入口；按 `sourceMessageId` 合并历史任务；生成任务与文字回答的 `generating` 状态分离，不能阻塞继续聊天。
- 修改 `frontend/src/types/consultations.ts`（仅在采用 `Message.generatedImages` 合同后）；推荐先使用独立会话列表接口，减少现有消息流契约改动。
- 新增 `frontend/src/views/imageGeneration.test.ts`、`frontend/e2e/image-generation.spec.ts`，更新 `frontend/BROWSER_ACCEPTANCE.md`。

### 7.2 交互硬要求

- 不自动生成、不默认收费；每次都由用户明确点击并确认。
- 弹窗必须写明：“图片由 AI 生成，仅作科普示意，可能存在结构或文字错误，不作为诊断、检查或治疗依据；每次生成可能产生费用。”
- 页面离开不取消任务；重新进入会话后从列表恢复并继续轮询。
- 文字回答生成和图片生成使用两套 loading/AbortController，互不锁死。
- 前端不展示或缓存 prompt 明文历史，不接触供应商 task ID/URL/API Key。
- Blob Object URL 在任务替换、删除和组件卸载时全部 `URL.revokeObjectURL`。
- 下载文件名使用本地固定格式 `AI科普配图-YYYYMMDD.webp`，不使用用户 prompt 拼文件名。
- 375px 窄屏弹窗、键盘操作、`aria-live` 状态和降低动态效果需要验收。

## 8. 测试与验收

### 8.1 后端自动化

- 幂等请求不重复计费；跨用户统一 404；来源消息/会话归属校验。
- 数据库共享的并发、10 分钟和每日限额；进程重启后仍有效。
- prompt 脱敏和允许/拒绝边界；日志不含 prompt、URL、Base64、密钥或供应商正文。
- 创建超时不自动重试；查询超时可重试；供应商审核、限流、无效 JSON、未知状态和 24 小时过期映射。
- URL 防 SSRF、私网 DNS、重定向、超大文件、伪图片、动画、像素炸弹、元数据剥离与 WebP 重编码。
- 加密落盘、鉴权读取、90 天清理、删除重试、会话删除、账号删除、孤儿对账。
- 生成图绝不进入附件上下文、红旗预检、RAG 或健康记录抽取。
- 迁移 upgrade/downgrade/upgrade 与含数据降级保护。

### 8.2 前端自动化

- 入口只出现在允许的医疗回答；紧急/追问/失败回答不出现。
- 用户取消不发请求；重复点击只产生一次 `clientRequestId`。
- 所有状态、轮询退避、刷新恢复、失败重试、过期、删除、下载和 Object URL 释放。
- 图片生成不阻塞发送新消息或文字流式回答。
- 接口返回内部 JSON/HTML 时仍使用统一安全中文错误文案。
- Vitest、生产构建和 Playwright 全量通过。

### 8.3 真实付费验收

须由用户再次明确同意后才调用。只用不含身份信息的合成提示词，至少覆盖：人体结构、疾病机制、预防动作三类允许案例，以及仿造诊断证明、处方剂量、真实病灶三类拒绝案例。人工核对：水印、解剖明显错误、错误文字、刷新恢复、删除、90 天文案和移动端布局。

## 9. 实施顺序与分工

1. 用户确认第 0 节 A/B；默认推荐 A。
2. Codex 重新核对 `alembic heads`，冻结迁移号和第 4 节接口；先做模型、迁移、供应商桩、状态机和测试。
3. DeepSeek 按第 7 节用接口桩开发 UI；只改 `frontend/**`，在 `COORDINATION.md` 7.1 登记。
4. Codex 完成真实接口、加密存储、删除/清理、审计和完整后端测试。
5. 前后端联调：创建→轮询→内容→刷新恢复→删除→跨用户隔离。
6. 用户同意后做一次小规模真实付费验收；通过后再考虑图像编辑、参考图或通用生图。

## 10. 明确不复用的旧链路

- 不复用 `POST /consultations/{id}/images`：它是用户上传、视觉识别和附件上下文入口。
- 不把生成图伪装成 `Attachment(kind=image)`：生成图是助手输出，生命周期、费用和安全语义不同。
- 不把图片生成模型加入聊天 `/models` 下拉框：聊天模型与图片模型能力不同。
- 不复用进程内上传限流作为收费保护：必须使用 PostgreSQL 共享状态。
- 可复用的只有登录/用户隔离、审计表、字段加密、加密图片存储底层、删除任务和统一错误响应模式。
