# 健康记录（Health Records）

健康记录保存**用户自己在对话中明确说过的健康信息**，用于在后续对话中减少重复询问、让科普内容更贴合用户关注方向，并在必要时提示就医。

它属于敏感个人信息，因此实现上遵循三条硬约束：

1. **只存用户明说的事实**。AI 只能把用户原话改写成简短陈述；任何推测、疑似判断、诊断结论都不得落库（`app/ai/health_extract.py` 会在写库前直接丢弃这类条目）。
2. **不参与紧急分流**。红旗症状预检（`app/safety/triage.py`）完全独立于健康记录，不读取、也不因记录而降低警惕。
3. **不用于推断病因或判断病情轻重**。注入给模型时附带明确的禁止条款（`app/ai/health_context.py`）。

## 已确认的产品决策

| 决策点 | 结论 | 说明 |
| --- | --- | --- |
| 写入方式 | AI 自动写入，用户之后可自行修改 | 覆盖了 `frontend/PROJECT_ROADMAP.md` 阶段 9 早期「仅在用户确认后保存」的写法 |
| 采集告知 | 首次登录通知一次，之后默认静默采集 | 首次弹窗提供「跳过」「关闭采集」两个出口，「关闭采集」当场生效 |
| 用户控制 | 可在「健康记录」页查看、修改、删除、关闭采集 | 关闭后立即停止提取，且不再注入回答 |

**合规提醒**：健康数据属于《个人信息保护法》定义的敏感个人信息，正式商业化上线前「默认开启 + 仅通知」通常需要单独的合规评估（一般要求单独同意）。当前按个人开发原型实现，上线前必须复核。

## 数据模型

迁移：`migrations/versions/20260916_0013_health_records.py`（`down_revision = 20260916_0012`）。

### `health_records`

| 字段 | 说明 |
| --- | --- |
| `id` / `user_id` | 主键；`user_id` 外键到 `users`，级联删除 |
| `category` | 受控枚举，见下表 |
| `content_ciphertext` | **Fernet 加密**的用户陈述内容 |
| `content_hash` | 规范化（NFKC + casefold）后的 SHA-256，仅用于去重，不可逆推原文 |
| `source` | `onboarding` / `conversation` / `user` |
| `source_message_id` | 来源消息，消息删除时置空（记录保留） |
| `recorded_at` / `created_at` / `updated_at` | 时间戳 |

唯一约束 `uq_health_records_user_category_hash (user_id, category, content_hash)` 保证同一事实只存一条；重复写入走 `ON CONFLICT DO NOTHING`，接口幂等。

### `health_record_settings`

| 字段 | 说明 |
| --- | --- |
| `user_id` | 主键，外键到 `users` |
| `collection_enabled` | 默认 `true`（默认采集），用户可关闭 |
| `notice_seen_at` | 首次通知确认时间 |
| `last_extracted_message_id` | 幂等标记，保证一条消息只提取一次 |

设置行缺失时按默认值处理（采集开启、未通知），因此首次读取设置不会写库。

### 分类枚举

`general_status`（近期身体状态）、`symptom`（近期症状）、`condition`（长期健康情况，用户自述）、`medication`（正在使用的药物）、`allergy`（过敏史）、`lifestyle`（生活方式）、`measurement`（自测指标）、`care_seeking`（就医情况）、`other`（其他）。

## 采集流程

1. 登录后前端调用 `GET /health-records/settings`，若 `noticeSeen` 为 `false` 则弹出一次说明弹窗。
2. 弹窗内用户可以选择最近的身体状态（`general_status` 记录，来源 `onboarding`），或：
   - **跳过**：只写 `noticeSeen=true`，保持默认采集，**不写入任何记录**；
   - **关闭采集**：写 `noticeSeen=true` 且 `collectionEnabled=false`，当场停止采集。
3. 之后不再打扰用户，采集默认进行，用户可随时在「健康记录」页关闭。

## 自动更新（对话提取，2026-09-30 修正）

**触发方式**：服务端在**回答完成链路**里派发，前端不再承担主责。`POST /consultations/{id}/stream`
的生成器在 `finally` 中调用 `health_records.schedule_conversation_extraction()`，因此正常完成、
用户中止、服务异常三条路径都会触发；任务用**自己的会话**（`EXTRACTION_SESSION_FACTORY`）、
有界并发与同消息去重，浏览器关闭、路由切换或前端请求失败都不会造成漏采。前端原有的
fire-and-forget 调用保留为**幂等兜底**。项目没有任务队列/定时器（Redis 等按需引入），
所以「定期更新」依旧是对话事件驱动，而不是调度器。

**抽取资格**（本次修复的核心）：判定只看**那条用户消息本身**，用独立模块
`app/ai/health_eligibility.py`，**不再**复用 RAG 的 `medical_content` / `retrieval_gate_reason`，
也不看 `messages.is_medical_content`。原因：检索门控回答的是「这个提问要不要检索医学知识」，
它把「我最近总口渴」「最近感觉身体状态不错：脸上红红的」这类真实自述判成 `non_medical_content`
（`app/ai/graph/retrieval_gate.py` 的症状词表里没有“口渴/脸上发红”），于是采集开着也什么都存不下来。
新判定按**表述框架**而不是症状白名单区分：用户本人的自述（体感、身体部位、症状、用药、过敏、
生活方式、自测指标、就医、长期情况）→ 抽取；问候寒暄、纯疾病知识问答、模型身份、产品功能提问、
他人情况、以及“我记录里有没有…”这类查询 → 直接 `stored: 0`，且**不产生模型调用**。

**双层过滤**不变：提示词禁止记录推断、建议、身份信息与他人情况，`_upsert_fact` 在
`source is CONVERSATION` 时再用 `is_safe_fact` 过滤一次。

**幂等**：`last_extracted_message_id` 只记最近一条，因此再加一道**记录级**判定——
该消息若已存在 `source_message_id` 相同的记录，直接返回 `already-extracted`，不重新调用模型；
`content_hash` 唯一约束继续兜住语义重复。

**失败处理与可观察性**：提取仍是**尽力而为**，任何 provider 报错都被吞掉并绝不影响对话主流程；
但不再是“完全不可观察”：失败会写受控日志（`health_record_extraction_*`，只带状态码、消息 id 与
异常类型，**不含健康明文与密钥**），`POST /extract` 也会返回 `status`/`reason`。

**成本**：只有通过资格判定的消息才会发起一次非流式模型调用（`temperature=0`、`max_tokens=600`、
优先使用 `available_models()` 中成本最低的兜底模型）；问候与纯知识问答被过滤可显著降低调用量。

人工修改后的记录来源改为 `user`，表示它已是用户确认过的内容。

## 在回答中的使用限制

`app/services/health_records.py::build_health_context` 组装最近至多 20 条、总长不超过 1200 字符的记录 JSON，交给 `app/ai/health_context.py::render_health_context` 包装成系统提示附加段。规则明确写入提示：

1. 只用于避免重复询问、贴合关注方向、提示是否就医；
2. 不得据记录推断病因、判断病情轻重或给出个体化诊断结论；
3. **不得因为记录中存在某项情况而降低对红旗症状的警惕**，紧急分流始终优先；
4. 与用户本次描述冲突时以本次描述为准；
5. 不主动罗列全部记录，不声称已核对病史或病历。

**当用户关闭采集时，`build_health_context` 直接返回 `None`**：既有记录仍可在页面上查看和删除，但不再进入回答上下文。这是一个隐私保守的取舍，若希望「关闭采集只影响新采集、不影响既有记录的个性化」，改动点仅在此函数。

## API

前缀 `/api/v1/health-records`，全部要求登录，且按 `user_id` 隔离（越权访问返回 404）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/settings` | 采集开关、首次通知状态、记录条数 |
| PATCH | `/settings` | 修改 `collectionEnabled` / `noticeSeen`（camelCase，至少一个字段，不接受 null） |
| POST | `/onboarding` | 首次身体状况采集，写入一条 `onboarding` 记录并标记通知已读 |
| GET | `` | 记录列表，`limit` 1–200 |
| POST | `` | 手动新增（来源 `user`），重复内容返回既有记录 |
| PATCH | `/{record_id}` | 修改分类或内容；修改后来源变为 `user` |
| DELETE | `/{record_id}` | 删除，返回 204 |
| POST | `/extract` | 幂等兜底：按 `consultationId` + **助手回答的** `messageId` 定位该轮用户消息并抽取，返回 `{"stored": n, "status": "stored\|skipped\|failed", "reason": <受控码>}`。`skipped` 的 `reason` 取资格判定原因（如 `social-only`、`product-capability`、`general-knowledge-question`）或 `collection-disabled`、`already-extracted`；`failed` 取 provider 错误码 |

## 隐私与数据安全

- 内容使用项目既有 `encrypt_sensitive`（Fernet）加密后落库，读取时解密；
- `content_hash` 只用于去重，不写入明文；
- 身份信息（手机号、身份证、邮箱）在提取阶段就被正则丢弃，不会进入记录；
- 记录随用户删除级联清理；来源消息删除时记录保留但断开引用；
- 提取内容不写日志。

## 已知限制

- 没有定时调度，只能由对话事件触发（见上）。
- 抽取任务脱离请求事务且没有队列：进程若在任务完成前退出，该轮就丢一次（不影响聊天与既有记录）。
  这是「没有任务队列」下最实用的取舍；要更强保证需引入队列，或把抽取并进回答事务（会拖慢流结束）。
- **端到端未覆盖真实浏览器断连**：测试用直接关闭生成器来验证同一个 `finally` 分支，真实断网/断连重试
  没有做浏览器级验收。前端 store 仍会吞掉 `/extract` 的异常（服务端触发已是主责，故不再依赖它），
  健康记录页也不会在对话结束后自动刷新列表——用户需要进入页面重新拉取。
- 资格判定是**面向召回**的中文规则屏（体感/部位/症状/用药/过敏/生活方式/自测/就医词表 + 框架判断），
  英文自述不识别；“家属情况”与本人自述混写在同一句时，屏只保证整句不被丢掉，具体条目由抽取器提示词
  与 `is_safe_fact` 过滤，无法从规则层保证 100% 不写入他人事实。
- 模型能力回答靠系统提示（`HEALTH_RECORD_CAPABILITY_INSTRUCTION`）保证，属于**提示级**约束：
  测试只断言该说明确实进入系统提示，无法机器验证模型一定按它回答。
- 提取依赖模型质量：模型可能漏抽或改写过度，用户需自行核对并修改。
- 同一事实若换一种说法表述，`content_hash` 无法识别，可能产生相近的两条记录（提示中已要求模型参考「已有记录」去重，属于尽力而为）。
- 图表已实现（2026-09-17）：`frontend/src/components/HealthRecordCharts.vue` 按需引入
  ECharts 6.1.0（Bar + Pie，只注册用到的图表与组件，避免整包进主包），范围**明确限定为
  记录条数与分类构成**；不做症状时间线、不做严重度趋势，也不对图表作任何医学判读。

## 接入状态（2026-09-16 已全部完成）

原「待接入」清单已全部落地。共享文件在改动前已备份到 `.dsh-backup/shared-files-before-wiring/`：

1. `backend/app/api/router.py`：注册 `health_records.router`；OpenAPI 实测 5 条路径 / 8 个端点。
2. `backend/app/ai/provider.py`：`stream_chat` 增加 `health_context: str | None = None`，非空时追加到 `system_content`。
3. `backend/app/api/routes/consultations.py`：生成回答前 `await health_service.build_health_context(db, user.id)`，作为第 5 个参数传入 `stream_chat`；注入发生在 `run_consultation_generation` 之后，不会影响红旗分流。
4. `frontend/src/router/index.ts`：`/app` children 增加 `health-records`。
5. `frontend/src/layouts/WorkspaceLayout.vue`：导航入口、挂载 `<HealthRecordNoticeDialog />`、登录后 `checkFirstNotice()`；`onUnmounted` 调用 `reset()`，覆盖退出登录与登录态失效两条路径。
6. `frontend/src/views/HomeView.vue`：回答成功后 `syncFromMessage(cid, userMessage.id)`。中止生成或命中紧急分流时不触发。
7. 文档同步：本文件、`frontend/PROJECT_ROADMAP.md` 阶段 9、`PROJECT_PROGRESS.md`（ADR-010）、`backend/docs/API.md`。

接线时同步更新了既有测试替身，这是改接口签名的必然结果，不是新增功能：`tests/test_consultations.py`
三处 `stream_chat` 桩补第 5 个参数；`tests/test_citation_audit.py` 的用例刻意使用只有 `commit`
的假 `db`，因此桩掉 `build_health_context`。

## 实现要点（非显而易见，改动前请先读）

1. **NFKC 只用于去重哈希，不用于存储**。`_normalized()` 会把全角 `：`、`（）` 折叠成半角，若直接存归一化结果，用户自己写的标点会被静默改写。因此 `_upsert_fact` 与 `update_record` 只做 `strip()`，只有 `content_hash()` 内部做 NFKC + casefold。
2. **`recorded_at` 由 Python 侧写入**。PostgreSQL 的 `now()` 在同一事务内是常量；依赖 server_default 会让同批写入的记录时间戳完全相同，`ORDER BY recorded_at DESC, id DESC` 退化为随机 UUID 排序，注入上下文时进哪几条变得不确定。
3. **安全闸门有两层**。`parse_extraction` 过滤一次，`_upsert_fact` 在 `source is CONVERSATION` 时再用 `is_safe_fact` 过滤一次。只靠提取层的单点过滤，一旦被绕过就会把推断性表述写进记录。
4. **`update_record` 提交后需要 `await db.refresh(row)`**。`updated_at` 由 `onupdate` 在数据库端生成，提交后该属性已过期，直接读取会触发异步懒加载并报错。

## 测试

| 文件 | 数量 | 是否需要数据库 |
| --- | --- | --- |
| `backend/tests/test_health_extract.py` | 28 | 否（提取解析、推理与身份信息拦截、提示词（含“只记本人/拒绝产品功能提问”）、上下文边界、schema 契约） |
| `backend/tests/test_health_records.py` | 19 | 是（默认采集、跳过语义、关闭采集、越权隔离、去重、编辑删除、提取幂等与资格判定、上下文上限） |
| `backend/tests/test_health_extraction_eligibility.py` | 40 | 否（资格判定边界：真实自述可抽、问候/知识问答/身份/产品功能/他人情况不抽，以及与 RAG 门控解耦的结构性断言） |
| `backend/tests/test_health_record_auto_extraction.py` | 11 | 是（服务端回答完成链路落库、生成器被关闭/抽取失败仍完成、幂等（含较早消息重触发）、关闭采集不调用模型、失败可观察且不泄明文） |
| `backend/tests/test_health_record_triage_independence.py` | 5 | 否（红旗预检结构上读不到健康记录；自述病史不削弱升级） |
| `backend/tests/test_health_context_injection.py` | 2 | 否（注入确实进入系统提示词；未提供时不得出现任何相关文本） |
| `backend/tests/test_model_identity.py` | 18 | 否（原 16：各服务商身份与展示模式路由；本任务 +2：产品能力说明确实进入系统提示） |
| `frontend/src/components/HealthRecordNoticeDialog.test.ts` | 6 | 否 |
| `frontend/src/stores/healthRecords.test.ts` | 11 | 否（含首次通知弹出、看过不再弹出、关闭采集后不打扰、同会话只检查一次） |
| `frontend/src/views/healthRecordView.test.ts` | 6 | 否 |
| `frontend/src/layouts/WorkspaceLayout.test.ts` | 4 | 否（登录后自动检查并弹窗、已看过不弹、导航入口、离开工作区清理状态） |

健康记录相关合计：后端 105 项（另含 `test_model_identity.py` 里新增的 2 项能力说明用例）、前端 27 项。

迁移 `20260916_0013` 已应用，**本次修复未新增迁移**（不加表/列/约束）。最近一次全量实测：
**后端 444 项全部通过**（基线 389，本任务 +55），`ruff check app tests` 全绿；
前端 `vitest run` 245 项中 244 通过（唯一失败是 `settings.test.ts` 的 5s 超时，隔离复跑 13/13 通过，
属负载抖动）、`npm run build` exit 0（内含 `vue-tsc -b`）。开发库真实链路验证：服务端触发与接口
两条路径都落下 `source=conversation` 的记录（只替换模型网络出口，未发起付费调用），验证后已清除
占位数据。**仍未做浏览器级“真实断连”验收**（见已知限制）。