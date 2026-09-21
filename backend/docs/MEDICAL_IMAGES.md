# 医学图片上传与受限识别设计

> 状态：2026-09-22 后端已实现并通过自动化测试；前端已由 DeepSeek 接线，待真实阿里云与浏览器联调。
> 产品边界：健康科普与就医分流，不作确诊，不替代医生，不判读医学影像病灶。

## 1. 已确认决策

- 支持三类图片：`report`（报告/检查单照片）、`medical_imaging`（X 光、CT、MRI 等片子照片）、
  `body_photo`（患处或身体照片）。上传时由用户选择类别，后端把它当作处理提示而不是可信事实。
- 报告照片允许 OCR；医学影像只识别影像类型、可见文字、部位与拍摄质量，不判断病灶；身体照片只整理
  肉眼可见且非诊断性的事实，并结合用户文字提供就医分流，不输出疾病识别结论。
- 原始上传字节不保存。后端完成真实类型校验、方向纠正、缩放、元数据移除和 WebP 重编码后，保存规范化图片。
- 规范化图片使用每图独立数据密钥加密，默认自上传起保留 90 天；识别文字和受限摘要作为加密附件分块，
  随附件/会话保留。图片到期后，历史消息显示“图片原件已按保留策略清理”，识别结果仍可查看。
- 用户删除附件、会话或账号时，立即删除数据库中的包裹密钥，使图片密文不可解密，并异步/补偿删除密文文件。
- 图片会在用户单独同意后发送给固定的服务端阿里云视觉模型。不得使用用户自带模型 Key，不得由当前聊天模型
  直接读取图片，也不得把图片、Base64、OCR 正文、文件名或哈希写入日志。
- 图片识别结果不参与确定性红旗预检；红旗预检仍只处理用户主动输入的文字。界面必须提示用户把胸痛、呼吸困难、
  意识异常、大出血等紧急表现直接写出或拨打 120，不能等待图片识别。

## 2. v1 限额与格式

- 接受 JPEG、PNG、WebP；不接受 GIF/动图、HEIC、TIFF、BMP、SVG、PDF 或伪装扩展名。
- 单张原始图片不超过 5 MiB，像素总量不超过 20,000,000，宽高均至少 32 px，宽高比不超过 20:1。
- 后端统一执行 EXIF 方向纠正、移除全部元数据、最长边缩到不超过 2400 px、转为静态 WebP（quality 82）。
- 每条消息最多 3 张图片；图片与文档合计仍不得超过现有 `attachmentIds` 的 5 项上限。
- 前端可在上传前压缩以改善体验，但后端必须重新解码、校验和规范化，不能信任前端 MIME、扩展名、尺寸或类别。

## 3. API 契约

### 上传

`POST /api/v1/consultations/{consultation_id}/images`

`multipart/form-data`：

- `file`: 单张图片。
- `imageCategory`: `report | medical_imaging | body_photo`。
- `noticeAccepted`: 必须为 `true`。
- `noticeVersion`: 必须为 `medical-image-upload-v1`。

成功返回 `201`：

```json
{
  "id": "uuid",
  "displayName": "检查单.jpg",
  "kind": "image",
  "imageCategory": "report",
  "mimeType": "image/webp",
  "byteSize": 234567,
  "width": 1600,
  "height": 1200,
  "charCount": 860,
  "preview": "白细胞计数……",
  "status": "ready",
  "imageAvailable": true,
  "imageExpiresAt": "2026-12-20T10:00:00Z",
  "createdAt": "2026-09-21T10:00:00Z"
}
```

上传只完成识别并把图片放入咨询草稿附件区，不自动发送消息。消息继续通过现有 `attachmentIds` 绑定图片；
同一图片只能在所属用户、所属咨询中使用。

### 读取规范化图片

`GET /api/v1/attachments/{attachment_id}/content`

- 必须登录并校验用户与咨询归属。
- 返回解密后的 `image/webp`，响应必须包含 `Cache-Control: no-store, private`、
  `X-Content-Type-Options: nosniff`，不提供公开 URL，不支持跨用户读取。
- 图片已到期返回 `410 IMAGE_EXPIRED`；文档附件或不存在/不属于当前用户统一返回 `404 ATTACHMENT_NOT_FOUND`。

### 列表、消息与删除

- 复用 `GET /consultations/{id}/attachments`、消息 `attachmentIds`、`MessageOut.attachments` 与
  `DELETE /attachments/{id}`。
- 附件输出扩展为可辨识联合类型；文档原字段保持兼容，图片增加 `imageCategory`、`mimeType`、尺寸、
  `imageAvailable` 和 `imageExpiresAt`。
- 删除图片附件时同时删除识别分块、包裹密钥与图片密文；历史消息继续使用现有墓碑机制。

## 4. 错误码

| HTTP | code | 场景 |
| --- | --- | --- |
| 413 | `IMAGE_TOO_LARGE` | 超过 5 MiB |
| 415 | `IMAGE_TYPE_NOT_ALLOWED` | 非 JPEG/PNG/WebP 或真实类型不符 |
| 422 | `IMAGE_NOTICE_REQUIRED` | 未确认图片处理与外发说明 |
| 422 | `IMAGE_CATEGORY_INVALID` | 类别不在白名单 |
| 422 | `IMAGE_INVALID` | 无法解码、动图、图片炸弹、尺寸或比例非法 |
| 422 | `IMAGE_NO_TEXT` | `report` 类图片没有可读取文字 |
| 422 | `IMAGE_UNSUITABLE` | 无法在产品安全边界内处理 |
| 429 | `UPLOAD_RATE_LIMITED` | 图片上传限流 |
| 502 | `IMAGE_PROVIDER_FAILED` | 视觉服务失败或返回不合约 |
| 504 | `IMAGE_PROVIDER_TIMEOUT` | 视觉服务超时 |
| 503 | `IMAGE_NOT_CONFIGURED` | 服务端视觉模型未配置 |
| 410 | `IMAGE_EXPIRED` | 规范化图片已按 90 天策略清理 |

错误响应不得包含服务商原文、Base64、OCR 内容、文件名或本地路径。

## 5. 服务端视觉处理

- 新增独立设置：`IMAGE_ANALYSIS_API_KEY`（未设置时可回落服务端 `QWEN_API_KEY`）、
  `IMAGE_ANALYSIS_BASE_URL`（只允许阿里云百炼 HTTPS 兼容地址）、
  `IMAGE_ANALYSIS_MODEL=qwen3.8-flash`、超时、大小、像素、保存天数和存储目录。
- 使用 OpenAI 兼容图文消息，把规范化图片临时编码为 Data URI；请求完成后立即释放内存。
- 固定系统提示和结构化 JSON 合约，至少返回：实际类别、OCR 文本、非诊断性可见事实、质量限制与安全提示。
- `medical_imaging` 禁止输出病灶、阴影、骨折、肿瘤等判读结论，只允许说明影像类型/部位/可见标签/拍摄质量，
  并建议结合正式影像报告咨询医生。
- `body_photo` 禁止给出疾病名称或概率，只允许颜色、范围、是否有明显出血等非诊断性描述；回答阶段必须结合
  用户文字决定科室或紧急程度。模型输出仍视为不可信数据，进入咨询上下文前执行身份信息脱敏与结构校验。
- `report` 保存 OCR 文字；不得把模型根据图片推测出的诊断补进 OCR 事实。

## 6. 存储、加密与清理

- `attachments.kind` 增加 `image`；新增 `image_category`、规范化 MIME、宽高、随机存储键、包裹密钥、
  `image_expires_at`、`image_deleted_at`、分析模型与分析版本等可空字段。迁移编号预留 `20260921_0018`，
  开工前必须运行 `alembic heads` 再锁定。
- 每张图片生成随机 256-bit 数据密钥，使用 AES-256-GCM 加密规范化 WebP；随机 nonce 与密文保存在
  `data/medical_images/` 的随机对象名中。数据密钥用现有字段主密钥包裹后存数据库，明文密钥不得落盘或记录日志。
- 临时上传/重编码文件无论成功失败都在 `finally` 清理；未绑定任何消息的图片上传 24 小时后删除；
  规范化图片自上传起 90 天后删除。识别分块不因图片到期而删除。
- 提供幂等清理服务和 CLI（先支持 `--dry-run`），由部署层每日执行；使用 PostgreSQL advisory lock 防止多实例重复清理。
- 主动删除先在事务中删除包裹密钥并提交，完成密码学删除，再尽力删除密文对象；遗留无主密文由清理任务补偿。
- 备份中的图片密文最多保留 30 天；由于包裹密钥已删除，主动删除后的备份密文不得恢复为可解密状态。

## 7. 审计与同意

- 首次图片上传必须显著说明：图片属于医疗健康敏感信息；规范化图片加密保存 90 天；识别结果随会话保留；
  图片将发送给阿里云视觉模型；不要上传他人资料；可随时删除附件、会话或账号。
- 复用 `audit_logs`，记录 `consent/upload/analyze/delete/expire`，`resource_type=medical_image`；失败只写受控错误码。
- 审计日志不写图片内容、OCR 文字、文件名、哈希、尺寸组合或服务商响应。隐私影响评估与处理记录属于合规文档，
  不等同于把图片本身长期保留。

## 8. 前后端分工

### Codex（后端所有权）

- 迁移、ORM、Pydantic 联合响应、配置和 `.env.example`。
- 图片真实性校验、规范化、独立加密存储、视觉模型客户端、上下文安全渲染、读取与删除接口。
- 图片数量/总附件数约束、限流、审计、90 天清理服务与 CLI。
- 测试：伪装类型、图片炸弹、动图、超尺寸、EXIF/GPS 移除、加密落盘、跨用户读取、删除级联、到期清理、
  服务商异常、结构化输出越界、三类安全提示、图片不进入日志、用户自带 Key 不被使用。
- 不发起真实付费调用；单元测试使用 HTTP 替身。真实调用必须另行得到用户确认。

### DeepSeek（前端所有权）

- 开工前先提交当前 4 个已验收但未提交的前端文件，避免继续叠加冲突。
- 附件按钮改为“上传文档 / 上传图片”；图片上传前选择三类之一，不得在前端拦截片子或身体照片。
- 前端压缩只用于体验；后端限额和规范化才是权威。支持 JPG/PNG/WebP，单张 5 MiB，最多 3 张、总附件最多 5 项。
- 一次性敏感信息与阿里云外发说明；本地缩略图用 Object URL，组件卸载/删除后及时 revoke，不进 localStorage。
- 上传完成不自动发送；支持仅图片发送。历史图片通过鉴权 API 获取 Blob，不拼 Base64 URL，不缓存到持久浏览器存储。
- 图片到期显示固定墓碑；报告照片、医学影像、身体照片显示不同的能力边界文案。
- 单测与 Playwright：选择类别、同意、预览、限额、取消、上传失败、仅图片发送、刷新恢复、到期墓碑、
  未登录/跨用户错误文案；不得用 `v-html` 渲染识别内容。

## 9. 实施顺序与验收

1. DeepSeek 先收口并提交当前前端工作树；双方确认工作树和 7.1 锁。
2. Codex 已应用迁移 `0018`，完成后端接口、加密存储、清理 CLI、测试和 `backend/docs/API.md`。
3. DeepSeek 已按冻结契约完成 UI 接线；后端字段已对齐 `imageCategory`、`medical-image-upload-v1`、`width/height`。
4. 前后端自动化均已完成；下一步做真实后端联调与无身份信息测试图片的人眼验收。
5. 用户用无身份信息的测试图片进行人工验收；真实阿里云调用涉及费用与医疗图片外发，必须单独确认。

验收不包括疾病识别准确率或医学影像诊断能力；不得宣传“AI 看片”“识别病因”或“辅助确诊”。
