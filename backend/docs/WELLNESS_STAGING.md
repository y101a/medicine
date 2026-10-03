# 养生健身知识储备（9 篇已按开发原型通道写入；**未进入正式知识库**）

> 用户 2026-10-03 要求：「帮我搜索储备一些关于养生健身相关的知识暂时放入文件中，等我确定后再写入给 AI」。
> 本文件是**给你看的复核清单**，配套机器可读的候选草稿在同目录 `wellness_candidates.json`。

## 0. 当前状态（先说清楚没做什么）

- **已写入 dev 数据库**：经用户要求，9 篇按**开发原型通道**导入（`review_status=prototype`、
  `medical_reviewed=false`、`production_eligible=false`，仅 `APP_ENVIRONMENT=development` 时参与检索）；
  库内快照与召回实测见 `backend/docs/PROTOTYPE_KNOWLEDGE.md` 的「2026-10-03 wellness 批次」。**未向量化**
  （不调用收费向量服务、不把正文送出本机），**未进入正式知识库**。
- **没有**加入 `approved_for_ingestion` 白名单：已在 `medical_source_registry.json` **登记**中国营养学会 /
  国家体育总局 / 国家中医药管理局 3 条来源（状态均为「仅登记、未批准」）；福建卫健委转载稿按用户决定
  **暂缓**，未登记。
- **没有**任何一条以正式（`approved`）文档入库：没有真实医学审核签名，按 `CONTROLLED_INGESTION.md`
  一条都不能按正式文档导入——**我不会代签**。
- 候选里 10 条仍是 `pending_qualified_medical_review`（福建那条为 `deferred_source_not_registered`）。
  实际入库 9 篇：① 《中国公民中医养生保健素养》第三十三至四十二条「常用养生保健简易方法」**未导入**
  （原文自带保健功效说法且涉及自行操作，理由见 `PROTOTYPE_KNOWLEDGE.md` 同节）；② 八段锦/功法安全那条
  因来源暂缓未导入。

## 1. 来源清单（都是我实际抓取到的页面）

| # | 机构 | 标题 | 发布 | 抓取结果 |
| --- | --- | --- | --- | --- |
| 1 | 世界卫生组织 | Physical activity（身体活动实况报道） | 2024-06-26 | ✅ HTTP 200（**英文页**；中文页 `who.int/zh/...` 抓取失败） |
| 2 | 中国营养学会 | 《中国居民膳食指南（2022）》平衡膳食八准则 | 2022-04-26 | ✅ HTTP 200，八条准则全文可读 |
| 3 | 国家体育总局 | 《全民健身指南》发布 | 2017-08-11 | ✅ HTTP 200（发布通稿，含内容框架说明） |
| 4 | 国家体育总局（来源中国体育报） | 季节交替身心疲 运动防护不能少 | 2025-02-26 | ✅ HTTP 200（热身、洋葱式穿衣法） |
| 5 | 国家中医药管理局、国家卫生计生委 | 《中国公民中医养生保健素养》公告（42 条） | 2014-06-06 | ✅ HTTP 200，42 条全文可读 |
| 6 | 福建省卫生健康委员会（转载新华社） | 运动是良医！中医健身可以这么练 | 2026-01-22 | ✅ HTTP 200（国家中医药管理局组织专家解读） |
| 7 | 中国疾病预防控制中心 | 全民健康生活方式行动（三减三健） | 2022-10-25 | ✅ HTTP 200 |

**没抓到、因此没有写进候选的**（不是它们不重要，是本机网络拿不到正文）：国家卫健委「健康中国行动（2019—2030年）」正文页（返回 HTTP 412）、《中国人群身体活动指南（2021）》（只有 PDF，抓取器不支持 PDF）、WHO 中文实况报道页（fetch 失败）。这三项我按「只写现象、不写因果」的规矩**没有凭记忆编写内容**。

## 2. 候选条目与审核要点

`source_key` 是我的**提议映射**，后面一列是这些来源在注册表里的真实状态。

| id | 主题 | 提议 source_key | 该来源当前状态 | 审核时必须处理 |
| --- | --- | --- | --- | --- |
| who-physical-activity-benefits-2024 | 身体活动的益处与不足风险 | `who_zh_fact_sheets` | 已登记，`license_check_per_document`，**不在**批准白名单 | 注册表把该来源标为 `zh-CN`，而我抓的是英文页：要么补抓中文页，要么改登记语言 |
| who-sedentary-behaviour-2024 | 久坐行为的健康风险 | `who_zh_fact_sheets` | 同上 | 同上 |
| cnsoc-dietary-guidelines-2022-principles | 平衡膳食八准则总览 | `cnsoc_dietary_guidelines_2022`（**已登记，未批准**） | 已登记（未批准）：版权与医学审核待做 | 明确写这是**人群层面**建议，不得变成个人饮食处方 |
| cnsoc-dietary-guidelines-2022-eat-move-balance | 准则二：运动量（150 分钟/周、6000 步、抗阻 2~3 天） | 同上 | 同上 | 慢病、孕产、术后、已有运动损伤者必须提示按医生意见调整 |
| cnsoc-dietary-guidelines-2022-salt-oil-sugar | 准则五：盐 5 g、油 25~30 g、糖 25~50 g、酒精 15 g | 同上 | 同上 | 定量值是人群建议，不得当作个人的限盐限酒治疗目标 |
| sport-gov-national-fitness-guide-2017 | 《全民健身指南》框架（先评估、再处方） | `sport_gov_fitness_guidance`（**已登记，未批准**） | 已登记（未批准）：版权与医学审核待做 | 只讲框架，不复制处方模板，不替代医生评估 |
| sport-gov-warmup-and-protection-2025 | 热身约 10 分钟、洋葱式穿衣法 | 同上 | 同上 | 原文有「运动中产热量可达静止时 10 倍」这类**未给文献的数字**，建议删掉无出处表述 |
| natcm-tcm-health-literacy-2014-principles | 中医养生四大基石、治未病三阶段、九种体质 | `natcm_tcm_wellness`（**已登记，未批准**） | 已登记（未批准）：版权与医学审核待做 | 「功效」类表述要改写为中医理论表述，不得写成疗效承诺 |
| natcm-tcm-health-literacy-2014-simple-methods | 第三十三至四十二条（叩齿、咽津、摩腹、足心按摩等） | 同上 | 同上 | **我建议整条不采用**：原文带疗效说法（清肝明目、强腰固肾）且涉及自行操作；艾灸、拔罐、刮痧有烫伤/皮肤损伤风险，不做操作指导 |
| fujian-wjw-tcm-exercise-safety-2026 | 八段锦等功法怎么练、练后疲劳怎么办、老年人先排查疾病 | `fujian_wjw_repost`（**未登记，已暂缓**） | **用户 2026-10-03 决定暂缓**：该来源是转载新华社稿、权利在原媒体，未加入受信来源白名单；候选状态已改为 `deferred_source_not_registered`，如要采用建议改用国家中医药管理局原始文件重新取证 | 按体质推荐具体式子属个体化建议，建议删除或改写；「立即停止并咨询医务人员」这类分流提示应保留 |
| chinacdc-healthy-lifestyle-action | 三减三健与全民健康生活方式行动 | `china_cdc_health_education` | 已登记，但 `permission_required`（官网声明限制复制发表） | 未获授权前**只能人工阅读与核验事实**，不能入库 |

## 3. 你确认后我会做什么（每一步都有前置条件）

1. **来源层面（2026-10-03 已部分完成）**：用户已同意扩充受信来源白名单，我已在 `medical_source_registry.json`
   **登记** 3 条来源（中国营养学会 / 国家体育总局 / 国家中医药管理局），并在
   `tests/test_medical_source_registry.py` 的 `TRUSTED_DOMAINS` 同步这 3 个域名；福建卫健委转载稿按用户决定
   **暂缓**（未登记）。**仍未把任何来源加入 `approved_for_ingestion`**——加入白名单前需要真实医学审核与授权判断。
2. **逐篇文档**：按 `CONTROLLED_INGESTION.md` 产出 UTF-8 Markdown（自编摘要，卫健委类来源上限 1600 字、逐字引用 ≤2 条且合计 ≤100 字）+ 元数据 JSON（**版权审核人与时间、医学审核人与时间都是必填**，不能用占位文本）。
3. **导入**：`app.rag.cli sync-sources` → `app.rag.cli import-markdown`（只写文本，**不生成向量**）。
4. **向量化与接线**：另批决定（本地向量 P4 此前明确不启用；云端向量化「默认不把正文送云端」这条需要你单独确认）。

## 4. 需要你决定的 3 件事

1. **要不要登记这 4 个新来源**并允许走「自编摘要入库」？还是先留作参考、暂时不进知识库？
2. **中医养生类内容是否纳入**？（这是产品边界决定：可作为文化/生活方式科普讲，还是完全不涉及；「功效」表述的口径需要医学审核人认可。）
3. **医学审核人是谁**？现有规则要求真实签名才能导入；如果没有，我可以一直停在候选阶段——**这是最安全的停法**，本文件就是这个停法的产物。

## 5. 自查（供 Codex 与后续审核核对）

- 本次只新增两个文件：本文件与 `wellness_candidates.json`；未改任何现有文件、未加迁移、未写数据库（§7.1 已登记并在收工后释放）。
- 11 条候选的正文都是我抓取页面后重新组织的概括；跨来源的时间点与数值（150 分钟/周、31%、5 g 盐、6000 步等）逐条对着抓取到的页面核过。
- 已知不确定项：我**没有**核对各来源的版权条款（注册表的 `legal_notice_url` 需逐篇判断）；WHO 条目当前引用的是英文页；营养学会/体育总局/中医药局页面的转载与授权条件需在登记来源时一并判断。

## 6. 重复信息核查（2026-10-03 实测，不是估计）

**现有库现状（实查开发库）**：知识文档 25 篇（24 篇现行 + 1 篇 `superseded`）、文本块 70 个、来源 5 个
（国家卫健委规范性文件与诊疗指南 / 国家药监局 / 中国公民健康素养（2024年版）/ 个人开发原型医学语料 / Tavily 开发原型搜索）。

**结论一：这 11 条不与现有正文撞车。** 在全部文本块里按关键词统计命中数：

| 关键词 | 命中块数 | 关键词 | 命中块数 |
| --- | --- | --- | --- |
| 健身 | **0** | 膳食 | 1 |
| 久坐 | **0** | 养生 | 1 |
| 八段锦 | **0** | 睡眠 | 1 |
| 太极 | **0** | 骨骼 | 1 |
| 热身 | **0** | 运动 / 中医 / 体重 / 盐 / 糖 | 3 / 3 / 4 / 5 / 7 |

**结论二：有 4 篇主题相邻**（不是重复，但要防止回答里两处口径打架）：
《关于印发健康中国行动——糖尿病防治行动实施方案（2024—2030年）的通知》（含膳食、运动、养生、体重、盐、糖、骨骼、中医）、
《常见慢性健康问题原型资料》《高血压认识与随访原型资料》《糖尿病常见表现与随访原型资料》（含饮食、盐、糖、体重）。
处理方式：导入前做**主题归口**——同一主题只留一个主文档，其余用引用或「另见」处理。

**结论三：还有一个计划中的重叠**：`official_summary_candidates.json` 里已登记的《中国公民健康素养（2024年版）》
**尚未导入**（该来源目前正式文档为 0），但它的「健康生活方式与行为」覆盖面与我这批膳食/运动条目重叠；
若两者都要导入，需先决定归口，避免同一套建议在库里存两份。

**导入器自带的去重机制（读 `app/rag/markdown_importer.py` 确认）**：

- **正文哈希去重**：导入前算 `sha256(正文)`，库里已有同哈希文档时直接返回 `duplicate=True`，不新增文档。
- **同来源同 URL 新版本**：把旧文档标记为 `superseded` 并保留快照（库里现存的 1 篇 `superseded` 就是这种）。
- **跨来源的近似重复不会自动发现**：哈希只认完全相同的正文；同一主题、不同来源的两份摘要必须**人工归口**——
  这正是结论二要人工处理的原因。
- **四道准入校验**（不满足就直接拒绝）：来源必须存在且 `ingestion_status == 'approved'` → 文档 URL 域名必须属于该来源
  → 正文必须符合该来源的摘要策略（`content_mode`、字数上限、逐字引用条数）→ 才进入哈希去重。

**这份储备导入前的检查清单（我会逐条走）**：① 同哈希检查（工具自动）② 同来源同 URL 版本检查（工具自动）
③ 主题归口人工比对（结论二那 4 篇）④ 与 `official_summary_candidates.json` 交叉比对（结论三）
⑤ 向量化前再查一次该 `content_hash` 是否已向量化。

## 7. 关于「先按原型导入」这条路（走之前务必看清）

- **代码事实**：检索同时接受 `review_status` 为 `approved` **和** `prototype` 的文档（`app/rag/retrieval.py`）。
  也就是说**原型文档会真的参与回答**——它不是隔离沙箱，只是一条「标为原型」的来源。
- 所以「先按原型导入」的实际含义是：**它立刻就会影响 AI 的回答**，只是引用里标为原型来源。
- 若走这条路，必须先做两件事：① 把带中医功效表述、自行操作（艾灸/拔罐/刮痧）和个体化建议的条目**剔除或改写**；
  ② 这批内容是对外部页面的摘要，若挂到「个人开发原型医学语料」这个来源下会**错标来源**，必须在文档元数据里
  显式写明真实出处与「未医学审核」状态。

## 8. 来源登记提案（2026-10-03：**已按用户决定落地 3 条**）

**状态更新（2026-10-03）**：用户已决定「只加 3 家国家级机构（中国营养学会 / 国家体育总局 /
国家中医药管理局），福建转载那条暂缓」。我已落盘：注册表 3 条来源 + `tests/test_medical_source_registry.py`
的 `TRUSTED_DOMAINS` + `MEDICAL_KNOWLEDGE_SOURCES.md`；**未把任何来源加入 `approved_for_ingestion`**
（仍需真实医学审核与授权判断）。落盘时 3 条的 `notes` 在下面提案的基础上补充了 https 实测结果与
「按用户决定登记」的措辞，**以注册表实际内容为准**。下面的 8.1–8.6 保留提案原文与当时的待决问题，作为决策记录。

### 8.1 为什么不能直接加这 4 个来源（当时发现的硬约束）

`backend/tests/test_medical_source_registry.py::test_medical_source_registry_uses_unique_official_https_channels`
对注册表里**每一个**来源都断言：`entry_url` 必须是 `https`，且**域名必须属于写死的 `TRUSTED_DOMAINS`**，
当前只有 6 个：`app.gjzwfw.gov.cn`、`www.chinacdc.cn`、`www.ndcpa.gov.cn`、`www.nhc.gov.cn`、
`www.nmpa.gov.cn`、`www.who.int`。我要用的 4 个域名一个都不在里面。

直接加进去会：① 让这条测试立刻变红；② 等于顺手**放宽一个来源白名单**——「哪些机构算可信来源」是政策决定，
不是实现细节，所以我不擅自改，改为提交提案 + 在 `COORDINATION.md` §6 请 Codex（该注册表与测试的归属方）确认。

另一条测试 `test_approved_sources_remain_manual_summary_only` 断言白名单恰好是那 3 个来源、且所有来源
`automated_collection` 为 `false`；**本提案不动白名单**，所以它不受影响。

### 8.2 https 可用性（我实测到的，只写现象）

| 域名 | https 实测 | 能否直接作 `entry_url` |
| --- | --- | --- |
| `www.sport.gov.cn` | ✅ 抓取成功（HTTP 200） | 可以 |
| `wjw.fujian.gov.cn` | ✅ 抓取成功（HTTP 200） | 可以 |
| `dg.cnsoc.org` | ❌ 本机抓取失败 | **未确认**（不能据此断定站点不支持 https，需复审时再验） |
| `www.natcm.gov.cn` | ❌ 本机抓取失败 | **未确认** |

### 8.3 提案内容（等白名单决定后再落盘）

追加到 `medical_source_registry.json` 的 `sources[]`（**`policy.approved_for_ingestion` 保持 3 条不变**）：

~~~json
[
  {
    "id": "cnsoc_dietary_guidelines_2022",
    "priority": 2,
    "organization": "中国营养学会",
    "authority_level": "national_academic_society",
    "jurisdiction": "CN",
    "language": "zh-CN",
    "channel_name": "《中国居民膳食指南（2022）》",
    "entry_url": "https://dg.cnsoc.org/",
    "content_scope": ["平衡膳食原则", "食物与营养建议", "人群膳食指导"],
    "rag_role": "nutrition_guideline_candidate",
    "ingestion_status": "permission_required",
    "automated_collection": false,
    "review_interval_days": 90,
    "notes": "2026-10-03 由 DSH 登记为候选来源（用户为养生健身储备要求先登记）：只做登记，未做版权与医学审核，也未加入 approved_for_ingestion。页面页脚声明「中国居民膳食指南 版权所有 Copyright © 2014 cnsoc.org」，未定位到独立版权声明页。定性建议：只做人群层面原则摘要，不得转成个人饮食处方或营养素目标。"
  },
  {
    "id": "sport_gov_fitness_guidance",
    "priority": 2,
    "organization": "国家体育总局",
    "authority_level": "national_sports_authority",
    "jurisdiction": "CN",
    "language": "zh-CN",
    "channel_name": "国家体育总局全民健身科普与《全民健身指南》",
    "entry_url": "https://www.sport.gov.cn/",
    "content_scope": ["全民健身指导", "运动防护与热身", "科学健身科普"],
    "rag_role": "fitness_guidance_candidate",
    "ingestion_status": "permission_required",
    "automated_collection": false,
    "review_interval_days": 90,
    "notes": "2026-10-03 由 DSH 登记为候选来源，未做版权与医学审核，也未加入 approved_for_ingestion。页面页脚标注「国家体育总局版权所有　国家体育总局体育信息中心承办」，未定位到独立版权声明页。定性建议：只讲通用热身与防护，不复制运动处方模板，不为个人开运动处方。"
  },
  {
    "id": "natcm_tcm_wellness",
    "priority": 2,
    "organization": "国家中医药管理局",
    "authority_level": "national_tcm_authority",
    "jurisdiction": "CN",
    "language": "zh-CN",
    "channel_name": "国家中医药管理局中医养生保健素养与工作动态",
    "entry_url": "https://www.natcm.gov.cn/",
    "content_scope": ["中医养生保健素养", "治未病理念", "传统功法科普"],
    "rag_role": "tcm_wellness_candidate",
    "ingestion_status": "permission_required",
    "automated_collection": false,
    "review_interval_days": 90,
    "notes": "2026-10-03 由 DSH 登记为候选来源，未做版权与医学审核，也未加入 approved_for_ingestion。页面页脚标注「版权所有：国家中医药管理局」。审核口径要求：中医「功效」类表述必须改写为理论表述，不得写成疗效承诺；艾灸、拔罐、刮痧等自施操作不做操作指导；个体化体质选式建议需删除或改写。"
  },
  {
    "id": "fujian_wjw_repost",
    "priority": 3,
    "organization": "福建省卫生健康委员会",
    "authority_level": "provincial_health_authority",
    "jurisdiction": "CN",
    "language": "zh-CN",
    "channel_name": "福建省卫健委媒体报道转载",
    "entry_url": "https://wjw.fujian.gov.cn/",
    "content_scope": ["健康科普转载", "传统功法与运动科普"],
    "rag_role": "repost_channel_candidate",
    "ingestion_status": "permission_required",
    "automated_collection": false,
    "review_interval_days": 30,
    "legal_notice_url": "http://wjw.fujian.gov.cn/bzzx/mzsm/",
    "notes": "2026-10-03 由 DSH 登记为候选来源，未做版权与医学审核，也未加入 approved_for_ingestion。已抓取核对该站《免责声明》（2019-02-11）：注明「稿件来源：福建省卫生健康委员会」的稿件版权属该站、未经协议授权不得转载；未注明来源的均为转载稿，使用时必须保留其注明的稿件来源并自负版权等法律责任。对应候选条目《运动是良医！中医健身可以这么练》页面注明来源为新华网，属转载稿、权利在原媒体——入库前必须完成授权判断，建议优先改用国家中医药管理局的原始文件替代。"
  }
]
~~~

### 8.4 落盘时要一并改的（不属于注册表本体）

1. `backend/tests/test_medical_source_registry.py` 的 `TRUSTED_DOMAINS`：加入 `www.sport.gov.cn`、
   `wjw.fujian.gov.cn`（另两个域名 https 未确认，先不加）；
2. `backend/docs/MEDICAL_KNOWLEDGE_SOURCES.md`：来源清单同步（该文件第 12 行指向机器可读注册表）。

### 8.5 验证命令（落盘后必须跑）

~~~powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_medical_source_registry.py -q
& .\.venv\Scripts\python.exe -m pytest tests/test_controlled_ingestion.py -q
~~~

### 8.6 当时的待决问题（**2026-10-03 已决定**：只加 3 家国家级机构、福建那条暂缓）

**是否把这 4 家机构加入受信来源白名单**（中国营养学会 / 国家体育总局 / 国家中医药管理局 / 福建省卫健委）？
这是把「谁算可信来源」从 6 个国家级机构 + WHO，放开到 4 个新机构，属于实质政策决定；决定后才能落盘提案，
之后才轮到「登记 → 医学审核 → 加入 `approved_for_ingestion` → 导入」。