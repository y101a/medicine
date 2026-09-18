# 开发原型医学语料（**非正式资料**）

本目录是**个人开发阶段的自编原型语料**，只用于验证 Markdown 导入、向量生成、pgvector 召回与
引用链路是否可工作。

## 必须知道的三件事

1. **未完成版权审核，也未完成医学专业审核。** 不是官方文档，不能用于诊断、治疗，也不能作任何
   临床准确性声明。
2. 正文由项目开发者依据公开健康科普主题自行整理；`manifest.json` 里的 `reference_urls` 是
   **查阅线索**，不代表来源已完成受控正式导入，正文也不是所列网页的复制件。
3. **提交进版本库不会改变以上任何一条。** 数据库只以 `prototype` 状态接纳这些记录，且仅
   `APP_ENVIRONMENT=development` 时参与向量化与检索；生产环境只接受 `approved` 来源与文档。
   文档元数据始终为 `medical_reviewed: false`、`production_eligible: false`。

## 为什么这些文件会在版本库里

它们原先只存在于本机目录，存在「看起来像有备份、其实没有」的风险。2026-09-18 起纳入版本库，
并由本文件把上述边界随文携带——**版本控制不等于审核通过**。

## 导入方式

`seed-prototype` 只读取 `manifest.json` 列出的文件（见 `backend/app/rag/prototype_seed.py`
的 `load_manifest`），因此**本文件不会被当作医学文档导入**。

命令、基线与后续升级路径见 `backend/docs/PROTOTYPE_KNOWLEDGE.md`。