# 认证接口契约

统一前缀：`/api/v1`。请求与响应使用 JSON；登录状态由 HttpOnly Cookie 管理。

## 注册

`POST /auth/register`

请求字段：`username`、`realName`、`phone`、`idCard`、`gender`、`password`。
成功返回 201 和 `{ "user": AuthUser }`，但不会自动登录。

## 登录

`POST /auth/login`

请求字段：`username`、`password`。用户名匹配不区分大小写。成功后设置访问
Cookie 和刷新 Cookie，并返回 `{ "user": AuthUser }`。

连续 5 次密码错误会锁定 15 分钟。不存在的用户名与错误密码使用相同错误提示，
避免泄露账户是否存在。

## 刷新与退出

- `POST /auth/refresh`：轮换刷新令牌并续期登录状态。
- `POST /auth/logout`：撤销当前刷新会话并删除 Cookie。

## 当前用户

`GET /users/me`

要求有效访问 Cookie。手机号与身份证只返回脱敏值，不返回原文。

## 修改当前用户资料

`PATCH /users/me`，需要登录 Cookie。成功返回 200 和更新后的 AuthUser
（与 GET /users/me 一致，没有外层 user 包装）。

请求示例：`{"realName": "李明", "gender": "male"}`。
可只提交其中一个字段，未提交的字段保持原值。
姓名去除首尾空格后限制 2–20 个字符，仅允许中文、英文字母和 ·，加密保存。
性别允许 male、female、private。手机号和身份证仍仅返回脱敏值。

空对象、显式 null、非法姓名/性别或任何其他字段均返回 422，整次修改不生效。
用户名、手机号、身份证、密码、角色、状态、注册时间和用户 ID 不可通过此接口修改。
目标用户始终从登录 Cookie 确定，未登录返回 401，停用账户返回 403。

## 用户头像

- `PUT /users/me/avatar`：使用 `multipart/form-data` 上传字段 `avatar`。
- `GET /users/me/avatar`：读取当前登录用户头像。
- `DELETE /users/me/avatar`：删除当前登录用户头像；头像已不存在时仍返回 204。

仅支持 JPG、PNG、WebP，文件最大 3 MB。后端校验真实图片内容、移除元数据并统一
居中裁切为 512×512 WebP。头像文件使用用户 UUID 命名并保存在
`AVATAR_STORAGE_DIR`，用户只能上传和读取自己的头像。

头像上传按账户限制为 10 分钟 10 次，超限返回 429 `UPLOAD_RATE_LIMITED`，并在
`details.retryAfterSeconds` 返回建议等待秒数。当前限流状态保存在单个应用进程内；部署
多个后端进程前应迁移到 Redis 或网关限流。成功上传、校验拒绝和删除会写入最小化审计表，
但不会记录原始文件名、文件内容、磁盘路径、IP 或患者文本。为避免攻击者利用被限流请求
持续写数据库，命中 429 的每次重试不单独写审计行。

## 应用内语音转写

`POST /voice/transcribe`，需要登录，使用 `multipart/form-data` 字段 `audio` 上传一段录音。
成功返回待用户核对的文字和后端从实际音频帧计算的时长：

~~~json
{
  "text": "最近三天咳嗽",
  "durationMs": 3200
}
~~~

第一版仅接收真实内容为 WebM 容器、Opus 编码的单声道或多声道纯音频；不信任请求声明的
MIME、文件名或前端上报时长。单次上限 2 MB、60 秒，按账户 10 分钟最多 6 次。响应设置
`Cache-Control: no-store`。Safari 等无法产生 WebM/Opus 的浏览器会收到 415
`VOICE_TYPE_NOT_ALLOWED`，可继续使用设备输入法的语音输入。

后端使用服务端 `ASR_API_KEY`；未单独配置时回落到服务端 `QWEN_API_KEY`，不会使用用户在
设置页保存的模型密钥。`ASR_BASE_URL` 只允许阿里云百炼 HTTPS 兼容接口域名，模型固定为
`qwen3-asr-flash`。音频以 Base64 Data URL 在单次同步请求中发送，处理期间只存在于内存，
不落盘、不写日志、不写数据库；审计表只记录 `transcribe`、`voice_audio`、结果与受控错误码。

转写接口不会创建咨询、保存消息或自动调用医疗 AI。前端必须先把文字放入输入框供用户核对，
用户主动发送后才进入既有红旗预检、RAG、引用核验和流式回答链路。

错误码包括：413 `VOICE_TOO_LARGE`；415 `VOICE_TYPE_NOT_ALLOWED`；422
`VOICE_INVALID_AUDIO`、`VOICE_TOO_LONG`、`VOICE_NO_SPEECH`；429
`UPLOAD_RATE_LIMITED`；503 `VOICE_NOT_CONFIGURED`；502
`VOICE_PROVIDER_FAILED`、`VOICE_PROVIDER_INVALID_RESPONSE`；504
`VOICE_PROVIDER_TIMEOUT`。

## 用户自带模型 API Key

设置页只允许配置模型注册表中的四个服务商：`deepseek`、`qwen`、`kimi`、
`zhipuai`。不接受自定义 `baseUrl`，避免服务器被用作任意外部请求入口。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /users/me/model-credentials` | 返回当前用户已配置的凭据摘要 |
| `PUT /users/me/model-credentials/{provider}` | 验证并加密保存或替换凭据 |
| `DELETE /users/me/model-credentials/{provider}` | 删除凭据 |

PUT 请求为 `{"apiKey":"..."}`。保存前，后端只通过 HTTPS `Authorization`
请求头向该服务商的固定官方地址发起一次 `max_tokens=1` 的验证请求；Key 不进入 URL
或日志。验证失败返回 422 `MODEL_CREDENTIAL_INVALID`，服务商故障与超时分别返回
502/504。验证接口按用户限制为 10 分钟 5 次。

GET 响应只返回掩码，永不返回明文：

~~~json
{
  "items": [
    {
      "provider": "deepseek",
      "maskedKey": "sk-…4f2a",
      "updatedAt": "2026-09-19T12:00:00Z",
      "lastVerifiedAt": "2026-09-19T12:00:00Z"
    }
  ]
}
~~~

`GET /models` 返回服务端可用模型与用户已配置模型的并集，并新增
`keySource`（`server` 或 `user`）。同一服务商同时存在两类 Key 时使用用户 Key；
删除用户 Key 后自动回落服务端 Key。用户 Key 只改变认证凭据，不改变固定官方地址、
模型白名单、安全提示词、红旗分流、RAG 或引用核验流程。

用户主动选择自带 Key 的模型后，本轮咨询内容及允许注入的健康记录摘要会发送到对应
服务商。发送前会移除显式姓名、手机号、身份证号、邮箱和详细地址；前端必须在
设置页明确披露该数据流向。脱敏降低直接身份暴露，但不代表健康文本已经匿名化。

## 错误响应

```json
{
  "code": "VALIDATION_ERROR",
  "message": "提交的信息校验未通过",
  "details": []
}
```

常用状态码：401 未登录或凭据错误、403 账户停用、409 唯一字段冲突、
422 参数校验失败、423 账户暂时锁定。

## 医学知识检索

`POST /knowledge/search`，要求有效登录 Cookie。

请求示例：

~~~json
{
  "query": "普通感冒是否应该自行服用抗生素",
  "topK": 5
}
~~~

后端在发送阿里云向量服务前会移除手机号、身份证、邮箱、显式姓名和详细地址，并把
查询截断到最多 500 个字符。原始查询和脱敏查询均不写入知识库或检索日志表。

生产环境仅召回来源为 `approved`、文档为 `approved` 且向量配置一致的文本块。开发
环境还允许明确标记为 `prototype` 的原型资料。返回项按余弦相似度排序，并包含
`trustLevel`（`approved` 或 `prototype`）、`organization`、`title`、
`canonicalUrl`、`versionLabel`、`publishedAt`、`sectionTitle` 和原始证据文本。
如果库中不存在符合这些条件的向量，接口直接返回空列表，不把查询发送给外部模型。

`queryRedacted` 表示本次查询在发送模型前是否移除了直接身份信息。该接口返回检索
证据，不给出诊断结论；调用方不得把相似度分数解释为患病概率。

## 咨询流式回答中的 RAG

`POST /consultations/{cid}/stream` 在调用聊天模型前进入 LangGraph 生成上下文图。正常
路线执行红旗复检、查询脱敏和最多 4 个证据块召回；证据作为不可信数据隔离后加入
系统提示词，要求模型使用 `[来源1]` 格式引用且不得编造来源。

流的 `start` 事件增加 `retrieval`：

~~~json
{
  "type": "start",
  "retrieval": {
    "status": "completed",
    "gateReason": "medical_content",
    "errorCode": null,
    "sources": [
      {
        "sourceKey": "developer_prototype_knowledge",
        "organization": "项目开发者",
        "title": "合理用药与抗菌药物原型资料",
        "canonicalUrl": "https://prototype.invalid/medical-knowledge/medicine-use",
        "sectionTitle": "普通感冒与抗菌药物",
        "similarity": 0.79,
        "trustLevel": "prototype"
      }
    ]
  }
}
~~~

status 可能为 completed、empty、failed 或 skipped。事件不会返回证据正文、原始用户
问题或数据库对象。

`retrieval.gateReason` 说明门控结果：`medical_content` 表示医学相关并执行检索，
`non_medical_content` 表示普通聊天并跳过检索，`emergency` 表示红旗路线已经终止。

产生实际科普正文时，去重后的来源快照会随助手消息保存在加密字段中，并通过
`MessageOut.citations` 返回；结构化追问卡不保存引用。前端仅在 citations 非空时显示
“参考资料 N 条”折叠区域。approved 来源可以打开原文，prototype 只显示开发测试警示，
不会提供 `prototype.invalid` 无效链接。相似度仅用于内部排序，不在界面解释为患病概率。

## 健康记录

前缀 `/health-records`，全部需要登录，且只能访问当前用户自己的记录。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /health-records/settings` | 读取采集开关与首次通知状态 |
| `PATCH /health-records/settings` | 关闭或重新开启自动采集 |
| `POST /health-records/onboarding` | 提交首次采集的身体状况（也可跳过） |
| `POST /health-records/extract` | 按某条助手回答回溯对应用户消息并增量提取事实 |
| `GET /health-records` | 列出当前用户的健康记录 |
| `POST /health-records` | 手动新增一条记录 |
| `PATCH /health-records/{record_id}` | 修改一条记录，来源改为用户自述 |
| `DELETE /health-records/{record_id}` | 删除一条记录 |

约定：

- 记录正文使用 Fernet 加密保存；去重依据是 NFKC + casefold 后的 SHA-256 指纹，不会
  改写用户原文标点。
- `source` 为 `onboarding`、`conversation` 或 `user`。对话提取的记录一定来自用户明确
  陈述，推断性表述与手机号、身份证、邮箱在写入前丢弃。
- 关闭采集后，既有记录不再进入回答上下文，但记录本身不会被删除。
- 跨用户访问一律返回 404，不区分“不存在”和“无权限”。
- 健康记录不参与红旗预检。`POST /consultations/{cid}/stream` 只把记录作为受限背景注入
  系统提示词，要求不得据记录推断病因，也不得因记录中存在某项情况而降低对红旗症状的警惕。

## 病历文档附件

全部接口要求登录，且附件必须属于当前用户的指定咨询：

| 方法与路径 | 用途 |
| --- | --- |
| `POST /consultations/{consultation_id}/attachments` | 上传、在本机隔离进程解析并加密保存文字 |
| `GET /consultations/{consultation_id}/attachments` | 列出该咨询尚未绑定消息的待发送附件 |
| `DELETE /attachments/{attachment_id}` | 永久删除附件及全部文本分块 |

上传为单文件 `multipart/form-data`，字段为 `file`、`noticeAccepted=true` 和
`noticeVersion=document-upload-v1`。响应字段为 `id`、`displayName`、`kind`、
`byteSize`、`pageCount`、`charCount`、`preview`、`status=ready`、`createdAt`。
PDF/PPTX 返回页数或幻灯片数；DOCX/TXT/MD 的 `pageCount` 为 `null`。`GET` 列表是输入框草稿列表：附件一旦绑定任一消息便不再返回，避免刷新、切换会话或消息分页时把已发送附件重新加入输入框。历史消息中的附件继续由消息接口返回，删除后的墓碑行为不变。

只支持带文本层 PDF、DOCX、PPTX、UTF-8 TXT/MD：单文件最大 30 MB，
PDF/PPTX 最多 100 页，提取文字最多 500000 字符，解析最长 60 秒；每个用户每
10 分钟最多上传 20 个。扫描件、加密 PDF、图片、Excel、旧版 DOC/PPT、宏文档、
压缩包和一次多文件均拒绝。原件不落盘、不保存；提取文字自动按约 2000 字分块并加密。

**2026-09-21 按用户要求放宽（方案 B）**：体积 10→30 MB、PDF/PPTX 30→100 页、解析
30→60 秒、每 10 分钟 5→20 个、每条消息所选附件 3→5 个。**模型侧预算未变**：每轮仍只把
最多 12000 字符的相关片段放进上下文（`ATTACHMENT_CONTEXT_MAX_CHARS`），所以放宽只影响
「能不能收下」，不等于「回答用得上更多内容」。代价是资源占用上升——请求体与解析子进程
都是整份进内存，30 MB 并发上传会显著抬高常驻内存；跨进程限流仍未实现。

发送用户消息时可增加 `attachmentIds`（最多 5 个不同 UUID）。同一附件可在同一咨询的
多条消息复用；不能跨咨询或跨用户引用。`MessageOut.attachments` 与流式 `start` 事件的
`attachmentsUsed` 返回 `{id, displayName, kind, status}`。删除后历史消息保留
`{id:null, displayName:"附件已删除", kind:null, status:"deleted"}` 墓碑，不再有正文。

只有用户在本轮消息明确选择的附件片段才进入模型上下文，且会先移除直接身份信息。
文档文字被标记为不可信数据，不能覆盖系统指令；模型只可提取事实、解释术语/指标和提供
就医分流，不得据此确诊、判读影像、开处方或给出具体剂量。红旗预检第一版仍只检查本轮
用户输入文本，不读取附件。原件不外发；用户发送问题后，仅预算内相关文字片段随问答外发。

稳定错误码包括：`DOCUMENT_NOTICE_REQUIRED`、`FILE_TOO_LARGE`、
`FILE_TYPE_NOT_ALLOWED`、`FILE_PAGE_LIMIT`、`FILE_ENCRYPTED`、`FILE_NO_TEXT`、
`FILE_TEXT_TOO_LARGE`、`FILE_ZIP_UNSAFE`、`FILE_PARSE_TIMEOUT`、
`FILE_PARSE_FAILED`、`UPLOAD_RATE_LIMITED`、`ATTACHMENT_NOT_FOUND`。

## 医学图片附件

图片复用附件列表、消息 `attachmentIds` 与删除接口，但使用独立上传和鉴权读取接口：

| 方法与路径 | 用途 |
| --- | --- |
| `POST /consultations/{consultation_id}/images` | 规范化、受限识别并加密保存单张图片 |
| `GET /attachments/{attachment_id}/content` | 解密读取仍在保留期内的规范化 WebP |

上传为 `multipart/form-data`：`file`、`noticeAccepted=true`、`noticeVersion=medical-image-upload-v1`。
旧客户端可继续发送 `imageCategory`，但后端会忽略并由固定视觉模型自动分类。只接收实际内容为
JPEG/PNG/WebP 的静态图片；原始文件不保存。后端纠正方向、移除元数据、最长边缩至 2400 px 内并
重编码为 `image/webp`。单张最多 5 MiB、2000 万像素、宽高至少 32 px、长宽比不超过 20:1；
每用户每 10 分钟最多上传 10 张；每条消息最多选择 3 张图片，文档与图片合计仍最多 5 项。

响应沿用附件字段，并为图片增加 `imageCategory`、`mimeType=image/webp`、`width`、`height`、
`imageAvailable`、`imageExpiresAt`。消息附件引用额外返回 `imageCategory`、
`imageAvailable` 与 `imageExpiresAt`。读取接口只允许所属用户访问，返回
`Cache-Control: no-store, private` 与 `X-Content-Type-Options: nosniff`；到期返回
410 `IMAGE_EXPIRED`。

图片使用固定的服务端阿里云 `qwen3.8-flash`，优先
`IMAGE_ANALYSIS_API_KEY`，为空时回退服务端 `QWEN_API_KEY`，绝不读取用户自带模型 Key。
分类只允许 `report|medical_imaging|body_photo|medication_leaflet|unrelated|unclear`；前五类成功保存并在响应中返回服务端判定的
`imageCategory`。`unrelated` 是普通图片：保存的受限摘要只说明“未检测到医疗健康相关内容”，允许绑定消息，
聊天模型不得把它当作医疗证据或虚构未提取的普通场景细节。`unclear` 返回 422 `IMAGE_CATEGORY_UNCLEAR`，
不生成附件、密文文件或上下文片段。报告图片只转录文字；医学影像只提取模态、部位、可见标签与质量，
不判读病灶；身体照片只整理非诊断性肉眼事实并过滤疾病名/概率；`medication_leaflet` 忠实转录说明书原文，
包括能看清的用法用量，但明确标记“仅转录、未核对、不可作为用药依据”，不据此给出是否服用、剂量加减、
替代、停用或联合用药建议。识别结果作为加密、不可信附件片段进入现有
上下文；图片结果不参与确定性红旗预检，紧急症状仍必须由用户主动输入文字。

规范化 WebP 使用每图随机 AES-256-GCM 数据密钥加密，数据密钥再由字段主密钥包裹。图片密文
默认保留 90 天，识别文字随会话保留；未绑定消息的图片 24 小时后删除。部署层应每日运行：

```powershell
.venv\Scripts\python.exe -m app.image_cleanup_cli --dry-run
.venv\Scripts\python.exe -m app.image_cleanup_cli
```

清理使用 PostgreSQL advisory lock，可安全避免多实例同时执行。用户删除附件、会话或账号也会
清除相应图片密文。稳定错误码：`IMAGE_TOO_LARGE`、`IMAGE_TYPE_NOT_ALLOWED`、
`IMAGE_NOTICE_REQUIRED`、`IMAGE_CATEGORY_UNCLEAR`、`IMAGE_INVALID`、
`IMAGE_NO_TEXT`、`IMAGE_NOT_CONFIGURED`、`IMAGE_PROVIDER_AUTH_FAILED`、
`IMAGE_PROVIDER_RATE_LIMITED`、`IMAGE_PROVIDER_REJECTED`、`IMAGE_PROVIDER_UNAVAILABLE`、
`IMAGE_PROVIDER_INVALID_RESPONSE`、`IMAGE_PROVIDER_TIMEOUT`、`IMAGE_EXPIRED`、`UPLOAD_RATE_LIMITED`。

图片识别对超时、连接错误、HTTP 408/425/429/5xx 和无效响应最多自动重试一次；400/401/403
等确定性失败不重试。诊断日志只记录尝试次数、异常类型、HTTP 状态与过滤后的供应商请求 ID，
不记录图片、Base64、OCR、文件名、密钥、异常正文或供应商响应体。

## AI 医学科普配图

图片生成与用户上传图片是两条独立链路。全部接口要求登录；任务只能关联当前用户、当前
会话内已完成的普通医疗回答：

| 方法与路径 | 用途 |
| --- | --- |
| `POST /consultations/{consultation_id}/image-generations` | 创建一张异步科普配图 |
| `GET /image-generations/{id}` | 查询并机会式推进任务 |
| `GET /consultations/{consultation_id}/image-generations` | 恢复会话中的全部任务 |
| `GET /image-generations/{id}/content` | 鉴权读取规范化 WebP |
| `DELETE /image-generations/{id}` | 取消未完成任务或永久删除结果 |

创建请求字段为 `clientRequestId`、`sourceMessageId`、`prompt`、`style`、
`aspectRatio`、`noticeAccepted=true`、`noticeVersion=image-generation-v1`。
相同用户与 `clientRequestId` 幂等，不会重复创建收费任务。状态为
`submitted|running|completed|failed|cancelled|expired`；响应不返回提示词、供应商任务
ID 或供应商结果 URL。

服务端固定阿里云 `wan2.6-t2i`、`n=1`、1K 尺寸映射和 `watermark=false`，图片像素内不
叠加水印文字。允许三种固定风格和四种比例。后端先脱敏并包裹安全模板，拒绝仿造医疗文件、
真实医疗影像、处方剂量、个体化病灶、血腥内容等请求。每用户同时最多一个任务，10 分钟
最多 3 次、UTC 自然日最多 10 次，限额由 PostgreSQL 记录共享。

成品 URL 只在本次供应商查询响应内使用：要求阿里云 HTTPS 结果域名、公网 DNS、443、
禁止重定向，下载后验证真实静态图片、像素与大小限制，移除源元数据并重编码 WebP，只写入
AIGC 隐式标识（生成属性、服务提供者编码、内容编号），再使用独立 AAD 和每图随机
AES-256-GCM 数据密钥加密保存 90 天。任务响应包含 `contentId`；每次鉴权读取按内容编号与
不可逆接收者指纹幂等留痕至少 183 天。前端只读取本项目的鉴权 Blob 接口。稳定错误码见
`docs/IMAGE_GENERATION.md`。

## 删除账号

`DELETE /users/me`，请求为 `{"currentPassword":"当前密码"}`。密码错误返回 422
`ACCOUNT_PASSWORD_INVALID`；每个用户每 10 分钟最多尝试 5 次。成功返回 204、清除认证
Cookie，并通过数据库级联永久删除用户的会话、消息、健康记录、模型密钥、附件及加密分块；
头像文件同步删除。最小化审计事件保留，但用户外键变为 `null`，不保留附件名或正文。
