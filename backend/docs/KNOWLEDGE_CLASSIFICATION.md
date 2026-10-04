# 公共医学知识四层分类

分类是文档的**用途标签**，不是审核结果，也不是四层依次审核的流程。每篇已审核公共文档恰有一个主层，可有不重复的副层；`topic_key` 为稳定英文主题键。新导入必须提供分类，历史文档不自动猜测分类。

| 层 | `primary_layer` | 范围 |
| --- | --- | --- |
| 疾病学 | `disease` | 疾病表现、危险信号、就医与随访科普 |
| 生理学 | `physiology` | 正常结构、功能与生命过程 |
| 药学 | `pharmacology` | 药物类别、用药安全与一般原理；不生成个人处方 |
| 养生健身 | `wellness_fitness` | 饮食、运动、睡眠等一般健康促进知识 |

导入审核元数据示例：

```json
"classification": {
  "primary_layer": "disease",
  "secondary_layers": ["physiology"],
  "topic_key": "headache"
}
```

分类保存在公共 `knowledge_documents.document_metadata.classification` 中，不存用户/患者资料，不改变 `review_status` 准入门槛；待审核的养生健身候选不会因此自动入库。历史文档分类缺失时保持缺失，待人工核对后补充。
