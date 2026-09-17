# 审核来源同步与单篇 Markdown 受控导入

## 安全边界

- 工具不会联网、抓取网页或自动下载正文。
- 只同步 `medical_source_registry.json` 中 `approved_for_ingestion` 明确列出的来源。
- 从批准列表移除的注册表来源会被降级为 `candidate`，不会继续作为准入来源。
- 每次只接收一篇本地 UTF-8 Markdown 和一份审核元数据 JSON。
- 文档 URL 必须属于已批准来源的域名或其子域名。
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
