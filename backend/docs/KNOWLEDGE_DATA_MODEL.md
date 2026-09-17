# 医学知识库数据模型

## 当前实现

Alembic 迁移 20260911_0006 建立四张共享知识库表：

~~~text
knowledge_sources
    └── knowledge_documents
            ├── knowledge_chunks
            └── ingestion_jobs
~~~

普通用户数据仍按账号隔离；知识库属于经过审核的共享公共资料。当前没有知识库
写入 API，后续只允许管理员或离线导入任务写入，普通用户只能通过受控检索使用。

## knowledge_sources

保存来源机构、渠道、权威级别、地域、语言、入口 URL、版权声明 URL、优先级和
准入状态。automated_collection 默认为 false。

正式资料只有 ingestion_status 为 approved 的来源，才允许受控导入程序继续处理。
个人开发语料使用独立的 prototype 状态，并且只在 development 环境可检索。

## knowledge_documents

保存每一份具体文档及其可追溯元数据：

- 原始 URL、标题、责任部门和作者。
- 发布时间、获取时间、版本和替代关系。
- 正文哈希、标准化正文和自定义元数据。
- 版权类型、版权审核人和时间、医学审核人和时间。
- pending、prototype、approved、rejected、superseded、expired 审核状态。

数据库约束规定：文档缺少版权审核、医学审核、许可证类型或正文时，不能标记为
approved。同一来源、原始 URL 和正文哈希唯一；同一 URL 的新版正文保留为独立快照，
并通过替代关系连接旧版本。

## knowledge_chunks

保存实际参与检索和引用的文本块：

- 文档外键和文档内顺序。
- 章节标题、章节路径、正文和正文哈希。
- token 数、embedding 模型、版本和维度。
- pgvector 的 vector 列。

删除文档会级联删除文本块。向量及其模型、版本和维度必须同时为空或同时存在，
数据库还会用 vector_dims 检查实际维度。

当前 vector 列已经固定为 1024 维，对应阿里云
`qwen3.7-text-embedding-flash`。HNSW 或 IVFFlat 索引将在检索基线评测后建立，避免在
没有真实语料和查询集时过早确定召回参数。

## ingestion_jobs

记录文档导入过程，包含幂等键、来源、文档、输入位置、解析器版本、统计信息、
错误信息和开始结束时间。状态限定为 queued、running、succeeded、failed 或
cancelled。

## 删除策略

- 已被文档引用的来源不能直接删除。
- 删除文档会删除对应文本块。
- 删除来源或文档不会删除导入审计记录，只会将其中的外键设为空。
- 数据库降级不会删除 vector 扩展，因为它可能被其他功能共享。

## 后续开发

1. 完成首篇真实文档的版权与医学审核，并加入来源批准列表。
2. 使用受控导入命令写入该文档，核对章节和版本元数据。
3. 使用已实现的单文档任务生成阿里云 1024 维向量。
4. 建立医学检索评测集、向量索引和引用检索接口。
5. 生产环境检索只返回 approved 且未被替代、未过期的文档。

具体操作见 `CONTROLLED_INGESTION.md`。
