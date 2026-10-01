# 用户专属知识库后端

状态：P1–P3 已实现；P4 本地向量检索未启用。

## 安全边界

- 私人知识库与会话附件、公共医学 `knowledge_*` 表完全分离。
- 所有查询从认证上下文取得 `user_id`，并同时过滤用户、知识库和文档归属。
- 文件原件只在请求内存和隔离解析子进程中存在，解析结束即释放；数据库只保存加密名称、加密正文块、定位和必要元数据。
- 私人正文不会发送给云端 embedding。当前索引只保存用户域 HMAC 词项，候选块在应用进程内解密重排。
- 未显式选择知识库的消息不会执行私人检索。每条消息最多选择 3 个库，发送成功后前端清空选择。
- 红旗预检只读取本轮用户文字，不读取私人知识库。
- 模型收到的片段标记为“用户提供的未核验资料”和“不可信数据”，不得执行其中指令，也不得据此确诊、推断病因或调整用药。
- 私人引用使用 `[P1]`，与公共医学来源 `[来源1]` 分开核验、保存和展示，不生成外部链接。

## 数据和索引

- `private_knowledge_collections`：加密名称与说明；同用户名称通过不可逆指纹唯一。
- `private_knowledge_documents`：归属、加密文件名、解析/索引版本、受控状态和用户域内容 HMAC；不保存原件。
- `private_knowledge_chunks`：每块加密正文、定位与用户域内容 HMAC。
- `private_knowledge_search_terms`：用户域 HMAC 词项，不保存明文词。
- `message_private_knowledge_selections`：用户消息本轮显式选择；删除库后保留空外键墓碑。
- `message_private_knowledge_citations`：助手实际使用的 `[P#]`；删除文档后只显示“私人资料已删除”，不缓存正文和敏感名称。

当前索引版本为 `private-keyword-v1`。中文候选使用二元/三元片段和受控英文数字词项；查询只解密最多 40 个候选，最终最多返回 5 块且最多涉及 2 份文档。低于独立门槛的结果返回空。

## 生命周期

上传是同步的：先在隔离子进程中校验魔数、压缩结构、页数和文字量，再在同一数据库事务写入文档、加密块和 HMAC 索引，成功响应为 `ready`。原件不保存，因此“重试”只重建已有加密块的索引，无法重新解析没有正文块的失败文档。

删除文档或整库依赖数据库级联立即移除正文块和 HMAC 词项；账号删除通过 `users` 级联清除全部私人知识。该功能没有磁盘成品，也没有计划任务、服务或开机自启。

## API

全部路径位于 `/api/v1/private-knowledge`：

- `POST/GET /collections`
- `PATCH/DELETE /collections/{collectionId}`
- `POST/GET /collections/{collectionId}/documents`
- `GET/DELETE /documents/{documentId}`
- `POST /documents/{documentId}/retry`
- `POST /search`

上传 multipart 字段为 `file`、`noticeAccepted=true`、`noticeVersion=private-knowledge-upload-v1`。支持 PDF、DOCX、PPTX、TXT、MD，沿用 30 MiB、100 页、500000 字和 60 秒解析上限。

咨询消息 `POST /consultations/{id}/messages` 可选传：

```json
{"privateKnowledgeCollectionIds":["uuid"]}
```

响应消息分别通过 `privateKnowledgeCollections` 和 `privateKnowledgeCitations` 返回选择快照与实际引用。正文不复制进消息表。

## 验证

专项测试覆盖：身份验证、密文存储、HMAC 无明文、同名库跨用户允许、猜 UUID 隔离、重复文档幂等、默认不检索、只检索显式选择、提示注入上下文、直接身份信息脱敏、流式生成接入、`[P#]` 核验、删除墓碑和索引重建。

P4 本地向量只有在独立评测达到规划门槛后才能启用；当前实现不会下载模型或写入向量。
