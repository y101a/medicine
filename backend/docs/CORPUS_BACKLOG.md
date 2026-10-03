# 语料补充清单（可勾选待办）

> 用途：日后补语料时按行勾选，不必重新盘点。
> 归属：**内容撰写与 dev 原型通道导入**按本清单执行；**来源授权与医学审核**由 Codex / 人工完成。
> 与 `backend/docs/KNOWLEDGE_FOUR_LAYER_GAP_PLAN.md`（Codex 的四层盘点与第一批 4 主题包）对齐，**不重复其已规划项**。
> 本文只是待办清单：**不代表任何一篇已获批准入库，也不代表来源已取证。**

## 0. 每篇的落地流程

1. **核对来源**：找到真实可访问的依据页（记 URL + 发布日期）；取不到就停在草案，不编造依据，不写具体数字。
2. **写正文**：`backend/data/prototype_knowledge/<slug>.md`，含固定免责声明；养生类只写原则与风险，不写剂量、疗程、穴位处方、功效承诺。
3. **导入**：在 `manifest.json` 增条目 → `python -m app.rag.cli seed-prototype`（dev 原型通道）。
4. **向量化**：会调用阿里云向量接口、按量计费、正文外发，**必须先取得用户明确同意**。
5. **收尾**：更新 `PROTOTYPE_KNOWLEDGE.md`、必要时补评测题集、按 `COORDINATION.md` §7 登记。

## 1. 当前分布与缺口（2026-10-03 实测）

现行自编原型 53 篇 / 208 块：养生 14、健身 13、养生健身第一批 9、带人体系统标注 10、早期医学/症状 7；
另有联网摘要缓存 7 篇、历史版本（superseded）15 篇、正式 `approved` **0 篇**。

四层缺口（按 Codex 分层，历史原型尚无标签）：**生理学 0 篇**、药学 1 篇（宽泛）、疾病学 7 篇、
养生健身 36 篇（数量已够，缺的是审核与去重）。

实测佐证：Codex 冻结题集 `medical_retrieval_evaluation_four_layer_batch1.json` 的 `tune` 12 题，
keyword 5/12 → hybrid 8/12；4 个未命中里 3 个是「文档还不存在」（都是生理学体温调节）。

## 2. 清单

状态取值：未开始 / 待核对来源 / 草案已写 / 已入库(prototype) / 已向量化。
所有行的「来源线索」默认 **未取证**，只有在该行单独注明时才表示已找到可用依据。

### W1 与 Codex 第一批对齐（**不重复撰写**，仅留位对照）

| 层 | `topic_key` | slug | 说明 |
| --- | --- | --- | --- |
| 疾病学 | `pediatric_fever` | `pediatric-fever` | 复核现有原型：年龄分层、就医表现、观察记录 |
| 生理学 | `temperature_regulation` | `physiology-temperature-regulation` | **新建**，Codex 已规划；batch1 有 3 道 tune 题等它 |
| 药学 | `rational_antibiotic_use` | `medicine-use` | 复核现有原型 |
| 养生健身 | `safe_activity_start` | `wellness-fitness-guide-framework` | 复核现有原型 |

### W2 生理学（层内 0 篇，优先级最高；只讲正常机制，不写成病因诊断）

| `topic_key` | 建议 slug | 覆盖的普通问法 | 内容边界 | 状态 |
| --- | --- | --- | --- | --- |
| `circulation_basics` | `physiology-circulation-basics` | 血压是怎么来的、脉搏是什么、心脏怎么泵血 | 正常机制；不解释个人血压值、不给目标值 | 未开始 |
| `breathing_gas_exchange` | `physiology-breathing-gas-exchange` | 为什么会喘、氧气怎么进身体、血氧是什么 | 正常机制；不解读个人血氧/影像 | 未开始 |
| `kidney_urine_formation` | `physiology-kidney-urine` | 尿是怎么生成的、尿量多少算正常范围 | 正常机制；不解释化验单、不判断肾病 | 未开始 |
| `digestion_absorption` | `physiology-digestion-absorption` | 胃肠怎么消化、为什么会胀气、肠鸣 | 正常机制；不给饮食处方 | 未开始 |
| `blood_sugar_regulation` | `physiology-blood-sugar-regulation` | 血糖由谁调节、胰岛素做什么 | 正常机制；不解读个人血糖、不提药物剂量 | 未开始 |
| `immune_response` | `physiology-immune-response` | 为什么会发热、红肿是什么反应、免疫做什么 | 正常机制；不把发热写成确诊依据 | 未开始 |
| `sleep_cycle` | `physiology-sleep-cycle` | 睡眠周期是什么、为什么会做梦、昼夜节律 | 正常机制；不诊断失眠 | 未开始 |
| `pain_perception` | `physiology-pain-perception` | 人为什么会痛、痛感怎么传 | 正常机制；不按疼痛部位推断疾病 | 未开始 |
| `fluid_electrolyte` | `physiology-fluid-electrolyte` | 出汗为什么口渴、水和盐怎么平衡 | 正常机制；不给补液方案 | 未开始 |

### W3 疾病学（常见症状 + 就医分流；「复核」表示已有原型、以扩写与核对为主）

| `topic_key` | 建议 slug | 覆盖的普通问法 | 内容边界 | 状态 |
| --- | --- | --- | --- | --- |
| `common_cold_vs_flu` | `disease-cold-and-flu` | 感冒和流感怎么区分、什么时候该去医院 | 科普与分流；不给用药方案 | 未开始 |
| `adult_fever` | `disease-fever-in-adults` | 成人发热要观察什么、几天不退怎么办 | 分流；不按体温单独定性 | 未开始 |
| `hypertension` | `disease-hypertension` | 血压高是什么概念、量血压注意什么 | 只讲测量与就医；**不调药、不给目标值** | 未开始 |
| `diabetes_basics` | `disease-diabetes-basics` | 血糖高要注意什么、多久复查 | 只讲就医与自我观察；不给饮食/用药处方 | 未开始 |
| `upper_abdominal_discomfort` | `disease-dyspepsia_reflux` | 反酸烧心、上腹不适常见原因 | 已有胃食管反流语料，先查重再定 | 待核对来源 |
| `cough_and_lung_signs` | `disease-cough-lung-signs` | 咳嗽多久要检查、哪些表现要急诊 | 分流；不解读胸片/CT | 未开始 |
| `dizziness_vs_vertigo` | `disease-dizziness-vertigo` | 头晕和眩晕差别、什么时候危险 | 现有 `headache-dizziness` 扩写，不新开同题 | 待核对来源 |
| `urinary_tract_infection` | `hematuria-urinary-tract-infection` | 尿频尿痛、血尿要不要就医 | 复核现有原型 | 待核对来源 |
| `common_rash` | `urticaria-eczema` | 起疹子怎么观察、何时就医 | 复核现有原型 | 待核对来源 |
| `constipation_diarrhea` | `disease-bowel-habits` | 便秘、腹泻一般怎么处理到哪一步 | 只讲原则与危险信号；不给药物剂量 | 未开始 |
| `anemia_fatigue` | `disease-anemia-fatigue` | 老是乏力、脸色差是不是贫血 | 需检查后由医生判断；不自行补铁 | 未开始 |
| `thyroid_nodule` | `disease-thyroid-nodule` | 查出甲状腺结节严重吗、多久复查 | 只讲随访与就医；不定性、不解读超声 | 未开始 |
| `neck_low_back_pain` | `disease-neck-back-pain` | 颈腰痛哪些信号要就医 | 分流；不给复位/锻炼处方 | 未开始 |
| `eye_ear_complaints` | `disease-eye-ear-complaints` | 红眼、耳鸣常见原因与就医时机 | 分流；不诊断视力/听力问题 | 未开始 |
| `emergency_red_flags` | `emergency-red-flags` | 哪些表现必须马上就医 | 复核现有原型（急症分流核心，优先） | 待核对来源 |

### W4 药学（现有 1 篇偏宽泛；只讲一般安全与咨询，不给剂量、疗程、处方）

| `topic_key` | 建议 slug | 覆盖的普通问法 | 内容边界 | 状态 |
| --- | --- | --- | --- | --- |
| `reading_drug_label` | `pharmacology-drug-label` | 说明书怎么看、适应症和禁忌是什么 | 教读法；不针对具体个人用药 | 未开始 |
| `analgesic_antipyretic_safety` | `pharmacology-analgesic-safety` | 退烧止痛药能随便吃吗、重复用药风险 | 一般风险与咨询就医；**不给剂量与频次** | 未开始 |
| `multiple_medication_risk` | `pharmacology-drug-interaction-basics` | 同时吃几种药要注意什么 | 讲咨询药师/医生的重要性；不做个人相互作用判断 | 未开始 |
| `medicine_storage_expiry` | `pharmacology-storage-expiry` | 家里的药能放多久、过期了怎么办 | 只讲原则；不给具体药品处置建议 | 未开始 |
| `patent_medicine_boundary` | `pharmacology-patent-medicine-boundary` | 中成药能不能自己长期吃 | 使用边界与风险；不给具体品种与疗程 | 未开始 |

### W5 养生健身补充（该层数量已够，只在有明确空档时补）

| `topic_key` | 建议 slug | 覆盖的普通问法 | 内容边界 | 状态 |
| --- | --- | --- | --- | --- |
| `sleep_hygiene` | `wellness-sleep-hygiene` | 怎么睡得好、熬夜怎么调 | 只讲一般作息原则；不诊断失眠、不给褪黑素用法 | 未开始 |
| `screen_time_eyes` | `wellness-screen-eyes` | 看屏幕久了眼睛累怎么办 | 与 `wellness-sedentary-behaviour` 查重后再定 | 待核对来源 |
| `oral_health` | `wellness-oral-health` | 刷牙、牙龈出血、多久看牙 | 一般口腔保健；不诊断牙周病 | 未开始 |
| `hearing_protection` | `wellness-hearing-protection` | 耳机音量、噪声伤听力 | 一般防护原则；不判断听力损失程度 | 未开始 |
| `vaccination_basics` | `wellness-vaccination-basics` | 疫苗一般是怎么回事 | 只讲一般常识；**不给个人接种建议**，指向接种点 | 未开始 |

## 3. 来源线索

- **已在册的受信来源（登记 ≠ 授权入库）**：国家卫健委健康素养与临床指南、国家药监局药品核验、
  国家中医药管理局、国家体育总局、中国疾控（营养与健康所 / 慢病中心）等，见 `medical_source_registry.json`
  与既有登记记录；`approved_for_ingestion` 仍是 **3 条**。
- **取不到或不可用的页**（不要再假设可用）：`nhc.gov.cn` 返回 HTTP 412、中国疾控主站与 WHO 中文页未打开、
  《中国人群身体活动指南（2021）》原文未获得、太极拳 `sport.gov.cn` 页面 403。
- 每篇落笔前必须**当场重新取证**：登记在册只说明允许考虑，不说明能直接引用。

## 4. 纪律（写之前先读）

- **不重复同题**：W3/W5 标「复核 / 待核对来源」的行先查重，能扩写就不新开文档。
- 养生类只写原则与风险；中医内容注明「中医理论表述」，不给穴位处方、艾灸拔罐操作步骤、疗程与功效承诺。
- 不伪造审核人与审核时间；原型一律 `review_status=prototype`，**不得**改成 `approved`。
- 评测纪律（沿用 Codex）：`tune` 可随时跑；**`holdout` 在内容与检索配置冻结前不得查看**。
  首批门槛：`tune` Top-3 ≥ 11/12、冻结后 `holdout` Top-3 ≥ 7/8，每层 ≥ 4/5。
- 检索命中 ≠ 回答安全或医学正确：危险表现必须保留及时就医分流。

## 5. 建议顺序

W2 生理学（0 篇，batch1 的 3 道 tune 题全靠它）→ W3 高风险主题（急症分流、儿童/成人发热、用药相关）
→ W4 药学 → W5 补充。养生健身层暂不铺量，先把审核与去重做完。