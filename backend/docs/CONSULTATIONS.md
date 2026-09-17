# 咨询与消息

所有路径使用 /api/v1 前缀，需要当前登录 Cookie。未登录返回 401；其他用户的
咨询与不存在的咨询统一返回 404。接口不接受客户端指定 user_id 或消息角色。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /consultations | 创建空会话 |
| GET | /consultations | 当前用户列表，offset 默认 0，limit 默认 20、最大 100 |
| GET | /consultations/{id} | 标题、消息数及时间 |
| POST | /consultations/{id}/messages | 保存用户消息 |
| GET | /consultations/{id}/messages | 最近 50 条，可用 before=序号向前加载 |
| POST | /consultations/{id}/stream | 生成并流式返回 AI 科普回答 |
| DELETE | /consultations/{id} | 永久删除会话及全部消息，返回 204 |
| GET | /models | 返回当前已配置并允许用户选择的模型 |

创建请求：{"clientRequestId":"UUID"}。
发送请求：{"clientRequestId":"UUID","content":"症状描述"}。
内容去首尾空白后为 1–2000 字符。消息角色为 user 或 assistant。
列表响应均为 {"items": [...], "hasMore": true/false}。
消息页按序号升序返回，before 是不包含该序号的上界。

保存用户消息时，后端会先执行独立于大模型的红旗症状预检。命中后消息响应包含
`triage`，前端直接展示固定紧急分流卡并停止模型调用；流式接口也会返回
`EMERGENCY_TRIAGE_ACTIVE`，防止绕过。即使没有配置模型 API Key，该预检仍可使用。
结果加密保存在 `messages.triage_ciphertext`。规则范围和限制见 `RED_FLAG_TRIAGE.md`。

流式回答请求：
`{"clientRequestId":"UUID","modelId":"deepseek-v4-flash","answerFormat":"plain"}`。
`answerFormat` 可选 `plain` 或 `card`，默认 `plain`。用户首次提问始终使用普通模式；
后端判定本条完成回答属于医疗内容时，前端在回答下显示“→ 是否生成一张病理科普卡片”。
用户确认后再次请求 `answerFormat: "card"`，并通过 `sourceMessageId` 指向原助手回答。
服务端会从原回答对应的用户问题生成固定分区卡片，而不是把助手回答当作新问题；原回答
保持不变，卡片作为新的助手消息追加并持久化。同一原回答只允许生成一张完成卡片，停止
或失败的卡片不占用该限制，可以重试。结构化追问和紧急分流不显示此入口。服务端只接受
模型注册表中的 ID，并且对应供应商必须已配置 API Key。服务端读取当前用户最近 30 条
会话消息，最后一条必须是用户消息；响应类型为 `application/x-ndjson`，依次发送
`start`、`delta`、`done` 或 `error` 事件。浏览器通过 AbortController 停止生成。
若已经产生部分正文，服务端会尽量保存并标记为已停止。AI 回答最多 12000 字符。
助手消息保存 `provider`、`modelId`、`modelName`、`generationStatus`、`answerFormat`、
`medicalContent` 和 `sourceMessageId`，因此同一会话可以逐条切换模型，刷新页面后仍能恢复
原回答、追加卡片及两者关系。

### 本轮回答引用核验（2026-09-14）

只有模型实际输出的 `[来源N]` 且 N 能对应本轮检索片段时，服务端才会将该片段
加密保存到助手消息的 `citations`。编号按传给模型的检索片段顺序生成，同一网页
的不同片段保留各自编号；`done.message.citations[].referenceNumber` 和历史消息
保持原始编号，前端折叠来源区按该编号展示。`start.retrieval.sources` 是本轮
可用的检索候选，不代表回答已经引用了这些资料。

不存在的来源编号会在最终保存的正文中改为 `[引用未核实]`，且不会进入来源列表；
若检索到了资料而回答未标注来源，最终正文提示无法核对两者的对应关系。结构化
追问不显示来源。旧消息中的来源快照缺少 `referenceNumber`，前端标为“历史检索
资料（引用未核验）”，不能推定其实际用于回答。此规则只核对编号是否存在，
不验证医学陈述是否被对应资料证实；核验在生成完成或保存中断片段时进行，流式
传输中的中间文本尚未经过最终核验。

### 健康记录注入（2026-09-16）

用户自述健康记录（见 `docs/HEALTH_RECORDS.md`）会作为受限背景追加到系统提示词，排在
检索证据之后。它只用于避免重复询问、贴合科普和提醒就医，并附带强制条款：不得据记录
推断病因，也不得因为记录中存在某项情况而降低对红旗症状的警惕；本轮描述与记录冲突时
以本轮描述为准。

红旗预检只接受本轮文本、结构上读不到健康记录，因此记录既不能触发、也不能压低紧急分流。
用户在健康记录页关闭采集后，记录不再进入提示词；提取或写入失败都不影响回答生成。

当信息不足且不存在需要立即就医的红旗表现时，模型可以返回结构化追问卡。后端只接受
2–5 个问题，并将控件限制为单选、多选、0–10 程度滑块和短文本；选择题最多 8 个选项。
校验通过后，`done` 事件及消息历史会增加 `followUp` 字段，前端将其渲染成可选择、
可提交的卡片。提交结果以一条可读的“补充信息”用户消息保存，然后继续生成科普回答。
卡片原始结构与消息正文一同加密保存，不新增明文医疗数据字段。非法结构不会保存，并
返回 `AI_INVALID_STRUCTURED_RESPONSE`，可以按现有流程由用户确认切换备用模型。
若供应商违反提示约定，在普通正文后输出追问标记，或把协议字段的下划线转义为 `\_`，
服务端会在跨流式分块的情况下识别并截住内部 JSON，最终仅返回经过结构校验的追问卡。
消息历史读取使用同一兼容解析，因此已保存的这类旧输出也不会继续展示原始协议内容。

模型调用使用 `AI_TIMEOUT_SECONDS` 控制响应超时。后端区分超时、连接失败、供应商
繁忙和普通供应商错误，并返回稳定错误码。若当前模型尚未输出正文，前端提示用户
确认切换到下一个已配置模型，并直接重试同一次回答，不重复保存用户问题；若已有
部分正文，则保留中断内容并提示用户手动切换模型后重新提问。

创建请求编号按用户唯一，消息请求编号按会话唯一。同一请求编号、相同正文重试
返回已有记录；同一消息编号更换正文返回 409。发送、AI 回答保存与删除使用会话行锁。
首次消息前 40 字生成标题。标题、正文使用现有字段密钥加密，数据库保存密文。

前端首次发送创建会话，保存用户问题后开始逐字展示 AI 回答；生成完成后使用
/app/consultations/{id} 地址，刷新可恢复用户和助手消息。
保存失败保留输入及请求编号，可重试；草稿仅在内存，刷新会丢失尚未保存的输入。
历史支持分页及删除确认；退出清空前端列表，不删除数据库记录。

部署或本地更新前，在 backend 目录执行：

```powershell
docker compose up -d
.\.venv\Scripts\alembic.exe upgrade head
```

最新迁移版本：20260916_0012。无需重新创建数据库或删除数据卷。

## 模型配置

后端使用 OpenAI 兼容的 `/chat/completions` 流式协议。模型 ID 固定在服务端
白名单中，前端不能指定任意外部模型。在 `.env` 设置实际使用供应商的密钥：

```dotenv
DEEPSEEK_API_KEY=模型服务密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
QWEN_API_KEY=模型服务密钥
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
KIMI_API_KEY=模型服务密钥
KIMI_BASE_URL=https://api.moonshot.cn/v1
ZHIPUAI_API_KEY=模型服务密钥
ZHIPUAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
AI_TIMEOUT_SECONDS=90
```

当前注册模型：`deepseek-v4-flash`、`qwen3.8-flash`、`kimi-k2.6`、`glm-5.2`。
模型列表只返回已配置供应商下的模型。此前实测异常的 `glm-4.7-flash`、SiliconFlow
Qwen 和 Ling 已从可选白名单移除。百炼基础地址必须与 API Key
所在地域或业务空间的 API Host 匹配。修改配置后重启 Uvicorn。密钥只放在后端 `.env`，
不得写入前端或提交仓库。
