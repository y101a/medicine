# 认证数据模型

## users

保存用户主体、用户名、性别、角色、状态、注册时间、手机号验证时间和认证版本。

- 用户名同时保存展示值和 `casefold` 后的唯一匹配值。
- 姓名、手机号、身份证使用 Fernet 加密后保存。
- 手机号和身份证另存 keyed HMAC 指纹，仅用于唯一性查询，不能还原原文。
- 当前角色包含 `user` 和 `admin`，注册接口只能创建 `user`。
- `phone_verified_at` 为空表示手机号从未完成验证码验证；迁移前已有用户保持为空。
- `auth_version` 从 1 开始。密码重置时递增，访问令牌中的 `ver` 必须与数据库一致，
  因而旧访问令牌可以立即失效。

## user_credentials

与用户一对一。密码通过 Argon2id 保存为不可逆哈希，并记录失败次数、
锁定截止时间和最近密码修改时间。

## auth_sessions

与用户一对多。刷新令牌只保存 SHA-256 哈希，同时记录创建、过期、撤销时间及
有限的客户端信息。刷新时旧会话立即撤销并创建新会话。

访问令牌和刷新令牌都只通过 HttpOnly Cookie 发送，页面脚本无法读取。
刷新令牌轮换和密码重置会撤销数据库会话；访问令牌另外通过 `auth_version` 失效。

## phone_verification_challenges

手机号注册验证、已有用户补验证和密码找回的短期 challenge。保存手机号 keyed HMAC 指纹、
用途、provider、验证码 HMAC 摘要、请求 IP 的不可逆指纹、尝试次数和各生命周期时间；不保存
明文手机号、验证码、verification token 或原始 IP。

- `purpose` 只允许 `registration`、`password_reset`、`phone_binding`。
- 验证码默认 5 分钟过期、最多错误 5 次；verification token 默认 10 分钟过期且只能消费一次。
- 不存在或未验证手机号的密码找回创建 `is_decoy=true` 的诱饵 challenge，不调用 provider。
- 注册成功后 challenge 关联新用户；账号删除时通过外键级联删除。
- 手机号和 IP 时间索引用于 PostgreSQL 共享限流，不能被多 worker 绕过。
- 过期行在后续请求中惰性失效，不在开发机创建计划任务或后台自启动。

## audit_logs

保存敏感数据操作的最小化审计事件。当前记录头像、病历文档、医学图片和 AI 科普文档的同意、
上传、生成、识别、拒绝、删除与到期清理事件。

- `actor_user_id` 只能来自服务端认证上下文，用户删除后通过外键 `SET NULL`，审计事件仍保留。
- `action`、`resource_type`、`outcome` 和 `reason_code` 只保存受控代码；可选 `resource_id`
  使用随机 UUID。
- 不设置自由文本或 JSON 详情字段，避免把原始文件名、文件内容、路径、IP、坐标或患者文本
  误写入审计表。
- 普通用户没有读取审计表的接口；未来管理员读取仍需单独建立权限、保留期和脱敏规则。

咨询、消息、分流、引用和健康记录表已经在后续迁移中建立。每条私有业务数据必须以服务端
认证上下文中的 `user_id` 做隔离，不接受前端自行指定用户身份。

## attachments

咨询级文档与医学图片附件元数据。`user_id` 和 `consultation_id` 均使用
`ON DELETE CASCADE`，展示文件名以 Fernet 密文保存。`kind` 允许
pdf/docx/pptx/txt/md/image。文档原件不保存，只记录真实内容嗅探后的类型、字节数、页数、
文字数和创建时间。

图片类别支持 `report`、`medical_imaging`、`body_photo`、`medication_leaflet` 和 `unrelated`；
`unclear` 不保存。图片原始上传字节同样不保存；服务端规范化为无元数据静态 WebP 后，以每图独立 AES-256-GCM
数据密钥加密存入随机对象路径，数据密钥再由字段主密钥包裹。图片行额外记录类别、MIME、宽高、
随机存储键、包裹密钥、90 天到期时间、删除时间、分析模型与版本。图片到期后清空存储键和包裹
密钥并设置删除时间，但保留附件行与识别文字，以支持历史消息显示到期墓碑。

## attachment_chunks

附件自动拆分后的有序文本块。正文使用 Fernet 密文保存，`locator` 只保存“第 N 页/段/
张幻灯片”等非正文定位标签。每个附件的 `position` 唯一；删除附件时级联删除全部分块。
分块用于在固定预算内选择与本轮问题相关的文字，不把整份长文档塞入聊天消息字段。

## message_attachments

消息与附件的多对多使用快照，每条消息最多五个有序关联，其中图片最多三张。同一咨询中的
附件可以被多条用户消息复用，助手普通回答会复制本轮用户消息的关联，便于历史界面标注使用了
哪些文档或图片。删除附件时 `attachment_id` 设为 `NULL`，历史消息仍显示“附件已删除”
墓碑；删除消息或咨询时关联级联删除。

账号删除通过删除 `users` 主体触发数据库级联，清理附件、分块、关联及其他私有业务数据。

## image_deletion_jobs

加密图片密文的持久化物理删除任务。只保存随机 `storage_key`、受控删除原因、状态、尝试次数、
下次尝试时间、受控错误类型和完成时间；不保存用户外键、附件外键、图片内容、文件名或解密密钥。

删除附件、咨询、账号或清理到期图片时，任务与数据库逻辑删除在同一事务中创建。事务提交后由
幂等处理器删除磁盘对象；文件已经不存在同样记为完成，临时文件占用或磁盘错误使用指数退避重试。
任务使用 `FOR UPDATE SKIP LOCKED` 领取，可由多个清理进程安全竞争。非法越界路径进入终止失败状态，
不会访问图片存储根目录之外的位置。

每日清理还会对账超过安全宽限期、但不再被 `attachments.image_storage_key` 或
`generated_images.storage_key` 引用的 `.bin` 和 `.tmp` 文件，为其补建任务。这覆盖文件原子
落盘后、数据库提交前崩溃形成的无主密文。
`audit_logs.actor_user_id` 使用 `SET NULL`，只保留受控代码组成的最小化审计记录。

## generated_images

AI 医学科普配图的异步任务与加密成品。`user_id`、`consultation_id`、
`source_message_id` 均为数据库外键；账号、会话或来源消息删除时级联删除任务，应用服务在
级联前先把仍存在的随机存储键写入 `image_deletion_jobs`。

- `(user_id, client_request_id)` 唯一，保障创建幂等；部分唯一索引保证每个用户同时最多一个
  `submitted/running` 任务。
- `prompt_ciphertext` 只保存脱敏并加安全模板后的实际外发提示词密文；供应商任务 ID 同样加密，
  成品保存后立即清空。供应商 URL 从不入库。
- 状态约束保证只有 `completed` 行可以同时持有 `storage_key`、包裹密钥、WebP 元数据与到期时间；
  `failed/cancelled/expired` 等状态不得持有图片密文引用。
- 成品默认保留 90 天。到期清空随机存储键和包裹密钥，设置 `expired` 与删除时间，并通过持久化
  删除任务移除磁盘密文。
- 表中不保存供应商响应正文、公开 URL、Base64、用户自带模型 Key 或诊断结论；生成图不进入
  附件上下文、RAG、红旗预检或健康记录抽取。

## generated_image_delivery_logs

无显式水印成品的最小化提供对象留痕。保存不可逆 `recipient_fingerprint`、`content_id`、
`source_consultation_id`、`delivered_at` 和至少 183 天后的 `retain_until`；不保存用户名、
姓名或其他明文身份信息。该表不设用户、会话或成品外键，避免用户删除业务数据时提前删除法定
留痕；`(content_id, recipient_fingerprint)` 唯一，使同一用户重复读取同一成品不会重复写入。

## generated_documents

AI 医学科普 Word/PPT 的异步任务。`user_id`、`consultation_id`、`source_message_id` 均为
数据库外键，账号、会话或来源消息删除时级联删除任务；应用服务在级联前将仍存在的随机存储键
写入 `generated_document_deletion_jobs`。

- `(user_id, client_request_id)` 唯一，保障创建幂等；部分唯一索引保证每个用户同时最多一个
  `queued/generating/rendering` 任务。
- `(user_id, source_message_id)` 唯一，换用新的幂等键重放同一消息也不会再次触发收费任务。
- `requested_formats` 只允许 `docx`、`pptx` 的无重复非空数组；来源主题从已保存消息重新判定，
  不信任客户端另传主题。
- 状态约束为 `queued/generating/rendering/completed/failed/cancelled/expired`，失败仅保存受控错误码。
- 内容计划由服务端固定模型依据知识库检索证据生成，不保存模型原始响应、用户密钥、附件正文、
  健康记录或医疗诊断结论。
- 成品默认保留 30 天；到期或用户删除时清除文件引用并进入持久化物理删除队列。

## generated_document_files

一个文档任务下的加密输出文件，每种格式至多一份。保存格式、受控下载名、MIME、字节数、
SHA-256、页/幻灯片数、随机存储键、包裹数据密钥、创建与到期时间。

- 文件使用独立 AAD 和每文件随机 AES-256-GCM 数据密钥；数据密钥再由字段主密钥包裹。
- DOCX 的 `page_count` 为空，因为分页取决于 Word 渲染环境；PPTX 保存准确幻灯片数。
- OOXML 写入前会限制 ZIP 条目、解压体积与压缩比，并拒绝宏、ActiveX、OLE、嵌入对象和外部关系。
- 下载必须同时满足当前用户所有权、任务完成且未过期，并在解密后校验 SHA-256。

## generated_document_deletion_jobs

生成文档密文的持久化物理删除任务。只保存随机 `storage_key`、受控原因、状态、尝试次数、
下次尝试时间、受控错误类型和完成时间，不保存用户外键、正文、文件名或解密密钥。任务与业务
删除在同一事务创建，提交后由幂等处理器删除磁盘对象；临时错误按指数退避，非法越界路径进入
终止失败状态。多个显式前台 worker 可使用 `FOR UPDATE SKIP LOCKED` 安全竞争。worker 还会
对账超过 24 小时安全宽限、但不再被文件表引用的 `.bin`/`.tmp`，并为其补建删除任务。
