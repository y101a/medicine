# 药品说明书识别：前后端实现方案

> 起草：DSH（2026-09-23）｜状态：**已全部落地并通过复核**——前端 DSH `56df4e5`；后端 Codex `f8d9482` + `1221a03`（v6、迁移 `20260923_0021`、291 passed，DSH 已独立重跑）。**真实说明书样例的识别效果仍待联调**（第 5 节）
> 本文件是**方案**，不是契约。类别取值、边界文案与错误码以 `backend/docs/MEDICAL_IMAGES.md` 为准，Codex 落地时请直接更新那份契约并在 `COORDINATION.md` 第 6 节回执。
> 触发来源：用户要求「图片识别：借助多模态大模型的能力，识别图片中的图像和文字；可用于识别病历、识别药品说明书等」，并要求核对代码是否已实现。

---

## 0. 决策：已由用户拍板（2026-09-23）

> **D1 = A3（用法用量原文照旧转录，并在渲染模板与上下文指令里强制加限定语）**
> **D2 = B2（新增第五类类别 `medication_leaflet`，而不是归入 `report`）**
>
> 用户于 2026-09-23 明确选择。据此：**第 3 节即为定稿实现方案**；第 4 节（B1）与 D1 的 A1/A2 分支保留仅为决策记录，**不再实施**。
> 由此固定的两条约束：①`ocr_text` 中的用法用量原文**必须原样保留**（不得静默删除），同时必须出现「仅转录、未核对、不可作为用药依据」限定语；②类别字符串定为 **`medication_leaflet`**（前端已按此实现，后端请勿改名；若必须改名，请先在第 6 节回执并通知 DSH 同步前端）。

原始决策依据（供追溯）：

| 编号 | 决策 | 选项 | 影响面 | 推荐 |
| --- | --- | --- | --- | --- |
| **D1** | 说明书里的**用法用量原文**怎么处理 | **A1 全文转录**（现状行为）／**A2 一律不转录、遮蔽剂量**／**A3 全文转录 + 强制限定语** | A1 零改动但有「变相传递用药信息」风险；A2 需新增剂量正则过滤与替换文案，且用户拿不到说明书原文；A3 只需在渲染模板与上下文指令里加限定语，信息不丢、责任边界清楚 | **A3** |
| **D2** | 说明书**是否新增第五类类别** | **B1 归入现有 `report`**／**B2 新增 `medication_leaflet`** | B1 无迁移、无类型变更，但界面会给说明书照片显示「报告 / 检查单」，且与报告共用同一段边界文案，剂量风险无法单独措辞；B2 需要 1 个迁移 + 4 处后端类别列表 + 2 处前端类型与文案 + 测试同步，换来独立标签、独立边界文案与独立上下文指令 | **B2** |

第 3 节 = **定稿实现方案**（D1=A3、D2=B2）；第 4 节与 D1 的 A1/A2 分支仅作记录，不实施。

---

## 1. 现状核对（DSH 读代码确认，附依据）

| 能力 | 现状 | 依据 |
| --- | --- | --- |
| 借助多模态大模型识别图像与文字 | **已实现**：服务端把规范化图以 base64 data URL 发给固定模型（`qwen3.8-flash`），`temperature=0`、强制 `json_object`，输出严格七字段 JSON | `backend/app/services/image_analysis.py:299-321`、`:41-50` |
| 识别病历类文字资料 | **部分实现**：`report` 类提取 `ocr_text` 并落库、进上下文 | `:84-85`、`:249-257` |
| 识别药品说明书 | **未实现**：`report` 定义未点名说明书；全仓库「药品」只出现在检索容灾站点清单（`backend/app/rag/web_search.py:174`），无类别、无文案、无测试；落 `unrelated` 时只回「未检测到医疗健康相关内容」，**静默失效** | grep 结果；`:92` |
| OCR 文本的剂量过滤 | **无**：`_FORBIDDEN_BODY` 只作用于身体照片的 `visible_facts`（`_clean_items(..., forbid_clinical=True)`），对 `ocr_text` 不生效 | `:35-38`、`:101`、`:269` |
| 回答层护栏 | **已有**：上下文禁止「开处方、推荐具体用药剂量」；有测试钉住 | `backend/app/ai/attachment_context.py:18-19`、`backend/tests/test_attachments.py:290` |
| 影像判读 | **明确不做**（产品边界，非缺口）：只写模态/部位/可见标签 | `:86-87` |
| 真实准确率 | **未验证**：所有模型调用都是桩（后端 `httpx.MockTransport`、前端接口桩），无病历/说明书真实样例记录 | 测试代码 |
| 小字可读性 | 链路统一压到长边 ≤2400 px、WebP 质量 82，说明书 6 号字易糊 → 更易返回 422 `IMAGE_NO_TEXT` / `IMAGE_CATEGORY_UNCLEAR`，界面看起来像「上传失败」 | `backend/app/services/image_validation.py`、`frontend/src/composables/imagePrep.ts:15` |

---

## 2. 目标与非目标

**目标**
1. 说明书照片（整张、局部、包装盒侧面、用药指导单）能被稳定判为说明书类，而不是 `unrelated`。
2. 文字如实转录（含用法用量原文），不补全看不清的内容，不改写、不换算单位。
3. 界面显示「药品说明书」标签与该类**专属**边界文案；历史消息、草稿区、刷新恢复一致。
4. 回答层可以引用/解释说明书已写明的文字，但**绝不**给出是否服用、剂量、加减量、替代或停用建议。
5. 审计、加密留存、删除、限流、清理规则与现有图片完全一致（不新开一套）。

**非目标（明确不做，请在契约里保持）**
- 判读影像病灶、给诊断或概率；根据照片推断疾病。
- 剂量换算（如 mg↔片）、按体重/年龄计算、疗程建议。
- 药物相互作用、禁忌判断、能否与其它药同服、替代或停用建议。
- 手写专项识别（另立任务；见第 7 节）。真实说明书多为印刷体，本任务不为手写做架构改动。

---

## 3. 推荐方案（D1=A3、D2=B2）的完整改动清单

### 3.1 后端（所有权：Codex）

| 文件 | 改动 | 要点 |
| --- | --- | --- |
| `backend/app/services/image_analysis.py` | ①`ANALYSIS_VERSION` 升版（当前 `medical-image-auto-category-v5` → v6，语义变更必须升版，它写进附件记录与审计）②`DetectedImageCategory`（`:28-34`）与 `AcceptedImageCategory`（`:25-27`）都加 `medication_leaflet` ③`_SYSTEM_PROMPT`（`:79-94`）新增类别定义 ④`_render()` 新增分支 ⑤必要时补 `_TEXT_FIELD_LIMITS`（`:39`） | 类别定义建议原文见下 |
| `backend/app/ai/attachment_context.py` | 在 `ATTACHMENT_CONTEXT_INSTRUCTION`（`:15-26`）中加说明书类限制语 | 建议原文见下 |
| `backend/app/schemas/attachments.py` | `ImageCategory` Literal（`:7`）加值（`:23`、`:50` 两处响应模型自动跟随） | 不加值会导致响应校验失败 |
| `backend/app/models/attachment.py` | CHECK 约束 `image_category_supported`（`:81-83`）的值列表加 `medication_leaflet` | 与迁移必须一致 |
| `backend/migrations/versions/` | 新建迁移 `2026092X_00NN_medication_leaflet.py`：drop + create `ck_attachments_image_category_supported`，**完全照 `20260922_0019_allow_unrelated_images.py` 的写法**（含 downgrade 的保守失败检查：仍有该类别行时不静默丢数据） | 编号按开工时最新 revision +1；**当前最新是 `20260923_0020_image_deletion_jobs.py`** |
| `backend/app/services/attachments.py` | **无需改动**（`image_category=category` 透传，`:148`；读取 `:55`、`:70` 也无需改） | 此处仅确认，避免误改 |
| `backend/app/api/routes/images.py` | **无需改动**（说明书沿用同一上传/规范化/识别/加密/审计路径） | 同上 |
| `backend/docs/MEDICAL_IMAGES.md` | 更新：第 9-10 行的类别说明、第 191-192 行的类别表与摘要规则、第 206-207 行的可保存类别与迁移说明、§10.2/§10.4 | 这份是契约，必须与代码同时更新 |
| `backend/docs/API.md`、`backend/docs/DATA_MODEL.md` | 若其中列出了图片类别取值或 CHECK 约束，一并对齐 | 不确定就先 grep `unrelated` |
| `backend/tests/test_medical_images.py` | 新增用例（见 3.3） | 沿用 `httpx.MockTransport` 桩 |
| `backend/tests/test_attachments.py` | 扩展上下文断言（现有 `:290` 已断言「不得／处方／用药剂量」） | 追加说明书限制语断言 |

**`_SYSTEM_PROMPT` 新增类别定义（建议原文，可直接用）**

```
medication_leaflet：药品说明书、用药指导单、疫苗说明书等以药品信息为主的印刷或拍摄资料；
忠实提取能看清的文字、数值、单位与原文用法用量表述，不换算、不比较、不推荐、不判断是否适合该用户；
看不清的部分留空，不得补全、不得据常识补充。
```

同时建议把 `report` 定义（`:84-85`）结尾补一句「（药品说明书请判为 medication_leaflet）」，减少两类的边界摇摆。

**`_render()` 新增分支（建议原文，对应 D1=A3）**

```
药品说明书文字提取（仅转录，未核对，不可作为用药依据）：
{ocr_text 截断 20000 字}
图片质量：{suffix}
限制：以上是说明书原文转录；是否适合你、剂量是否需要调整，请以说明书原文并遵医嘱或咨询药师；
本回答不提供是否服用、剂量加减、替代或停用建议。
```

空 `ocr_text` 时的处理与 `report` 一致：抛 422 `IMAGE_NO_TEXT`（「未识别到清晰文字，请换一张更清楚的图片」），不落库、不落盘。

**`attachment_context.py` 追加的限制语（建议原文）**

```
当 imageCategory 为 medication_leaflet 时：只能转录或解释说明书已写明的文字，必须提示「以说明书原文与
医生或药师意见为准」；不得推荐是否服用、不得给出或换算剂量、不得比较或替代其他药物、不得判断能否同服、
不得推断药物相互作用。用户问「我该吃多少」这类问题时，只引导其核对说明书原文并咨询医生或药师。
```

### 3.2 前端（所有权：DSH）

| 文件 | 改动 | 要点 |
| --- | --- | --- |
| `frontend/src/types/consultations.ts` | `ImageCategory`（`:34`）加 `medication_leaflet` | 与 `imagePrep.ts` 是两处历史重复定义，**两处都要改**（本轮不合并，避免夹带重构） |
| `frontend/src/composables/imagePrep.ts` | `ImageCategory`（`:37`）、`IMAGE_CATEGORY_LABELS`、`IMAGE_CATEGORY_NOTICES` 各加一项 | 建议文案见下 |
| `frontend/src/views/HomeView.vue` | `IMAGE_ATTACHMENT_PROMPT` 补「说明书上的文字」；**无需**改渲染逻辑（标签/边界行按 map 取值、隐藏判定按常量引用） | 默认提问仍只发给模型、不显示给用户 |
| `frontend/src/composables/composerPrompts.ts` | **新增**：把 `DEFAULT_ATTACHMENT_PROMPT`、`IMAGE_ATTACHMENT_PROMPT`、`HIDDEN_AUTO_PROMPTS`、`isHiddenAutoPrompt` 从 `HomeView.vue` 抽到独立模块 | 同一份文案既发给模型又用于「不该显示」判定，抄两份必然漂移——本次改文案时就真的踩到（测试里硬编码旧句导致隐藏失效），故收成单一来源；`HomeView` 改为 import |
| `frontend/src/api/attachments.ts`、`useAttachments.ts` | **无需改动** | 类别来自响应，前端不判断 |
| （可选，建议单列）`frontend/src/components/MessageAttachments.vue` | 历史消息里显示类别标签 | 现在历史图片不显示类别——说明书在历史里更该看得出是哪一类；这属于既有缺口，可与本任务一起做或单列 |

**标签与边界文案（建议原文）**

```ts
medication_leaflet: '药品说明书'
// 边界
'只读取并转写说明书上的文字（含用法用量原文），不作用药建议、不换算剂量；是否适合你请遵医嘱或咨询药师。'
```

`IMAGE_ATTACHMENT_PROMPT` 建议改为（**已落地**）：

```
请根据我上传的图片，帮我整理能读到的信息（报告上的指标、说明书上的文字，或片子和照片上肉眼可见、非诊断性的情况），并说明下一步该看什么科；不要作出确诊，也不要判读影像。
```

### 3.3 测试清单（新增，两侧都要）

后端（`backend/tests/test_medical_images.py`，桩 + 断言）：
1. 说明书类被接受：返回 201、`imageCategory == "medication_leaflet"`、密文与 90 天留存字段齐全。
2. 渲染模板：正文以「药品说明书文字提取」「仅转录」「不可作为用药依据」开头，且含限定语。
3. D1=A3 断言：`ocr_text` 中的用法用量原文**被保留**（不静默删除），限定语同时存在。
4. 空文字：`ocr_text` 为空时 422 `IMAGE_NO_TEXT`，且不落库、不落盘（审计为 rejected）。
5. 上下文：消息绑定说明书附件后，`build_attachment_context` 输出含说明书限制语（扩展 `test_attachments.py:290` 那条）。
6. 迁移：upgrade 后 CHECK 接受第五类；downgrade 时若仍存在该类别行则**保守失败**（照 `20260922_0019` 的既有断言写法）。
7. 旧客户端兼容：multipart 里仍带 `imageCategory` 时被忽略（沿用既有的忽略旧字段用例并覆盖新值）。

前端：
1. 单测（`frontend/src/views/images.test.ts`）：五类边界文案循环加说明书一例；「被判为药品说明书的照常是成功附件：显示标签与边界、且能发送」；「刷新已有会话时说明书类别与边界恢复」。
2. 单测（`frontend/src/composables/imagePrep.test.ts`）：类别清单断言由四类改五类，并断言说明书标签与边界关键词（「不作用药建议」）。
3. e2e（`frontend/e2e/images.spec.ts`）：说明书照片显示「药品说明书」标签与边界、可随提问发出；说明书图读不出文字（422 `IMAGE_NO_TEXT`）时给可关闭短提示、不进卡片。
4. `frontend/BROWSER_ACCEPTANCE.md`：`images.spec.ts` 行与人工验收第 3 条同步（含说明书类别）。

### 3.4 顺序与冻结点

1. **Codex 先**：类别取值 + 迁移 + 提示词 + 契约文档 → 这一步定死「类别字符串 `medication_leaflet`」与两段限制语文本。**（状态：已完成，提交 `1221a03`，见第 9 节复核）**
2. **DSH 后/并行**：前端类型、标签、边界文案、默认提问、单测与 e2e 可以**先用桩按新类别开发**，不阻塞 Codex；等它落地后再跑一次真实链路。**（状态：已完成，提交 `56df4e5`）**
3. **真实样例评测**（第 5 节）最后做，需要用户确认付费外发。

### 3.5 验收基线（两侧提交前必须过）

| 侧 | 命令 | 当前基线 | 提交后期望 |
| --- | --- | --- | --- |
| 后端 | `.venv\Scripts\python.exe -m pytest -q`、`ruff check --line-length 100 --select E,F,I,UP,B` | **291 passed**（Codex 报告，DSH 已独立重跑）、Ruff 全绿、迁移 `0021 -> 0020 -> 0021` 往返通过 | 不低于 291，全绿 |
| 前端 | `npx vitest run`、`npm run build` | **171 passed / 17 files**、构建退出码 0（DSH `56df4e5` 已达成） | 不低于 171 / 17，构建退出码 0 |
| e2e | `npx playwright test` | **50 项**（新增说明书用例后；该文件在满负载下偶发超时，需隔离复跑定性） | 不低于 50 项 |

---

## 4. 若选 B1（归入 `report`，不新增类别）的差异清单

只做这些，其余照旧：

1. `image_analysis.py` 的 `report` 定义里点名说明书（「药品说明书、用药指导单同属本类」），**不新增类别、不升 CHECK、不加迁移**。
2. `attachment_context.py` 的限制语改成按「文字资料」统一表述（说明书与报告共用同一段，无法只为说明书措辞）。
3. 前端 `ImageCategory` 不动；但建议把标签改为「报告 / 检查单 / 说明书」并同步边界文案（否则说明书照片会显示「报告 / 检查单」）。
4. 代价：说明书的剂量风险与检验单混在一起，将来要单独收紧时仍要再做一次 B2。

---

## 5. 真实样例评测方案（**需用户确认后才能执行**：涉及付费调用与图片外发）

样例矩阵（每格建议 ≥3 张，覆盖不同光照/角度）：

| 类型 | 样例要点 | 关心什么 |
| --- | --- | --- |
| 印刷病历/出院小结 | 正常、反光、折痕 | 类别是否 `report`、文字转录完整度 |
| 手写病历/医嘱 | 圆珠笔、铅笔、连笔 | 错字率（本任务不修，但要留数据） |
| 检验单 | 小字、多列、箭头标记 | 数值与单位是否读对、参考范围 |
| 处方单 | 手写+印刷混合 | 类别与转录 |
| **药品说明书** | 整张、局部放大、包装侧面、反光 | 是否稳定判为 `medication_leaflet`、用法用量原文是否完整、失败码 |
| 无关图 | 风景/商品 | 是否稳落 `unrelated`（防误判医疗） |

每条记录：类别判定、`ocr_text` 与人工抄录的关键字段差异（数值/单位/剂量逐项比对）、`quality_warnings`、端到端耗时、失败错误码。

通过标准（**建议值，不是结论**，需你确认后才作为验收门槛）：类别判定正确率 ≥ 90%；关键数值（检验值、剂量数字）转录与人工核对一致率 100% 才允许作为后续引用依据，否则界面必须提示「请核对原件」。

---

## 6. 隐私与合规

1. 说明书与病历同属医疗健康敏感信息，**沿用现有全套规则**：本地去 EXIF → 服务端统一 WebP → AES-GCM 加密落盘 → 90 天保留 → 24 小时未绑定孤儿清理 → 删除与账号删除联动 → 审计。
2. 说明书照片常含厂家、批号、条码、有效期；现有 `redact_direct_identifiers` 已在上下文渲染时做直接身份标识脱敏，说明书沿用，**不新增提取字段**（不要顺手抽批号/条码）。
3. 首次上传同意说明（`IMAGE_CONSENT_NOTICE`）目前只提「报告、片子、患处照片」类语义，建议补一句：说明书照片按同一规则处理与外发。

---

## 7. 风险与未验证（写作时不得省略）

1. **真实识别准确率未知**：仓库内没有真实病历/说明书样例结果；说明书字小 + 链路压到 2400 px/WebP 82，可能更常触发 `IMAGE_NO_TEXT`/`unclear`。
2. **说明书可能仍被判成 `unrelated`**：新增类别后需靠提示词 + 评测确认，不能只靠代码断言；这也是本任务的主要验收风险。
3. **手写病历仍是弱项**（无专项能力、无置信度字段），本方案不为它做架构改动。
4. **D1 未定则无法写测试**：A3 断言「原文保留 + 限定语」，A2 断言「不含剂量数字」，两者互斥。
5. **迁移编号会变**：开工时必须按当时最新 revision +1（当前 `20260923_0020`）；降级路径要保守失败，避免丢数据。
6. **前端历史消息不显示类别**（既有缺口）：若不一并做，说明书在历史里看不出类别。

---

## 8. 请 Codex 的回执方式

1. 在 `COORDINATION.md` 第 6 节对应行更新状态（认领 / 完成 / 变更）。
2. 落地时同步更新契约 `backend/docs/MEDICAL_IMAGES.md`（类别表、边界、§10.2/§10.4）与迁移说明。
3. 在 `COORDINATION.md` 7.2 顶部写四行报告（改动 / 根因或设计 / 验证 / 未验证），并给出新基线数字。
4. 若你认为 D2 应选 B1、或 D1 应选 A1/A2，请直接在本文件对应行批注并说明理由——**不要静默改方案**。

---

## 9. 复核结论（DSH，2026-09-24，针对 Codex `f8d9482` + `1221a03`）

### 逐条核对方案第 3.1 节：全部通过

| 要求 | 结果 |
| --- | --- |
| `ANALYSIS_VERSION` 升版 | ✅ `medical-image-auto-category-v6`（`image_analysis.py:20`；测试断言记录里的 `analysis_version == v6`） |
| 两个 Literal 加 `medication_leaflet` | ✅ `:26`（Accepted）/ `:32`（Detected） |
| `_SYSTEM_PROMPT` 类别定义 | ✅ `:94-96`；且 `report` 明确写「不包括药品说明书」`:86`——比方案建议更严，直接消除两类摇摆 |
| `_render()` 新分支与 A3 | ✅ `:263-273`：`ocr[:20_000]` **原文保留**、标题含「仅转录，未核对，不可作为用药依据」、结尾含「不提供是否服用、剂量加减、替代或停用建议」；空文字 → 422 `IMAGE_NO_TEXT`，不落库不落盘 |
| 上下文护栏 | ✅ `attachment_context.py:57-62` 说明书专属规则；`:32-40` 只按本轮**实际**类别注入，并声明「不得虚构或套用未出现的类别结论」——正好覆盖此前跨类别污染那类问题 |
| Schema / ORM 约束 | ✅ `schemas/attachments.py:8`、`models/attachment.py:82` |
| 迁移与降级保守失败 | ✅ `20260923_0021`，`down_revision = 20260923_0020`，照 `0019` 先例 drop+create；降级先 `count(*)`，命中即 `RuntimeError` |
| 测试 | ✅ A3 渲染（原文 + 限定语）、空文字 422、降级拒绝、五类参数化、API 端到端（201 / v6 / chunk 含原文与限定语 / 上下文含类别与两条护栏） |
| 契约文档 | ✅ `MEDICAL_IMAGES.md` 第 3 行与类别表、错误码、迁移章节；`API.md:303-307`；`DATA_MODEL.md:45` |

### DSH 亲自重跑（独立于 Codex 的自述）
后端 `pytest -q` **291 passed**；Ruff 全绿；`alembic current` = `20260923_0021 (head)`；迁移 `0021 → 0020 → 0021` 往返成功；并直接查询线上库约束定义，五个取值都在（含 `medication_leaflet`）。

### 复核发现（都不影响可用性）
1. `image_analysis.py:98` 的 `unclear` 定义仍写「无法可靠判断是否属于**前四类**」，加了第五类后应为「前五类」（`:97` 的 `unrelated` 写「前四类」是对的，因为说明书已进入前四）。属 Codex 文件，已写进 `COORDINATION.md` 第 6 节。
2. `attachment_context.py:79` 的 `unrelated` 护栏列的是「不得套用到 report、medical_imaging 或 body_photo」，**漏了 `medication_leaflet`**——同一轮里既有说明书又有普通图片时，普通图片的结论有外溢到说明书的余地。建议补上类别名。
3. `PROJECT_PROGRESS.md` 两处仍写「四类」（已由 DSH 更新为五类）。
4. 可选建议（取向问题，非缺陷）：`_response_guidance` 的通用要求（③给 2–4 条居家建议、④分级就医条件）对「只上传说明书」的一轮略显生硬，可考虑对纯说明书轮次放宽「凑建议」的压力。

### 仍然未验证
真实说明书照片的类别判定与 OCR 准确率（第 5 节评测矩阵，需用户确认付费外发才能做）；**v6 的真实付费调用未由 DSH 执行**。