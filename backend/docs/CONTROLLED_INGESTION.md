# 审核来源同步与单篇 Markdown 受控导入

## 安全边界

- 工具不会联网、抓取网页或自动下载正文。
- 只同步 `medical_source_registry.json` 中 `approved_for_ingestion` 明确列出的来源。
- 从批准列表移除的注册表来源会被降级为 `candidate`，不会继续作为准入来源。
- 每次只接收一篇本地 UTF-8 Markdown 和一份审核元数据 JSON。
- 文档 URL 必须属于已批准来源的域名或其子域名。
- 来源若配置了摘要策略，只接受 `content_mode: original_summary`；逐字引用必须在
  `verbatim_quotes` 中逐条声明，并同时出现在正文。
- 当前国家卫健委摘要最多 1600-1800 字、最多 2 条逐字引用且合计不超过 100 字；
  国家药监局监管事实摘要最多 1200 字、最多 1 条逐字引用且不超过 50 字。
- `canonical_url` 必须是实际支持摘要内容的原始页面；回答引用通过该字段返回原始 URL。
- 许可证、版权审核人和时间、医学审核人和时间均为必填项。
- 导入失败不会留下不完整文档；已建立的任务会保留失败审计信息。
- 相同正文重复导入是幂等操作；同一 URL 的新版正文会保留旧快照并建立替代关系。

## 1. 批准并同步来源

先由负责人完成来源层面的医学与版权审核，再把来源 ID 加入：

~~~json
"approved_for_ingestion": ["nhc_health_literacy_2024"]
~~~

然后在 `backend` 目录运行：

~~~powershell
.\.venv\Scripts\python.exe -m app.rag.cli sync-sources
~~~

批准列表为空时命令会成功返回 `approved_requested: 0`，不会创建来源。

## 2. 准备单篇文档

Markdown 文件必须为 UTF-8，扩展名为 `.md` 或 `.markdown`，且不超过 2 MiB。解析器按
Markdown 标题保留章节路径，并把正文切为约 1000 字符的文本块。目前只写入文本，
尚不生成向量。

复制 `docs/examples/knowledge_document.metadata.example.json`，填写这篇文档真实的
原始 URL、版本、许可证或授权依据，以及实际完成审核的人员和时间。示例中的占位文本
不能作为正式审核记录。

对于仅允许自编摘要的来源，还必须填写：

~~~json
{
  "content_mode": "original_summary",
  "verbatim_quotes": ["如有逐字引用，在此逐条声明；没有则使用空数组"]
}
~~~

未在 `verbatim_quotes` 声明的文字应为项目自行撰写的概括。候选草稿不能把
`pending_qualified_medical_review` 改写成虚构的审核人；没有真实医学审核就不得导入。

## 3. 执行导入

~~~powershell
.\.venv\Scripts\python.exe -m app.rag.cli import-markdown --file "D:\reviewed\health-literacy.md" --metadata "D:\reviewed\health-literacy.metadata.json"
~~~

成功时返回 JSON，例如：

~~~json
{
  "ok": true,
  "document_id": "...",
  "chunk_count": 8,
  "duplicate": false,
  "supersedes_document_id": null
}
~~~

再次导入相同 URL 和相同正文时，返回同一个文档 ID 且 `duplicate` 为 `true`。同一 URL
正文发生变化时会创建新版本，把旧版本标为 `superseded`，不会覆盖历史内容。

## 后续步骤

已选定阿里云 `qwen3.7-text-embedding-flash` 和 1024 维向量。导入成功并取得
`document_id` 后，可执行：

~~~powershell
.\.venv\Scripts\python.exe -m app.rag.cli embed-document --document-id "文档UUID"
~~~

具体配置和隐私边界见 `EMBEDDINGS.md`。生成向量仍不代表内容达到临床验证标准；在
向量索引、检索评测和引用接口完成前，文档不会自动参与用户回答。
