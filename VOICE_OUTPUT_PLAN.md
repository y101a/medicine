# 语音输出（TTS）并行实施方案

> 状态：后端已实现并通过自动化测试；DSH 前端并行实现中；真实付费 TTS 尚未联调
>
> 日期：2026-10-01
>
> 范围：把已经生成并保存的 AI 文字回答转换为可播放语音；不改变医疗回答、检索、红旗分流或健康记录逻辑。

## 0. 结论先行

当前项目已经有“麦克风录音 → 服务端转文字 → 写回输入框”的语音输入，但没有语音合成接口、音频播放器、语音输出意图，也没有语音对话模式。

第一版按下面的最小闭环实现：

1. **文字回答永远是主结果**。先保存并显示完整文字，再按需生成语音；TTS 失败不得影响文字回答。
2. 每条已完成的 AI 回答提供“朗读”入口；用户直接说“请用语音回答”时，回答完成后自动朗读。
3. 增加用户主动开启的“语音对话模式”：继续复用现有麦克风转写；每次 AI 文字回答完成后自动朗读。第一版不是持续监听，也不是全双工实时通话。
4. 后端使用服务端统一配置的阿里云百炼 `qwen-audio-3.1-tts-flash`，前端不接触 API Key，也不允许用户传任意模型、音色或指令。
5. 第一版只生成临时 MP3：后端不落盘、不入数据库、不把供应商临时 URL 返回给浏览器；响应结束即丢弃字节，前端 Object URL 在停止、切会话和卸载时释放。
6. 普通话默认音色为 `yuxiaoyun_v3.1`；方言只开放官方已确认兼容的白名单。首版支持普通话、上海话、广东话、东北话、重庆话、陕西话、云南话、宁波话、甘肃话。
7. 本方案不要求新表或迁移；如以后需要跨刷新重播、历史音频或离线下载，再单独设计加密存储和保留期。

## 1. 已有能力与缺口

### 1.1 已实现，可直接复用

- `frontend/src/api/voice.ts`：已有 multipart 语音转写请求。
- `frontend/src/composables/useVoiceRecorder.ts`：已有浏览器麦克风授权、录音状态机、最长 60 秒限制和转写结果写回草稿。
- `backend/app/api/routes/voice.py`、`backend/app/services/voice_transcription.py`：已有登录鉴权、真实格式校验、服务端百炼配置、受控错误和音频不落盘原则。
- 咨询主链路已有流式文字回答、消息持久化、停止生成、切换会话与历史恢复。
- 前端已有统一错误净化逻辑，服务端异常详情不能直接显示给用户。

### 1.2 尚未实现

- 没有文本转语音（TTS）供应商封装和 API。
- 没有朗读按钮、播放器、播放/暂停/停止状态。
- 没有“请用语音回答”的确定性意图识别。
- 没有语音对话模式和自动播放规则。
- 没有音色/方言白名单、费用限流、TTS 审计与专项测试。

### 1.3 不应误认成现有能力

- 历史草稿或旧原型中出现的 `edge-tts`、Neo4j 或浏览器 `speechSynthesis` 不代表当前项目已实现语音输出。
- 当前语音输入只做 ASR，不会自动产生音频回答。
- 当前多轮历史传给大模型的是文字消息；TTS 不需要也不应把音频重新塞回模型上下文。

## 2. 产品行为冻结

### 2.1 三种触发方式

| 触发方式 | 行为 | 是否自动播放 |
| --- | --- | --- |
| 用户点击某条 AI 消息的“朗读” | 朗读该条已完成文字回答 | 是，点击本身是用户手势 |
| 用户明确说“请用语音回答/读出来/用粤语回答”等 | 照常生成和保存文字，流结束后请求该回答的语音 | 是 |
| 用户主动开启“语音对话模式” | 继续用现有麦克风输入；每条新 AI 回答完成后请求语音 | 是；若浏览器拦截则显示“点此播放” |

以下内容不触发语音输出：

- “你支持语音吗”“如何使用语音输出”等功能询问；
- “不要朗读”“只要文字”；
- 尚未完成、已停止且为空、属于用户自己的消息；
- 图片/PPT/Word 生成任务卡本身；任务完成后仍只播报旁边真实存在的 AI 文字说明。

### 2.2 文字优先与医疗安全

- 红旗预检、就医分级、引用核验和免责声明仍在原文字链路完成，TTS 不参与医学判断。
- 文字一旦保存就立即可见，不能等待 TTS。
- 朗读内容必须保留紧急提醒和“仅供健康科普参考”等免责声明。
- 不能朗读隐藏系统提示、模型上下文、健康记录、附件提取原文、内部错误、密钥、供应商响应或审计数据。
- 音频内容由服务端根据数据库中的助手消息重新取得；客户端不能提交任意待朗读长文本。
- 同一时间只播放一段；新播放开始前停止旧音频。

### 2.3 语音对话模式边界

第一版定义为“按键录音 + 自动播报”，不是持续监听：

1. 用户点击开启模式；这一步建立浏览器允许播放声音所需的用户手势。
2. 用户仍点击麦克风开始和结束录音，转写文本仍先出现在输入框，可修改后发送。
3. AI 文字回答完成后自动播报。
4. 播放期间点击麦克风时，先停止播放，避免扬声器声音被重新录入。
5. 切换会话、退出登录、停止生成或关闭模式时立即停止并释放当前音频。

持续监听、打断式对话、WebSocket 实时双工、回声消除调优属于后续独立项目，不纳入本版。

## 3. 音色与方言白名单

### 3.1 前端只认识稳定的产品枚举

前端传 `speechPreset`，不传供应商 `voice` 或自由文本 `instruction`：

| `speechPreset` | 展示名 | 后端 voice | 后端 instruction |
| --- | --- | --- | --- |
| `mandarin_female` | 普通话·自然女声 | `yuxiaoyun_v3.1` | 空 |
| `mandarin_male` | 普通话·自然男声 | `anmingyuan_v3.1` | 空 |
| `shanghai` | 上海话 | `longanlingxin_v3.1` | `请用上海话自然、清晰地表达` |
| `cantonese` | 广东话 | `longanhuan_v3.1` | `请用广东话自然、清晰地表达` |
| `northeast` | 东北话 | `longanfengyue_v3.1` | `请用东北话自然、清晰地表达` |
| `chongqing` | 重庆话 | `longanhuan_v3.1` | `请用重庆话自然、清晰地表达` |
| `shaanxi` | 陕西话 | `longanlingxin_v3.1` | `请用陕西话自然、清晰地表达` |
| `yunnan` | 云南话 | `longanlingxin_v3.1` | `请用云南话自然、清晰地表达` |
| `ningbo` | 宁波话 | `longanhuan_v3.1` | `请用宁波话自然、清晰地表达` |
| `gansu` | 甘肃话 | `xunanchuan_v3.1` | `请用甘肃话自然、清晰地表达` |

映射全部由后端常量维护。供应商升级时可以换实际 voice，但不得悄悄改变产品枚举含义。

### 3.2 明确不开放的能力

- 不允许客户端传任意 voice id、prompt、instruction、情绪标签或声音复刻 id。
- 不做用户声音克隆、上传参考音频或“模仿某个人”。
- 不承诺四川话、河南话等未列入首版系统音色兼容表的方言；需要时先做真实试听评测再扩白名单。
- 医疗科普默认语气固定为自然、清晰、克制；不开放恐吓、哭喊、角色扮演等风格。

## 4. 服务端 API 契约

所有路径以 `/api/v1` 为前缀，要求登录态和消息归属校验。

### 4.1 获取可用预设

`GET /speech/presets`

响应 200：

```json
{
  "default": "mandarin_female",
  "items": [
    {
      "id": "mandarin_female",
      "label": "普通话·自然女声",
      "language": "zh-CN",
      "dialect": null
    },
    {
      "id": "cantonese",
      "label": "广东话",
      "language": "zh-CN",
      "dialect": "cantonese"
    }
  ]
}
```

响应只返回产品字段，不暴露模型、供应商地址或 instruction。

### 4.2 合成一条助手消息

`POST /consultations/{consultationId}/messages/{messageId}/speech`

请求 JSON：

```json
{
  "speechPreset": "mandarin_female",
  "rate": 1.0
}
```

约束：

- `messageId` 必须属于当前用户和路径中的会话；
- 消息角色必须是 `assistant`，内容非空且已经保存；
- `speechPreset` 必须在服务端白名单；
- `rate` 仅允许 `0.8`、`1.0`、`1.2`，默认 `1.0`；
- 服务端清洗后的文本最多 4000 个 Unicode 字符；超限提示用户分段朗读，不自动截断关键安全内容；
- 生成格式固定 MP3、24 kHz，启用供应商 AIGC 标识能力。

成功响应 200：

- `Content-Type: audio/mpeg`
- `Cache-Control: no-store`
- `Content-Disposition: inline; filename="assistant-speech.mp3"`
- 可选诊断头：`X-Speech-Preset`、`X-Request-Id`，不得含用户文本。

前端用 `response.blob()` 播放。响应是一次性临时结果，不保证刷新后仍可用。

### 4.3 语音输出意图

后端对用户消息做确定性识别，不交给大模型自由决定是否产生费用。创建用户消息的既有响应增加可选字段：

```json
{
  "speechOutputIntent": {
    "requested": true,
    "speechPreset": "cantonese"
  }
}
```

规则：

- 必须同时命中明确的输出动作（“用语音回答/朗读/读出来/播报”）和当前回答语境；
- “用粤语回答”这类明确方言表达可直接视为语音请求；
- 否定词优先；功能询问、引用示例和假设句不触发；
- 不识别出方言时用用户当前选择的预设，仍没有则用后端默认普通话；
- 前端只消费后端结果，不另写一套会漂移的正则。

建议放在 `MessageOut` 的用户消息上，而不是流式 `done` 事件：消息保存成功时结果已经确定，刷新或流式重连不改变意图。

### 4.4 错误契约

沿用项目统一错误形状，至少包含下列 code：

| HTTP | code | 用户文案 |
| --- | --- | --- |
| 404 | `SPEECH_MESSAGE_NOT_FOUND` | 没有找到可朗读的回答 |
| 409 | `SPEECH_MESSAGE_NOT_READY` | 回答尚未完成，请稍后再试 |
| 422 | `SPEECH_MESSAGE_UNSUPPORTED` | 这条内容暂时无法朗读 |
| 422 | `SPEECH_PRESET_UNSUPPORTED` | 暂不支持这个音色或方言 |
| 422 | `SPEECH_TEXT_TOO_LONG` | 内容较长，请分段朗读 |
| 429 | `SPEECH_RATE_LIMITED` | 语音生成过于频繁，请稍后再试 |
| 502 | `SPEECH_SERVICE_UNAVAILABLE` | 语音服务暂时不可用，请稍后再试 |
| 504 | `SPEECH_SERVICE_TIMEOUT` | 语音生成超时，请稍后再试 |

错误响应不能把供应商原文、URL、请求体或用户医疗内容透传到前端。

## 5. 后端实现清单（Codex）

建议文件：

- `backend/app/core/config.py`：新增 `tts_api_key`、`tts_base_url`、`tts_model`、`tts_timeout_seconds`、`tts_max_text_chars`、限流配置；Key 默认可回落服务端 `qwen_api_key`，地址不能回落 OpenAI compatible base URL。
- `backend/.env.example`：只增加变量名和占位符，不写真实 workspace 或密钥。
- `backend/app/schemas/speech.py`：预设、请求和列表响应。
- `backend/app/services/speech_intent.py`：确定性自然语言触发与否定/功能询问规则。
- `backend/app/services/speech_text.py`：从助手消息生成朗读文本。
- `backend/app/services/speech_synthesis.py`：白名单映射、百炼 HTTP 调用、超时、响应校验和 MP3 返回。
- `backend/app/api/routes/speech.py`：两个 API、鉴权、归属、限流与审计。
- `backend/app/api/router.py`：挂载路由。
- `backend/app/schemas/consultations.py` 与创建消息链路：返回 `speechOutputIntent`。
- `backend/tests/test_speech_output.py`：专项测试。
- `backend/docs/API.md`：最终契约。

### 5.1 朗读文本清洗

`prepare_speech_text()` 只处理已保存助手正文：

- Markdown 标题转为普通短句；列表项之间加入自然停顿；
- 删除代码围栏、裸 URL、Markdown 链接地址，但保留链接文字；
- 删除 `[来源1]` 这类引用标记和单独的来源 URL 列表；
- 保留剂量、时间、单位、警示和免责声明，不做医学摘要或改写；
- 忽略 HTML、隐藏元数据和不可见控制字符；
- 清洗后为空则返回 `SPEECH_MESSAGE_UNSUPPORTED`；
- 超过 4000 字符则明确拒绝，不静默截断。

### 5.2 供应商调用

- 固定北京地域 workspace 专属 HTTP endpoint；只允许 HTTPS。
- 固定模型 `qwen-audio-3.1-tts-flash`，白名单选择 voice/instruction。
- 第一版用非流式 HTTP：拿到供应商临时 URL 后，由后端立即下载并验证，再以 `audio/mpeg` 转发；浏览器不能直连临时 URL。
- 只允许官方供应商域名，禁重定向，限制下载体积与总超时，防止 SSRF 和内存失控。
- 供应商 URL 官方说明只在 24 小时内有效，因此不能当成项目持久资源。
- 不记录请求正文、音频字节、供应商 URL、API Key 或完整异常体。

### 5.3 限流和审计

- 首版建议：每用户每 10 分钟最多 10 次、每天最多 50 次；具体值由配置控制。
- 限流必须是多 worker 共享口径，不能只用进程内 `dict`。优先复用数据库审计记录按用户计数；如性能不足再设计 Redis，不为本版新增常驻服务。
- 审计只记录 `user_id`、`message_id`、preset、字符数、结果码、耗时和 request id；不记录文本和音频。
- 同一用户同一消息同时只允许一个正在进行的合成；重复请求返回 409 或复用正在进行的请求，不能并发重复计费。

### 5.4 后端测试最低集

- 预设列表不暴露 voice、模型、instruction 或 Key。
- 本人已完成助手消息可合成；用户消息、空消息、未完成消息拒绝。
- 跨用户和跨会话 message id 一律按 404 处理，不泄露存在性。
- 任意客户端文本、voice、instruction 字段无法进入供应商请求。
- Markdown/来源清洗正确，免责声明和紧急提醒保留，超长不截断。
- 方言枚举逐一映射到兼容 voice；未知枚举 422。
- 供应商超时、非 2xx、空 URL、非法域名、重定向、过大音频、错误 MIME 都映射成受控错误。
- 限流、多请求互斥和审计覆盖。
- 断言不落盘、不建表、不把文本/音频/临时 URL 写日志。
- `speechOutputIntent` 覆盖明确命中、否定、功能询问、引用句和各方言表达。

## 6. 前端实现清单（DSH）

建议文件：

- `frontend/src/types/speech.ts`：预设、播放状态、错误类型。
- `frontend/src/api/speech.ts`：获取预设、鉴权 Blob 请求、错误净化。
- `frontend/src/composables/useSpeechOutput.ts`：每会话单播放器、AbortController、Object URL 生命周期、自动播放回退。
- `frontend/src/components/MessageSpeechControl.vue`：朗读/暂停/继续/停止按钮和可访问状态。
- `frontend/src/views/HomeView.vue`：助手消息接线、自然语言意图、语音模式与切会话清理。
- `frontend/src/types/consultations.ts`：增加可选 `speechOutputIntent`。
- `frontend/src/stores/composerHints.ts` 或独立 store：保存用户选择的 preset、rate 和语音模式；不得保存音频 Blob。
- 前端 Vitest、Playwright 与 `frontend/BROWSER_ACCEPTANCE.md`。

### 6.1 状态机

单一全局播放器状态：

`idle -> loading -> playing <-> paused -> idle`

任何阶段都可进入 `error`，显示受控短句后回到 `idle`。新播放、切会话、退出登录、组件卸载时：

1. abort 未完成请求；
2. pause 当前 audio；
3. 清空 `src`；
4. `URL.revokeObjectURL()`；
5. 清空当前 message id。

### 6.2 交互要求

- 只在助手消息完成后显示朗读入口；用户消息无入口。
- 正在请求时按钮显示“正在生成语音”，可取消；不能重复点击产生并行请求。
- 播放时显示“暂停”和“停止”；暂停后显示“继续”。
- 错误只影响该条消息，文字、引用和其他功能保持可用。
- 自动播放被浏览器拦截时，不报系统错误，改成明显的“语音已生成，点击播放”。
- 尊重 `prefers-reduced-motion`；状态区域使用 `role=status` 与 `aria-live=polite`，不要连续播报播放秒数。
- 窄屏仍按项目 ADR-011 给宽屏提示，本功能不单独扩大移动端范围。

### 6.3 语音模式与偏好

- 模式开关必须由用户主动点击；默认关闭。
- 预设与语速可保存在本地偏好；语音模式是否跨刷新保持，建议首版只保留到当前标签页，避免公共电脑突然出声。
- 用户明确请求某方言时，本轮覆盖偏好但不永久改默认。
- 自动播放前若用户已离开当前会话，只生成也不播放，或直接取消请求；不得在另一会话突然发声。
- 语音播放时开始录音，要先停止播放。

### 6.4 前端测试最低集

- 已完成助手消息有朗读入口，用户/未完成消息没有。
- Blob 请求携带鉴权并创建 Object URL；停止、切会话、卸载均 revoke。
- loading 期间禁止重复请求；新消息播放会停止旧消息。
- 播放/暂停/继续/停止状态与 aria 文案正确。
- 自然语言 `speechOutputIntent` 命中后，先完成文字流再自动请求音频。
- 语音模式关闭时不自动播；开启后自动播；浏览器拒绝 autoplay 时降级为点击播放。
- 方言与语速只发产品枚举；不能注入 voice/instruction。
- 429/502/504 和网络取消显示受控中文，不泄露 JSON/HTML。
- 开麦克风会停止扬声器播放。
- Playwright 覆盖刷新、切会话、窄屏提示和自动播放失败降级；接口先用 `page.route` 打桩，真实联调必须单独标注。

## 7. 并行开发顺序

### 阶段 A：冻结契约（本文件）

- Codex 与 DSH 共同以第 3、4 节为准。
- 若路径、字段、错误码或枚举要改，先更新本文件和 `COORDINATION.md`，再改代码。

### 阶段 B：可并行开工

Codex：

1. 配置、schema、文本清洗、意图识别；
2. 供应商 adapter 与 `/speech/presets`、消息语音接口；
3. 专项测试和 API 文档。

DSH：

1. 按冻结接口写 types/API/composable；
2. 用接口桩完成消息控制和语音模式；
3. Vitest/Playwright/验收文档。

并行期间 DSH 不改 `backend/**`，Codex 不改 `frontend/**`。`HomeView.vue` 当前已有 DSH 在途改动，Codex 禁止触碰。

### 阶段 C：真实联调

1. 后端先完成无付费 mock 测试并释放文件占用。
2. 使用不含真实个人健康信息的固定短句，真实调用普通话、男声和至少两种方言各一次。
3. DSH 用真实后端验证 Blob 播放、取消、切会话和自动播放降级。
4. 记录真实延迟、音频大小、失败码和费用调用次数；不保存音频样例到仓库。

## 8. 验收标准

全部满足才可宣称“语音输出已实现”：

- 文字回答始终先显示；TTS 故障不影响对话。
- 朗读、暂停、继续、停止和第二条消息抢占播放均可用。
- “请用语音回答”会在文字完成后自动播放；“你支持语音吗”不会误触发。
- 语音对话模式可主动开关，复用现有麦克风输入且不会把扬声器声音继续录入。
- 普通话和白名单方言完成真实试听；未试听的方言不能宣称可用。
- 跨用户消息不可合成；客户端不能让服务端朗读任意文本或注入供应商参数。
- 音频、朗读文本、临时 URL、密钥均不落日志；后端不落盘、不入库。
- 限流、超时、取消、浏览器自动播放限制都有受控降级。
- 后端 Ruff/pytest、前端 build/Vitest/Playwright 通过；真实联调与接口桩结果分开记录。

## 9. 后续版本，当前不做

- 跨刷新重播、历史音频、下载音频；
- 用户自定义声音、声音复刻和任意情绪指令；
- WebSocket 实时流式播放与全双工语音对话；
- 把音频当作对话历史重新输入模型；
- 为 PPT、Word 或图片生成任务制作旁白；
- 自动把健康记录“定期播报”给用户。

## 10. 官方依据与需复核项

方案于 2026-10-01 依据阿里云百炼官方文档核对：

- [非实时语音合成](https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide)：Qwen-Audio-TTS 的 HTTP endpoint、非流式 URL 24 小时有效、流式输出和方言指令说明。
- [qwen-audio-3.1-tts-flash 模型信息](https://help.aliyun.com/zh/model-studio/qwen-audio-3-1-tts-flash)：文本输入、音频输出、HTTP/WebSocket、北京地域和 RPS 说明。
- [Qwen-Audio-TTS 音色列表](https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list)：模型与 voice 不可跨用、首版四个多语种/方言音色及八种方言范围。

供应商模型、音色、价格、限流和字段可能变化。实施和上线前必须再次查官方文档并做真实短句烟测；代码中的模型与映射必须由服务端配置/白名单控制，不能把本文当成永久不变的供应商事实。

## 11. 2026-10-01 实施记录

Codex 后端已完成：

- `GET /api/v1/speech/presets` 与 `POST /api/v1/consultations/{consultationId}/messages/{messageId}/speech`；
- `MessageOut.speechOutputIntent` 的确定性识别；
- 十种产品预设、百炼原生 TTS 请求、AIGC 隐性标识和临时 OSS 音频的 HTTPS 代理校验；
- Markdown/代码块/URL/引用标记清洗，保留紧急提醒和免责声明；
- 当前用户/会话/消息归属校验、数据库共享限额、同消息并发锁和最小化审计；
- 23 项语音输出专项测试；完整后端测试由 470 项增加到 493 项，Ruff 全绿。

本轮没有调用真实付费 TTS，没有保存音频或供应商临时 URL，也没有新增迁移。真实普通话、男女声和方言试听仍属于阶段 C，完成前不得宣称真实语音质量已经验收。
