# AI 医学科普配图

## 边界

第一版只在已完成的医疗回答下由用户明确点击生成一张科普示意图。它不是诊断、检查结果、
处方或治疗方案；不支持通用文生图、图片编辑、参考图、多图融合、真实医学影像、医疗文件
仿造或个体化病灶。文字回答不等待图片任务。

后端固定使用服务端阿里云百炼凭据和 `wan2.6-t2i` 原生异步 API，不读取用户在设置页填写的
聊天模型 Key。创建请求固定 `n=1` 和 `watermark=false`，因此成品像素内不包含供应商叠加的
“AI生成”水印文字；前端必须在图片外持续显示“AI 生成·科普示意，不作为诊断依据”。
规范化 WebP 仍包含 AIGC 隐式元数据，不等于未标识内容。

## 配置

必需：`IMAGE_GENERATION_BASE_URL`（业务空间原生 `/api/v1` 地址）以及
`IMAGE_GENERATION_API_KEY`；后者留空时回落服务端 `QWEN_API_KEY`。地址不能使用
`/compatible-mode/v1`。其余默认值见 `.env.example`。

## 状态与可靠性

1. POST 先在数据库写入带幂等键的本地任务，再调用供应商创建接口。
2. 创建超时不自动重试，因为无法确认供应商是否已经计费；该本地任务标记失败。
3. GET 在到达 `next_poll_at` 后机会式轮询。部署还必须每分钟执行恢复 CLI，避免用户离开页面后
   任务无人推进：

```powershell
.venv\Scripts\python.exe -m app.image_generation_cli
```

4. 供应商成功后，结果 URL 只在内存中短暂存在。服务端校验 URL、DNS、大小、真实图片与像素，
   移除源元数据后重编码 WebP，只写入规范化 AIGC 隐式标识（生成属性、服务提供者编码、内容编号），
   再以 `generated-image-v1` AAD 加密落盘，随后清除供应商任务 ID。
5. 结果默认保留 90 天。CLI 同时清理过期成品；删除任务、会话或账号均使用
   `image_deletion_jobs` 持久化物理删除，失败可重试。

## 隐私与日志

用户提示词先去空白、直接身份信息脱敏，再放入固定的“不可信主题数据”安全模板。数据库只保存
实际外发提示词的 Fernet 密文。日志和 API 响应不得包含提示词、供应商任务 ID、供应商 URL、
图片字节、Base64、密钥或供应商响应正文。

每次鉴权读取成品时，服务端按“内容编号 + 不可逆接收者指纹”幂等记录提供时间、来源会话和
至少 183 天留存截止时间。该最小化留痕不保存用户明文身份，且不随图片、会话或账号删除而删除。
响应中的 `contentId` 是对应内容编号。

## 稳定错误码

- `IMAGE_GENERATION_NOTICE_REQUIRED`
- `IMAGE_GENERATION_PROMPT_INVALID`
- `IMAGE_GENERATION_SOURCE_INVALID`
- `IMAGE_GENERATION_ACTIVE`
- `IMAGE_GENERATION_NOT_READY`
- `IMAGE_GENERATION_RATE_LIMITED`
- `IMAGE_GENERATION_PROVIDER_REJECTED`
- `IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE`
- `IMAGE_GENERATION_PROVIDER_UNAVAILABLE`
- `IMAGE_GENERATION_PROVIDER_TIMEOUT`
- `IMAGE_GENERATION_NOT_CONFIGURED`
- `IMAGE_GENERATION_NOT_FOUND`
- `GENERATED_IMAGE_EXPIRED`

不存在与跨用户访问都统一为 404。供应商原始错误不透传给前端。

## 验收

自动化覆盖幂等、用户隔离、同一用户活动任务限制、安全提示词拒绝、无水印参数、AIGC 隐式
元数据、加密保存、鉴权读取与六个月留痕、列表恢复、删除和私网 URL 拒绝。真实调用会产生费用，只有用户再次明确同意后才使用
无身份信息的合成提示词执行。
