# PubMed 与高德 POI MCP（开发阶段）

## 当前状态

后端在 `APP_ENVIRONMENT=development` 且 `MCP_ENABLED=true` 时，将只读、无状态的
Streamable HTTP MCP 服务挂载在：

```text
http://127.0.0.1:8000/mcp/
```

生产环境始终不挂载该端点。服务使用 MCP Python SDK 2.x；FastAPI 每次启动都会创建
新的 MCP 会话管理器，兼容开发热重载和测试中的多次生命周期启动。

## 工具

### `search_pubmed`

- 输入：`topic`、`max_results`（1-10，默认 5）。
- `topic` 只能是本地固定白名单中的通用病名，患者原文、自由文本和身份信息会被拒绝。
- 中文白名单病名在本地映射为固定英文检索词，再调用 NCBI ESearch 和 EFetch。
- 输出 PMID、标题、摘要、期刊、发表时间、DOI 和 PubMed 固定链接。
- `PUBMED_API_KEY` 可选；建议设置 `PUBMED_TOOL_NAME` 与 `PUBMED_EMAIL` 以遵守 NCBI
  E-utilities 使用规范。

### `search_medical_pois`

- 输入：`city`、`department`、`max_results`（1-10，默认 5）。
- `city` 只允许 2-12 个中文字符或 6 位行政区编码；不接收详细地址。
- `department` 只能是本地通用科室白名单中的值。
- 不接收或发送用户坐标；高德响应中的 `location` 也不会返回给 MCP 调用方。
- 需要在本机 `.env` 设置 `AMAP_API_KEY`。缺少 Key 时返回 `AMAP_NOT_CONFIGURED`，
  不会产生伪造结果。

### `find_nearby_hospitals`

- 输入：`latitude`、`longitude`、`location_consent=true`、`route_mode` 和最多 3 条结果。
- 调用方必须先取得用户本次明确定位授权；缺少授权时服务端拒绝调用。
- 浏览器 GPS 坐标先转换为高德坐标，再做周边医院查询；名称不含“医院”的社区卫生
  服务站等候选会被排除。
- 最多比较 3 家医院的驾车或步行路线，并按预计路线时间排序。单条路线超时不会丢弃
  已找到的医院，而是明确降级为直线距离参考。
- 响应不包含用户起点坐标；服务端不把坐标写入数据库、业务日志或调用审计。

### `search_hospitals_by_area`

- 定位拒绝、不支持或失败时使用，仅接受城市、区县名称或 6 位行政区编码。
- 返回医院列表和高德导航 URI，但不声称能判断哪家医院最近。

登录用户前端通过 `/api/v1/navigation/nearby-hospitals` 和
`/api/v1/navigation/hospitals-by-area` 使用同一套受控适配器。咨询页会在用户点击后申请
一次浏览器定位权限；拒绝时自动切换区域查询。每个用户在单进程内限制为 10 分钟 6 次，
限流状态不包含坐标。

## 环境变量

```text
MCP_ENABLED=true
EXTERNAL_TOOL_TIMEOUT_SECONDS=10
PUBMED_API_KEY=
PUBMED_TOOL_NAME=medical_assistant
PUBMED_EMAIL=
AMAP_API_KEY=
```

密钥只保存在本机 `.env` 或正式密钥系统中，不得写入源码、日志、测试、截图或对话。

## 安全与产品边界

- 四个工具均声明为 MCP `readOnlyHint=true`、`destructiveHint=false`。
- 服务端日志只记录工具名、结果状态、耗时和结果数量，不记录参数、患者文本或供应商响应。
- PubMed 文献仍需人工筛选和医学审核，不能直接视为产品已批准知识。
- 高德 POI 可能过期，只能作就医查找线索；就诊前应向机构核实科室、时间和资质。
- “最近”不等于“最适合”；危急表现始终优先提示拨打 120，普通导航不能替代急救。
- 浏览器精确定位在生产环境需要 HTTPS；高德 URI 在部分内置浏览器或未安装高德 App
  的设备上可能无法直接进入实时导航。
- 当前仅完成 MCP 服务端和协议级调用，尚未让咨询 LangGraph 自动调用外部工具；自动调用前
  仍需设计明确触发、用户提示、结果引用和失败降级策略。

## 验证

```powershell
cd backend
.venv\Scripts\pytest.exe tests\test_mcp_tools.py -q
.venv\Scripts\pytest.exe -q
.venv\Scripts\ruff.exe check app tests
```

自动化测试中的高德请求使用模拟响应，不消耗配额。2026-09-16 已使用本机 Key 以
“北京市 + 内科”完成 1 次真实只读冒烟并返回 3 条 POI；这只证明当前 Key 与链路可用，
不代表长期配额或数据完整性。PubMed 可在不配置 API Key 时用固定白名单病名做低频真实
冒烟测试，但批量调用应配置 Key 并遵守 NCBI 频率限制。

导航链路另使用公开测试坐标验证了 GPS 转换、周边查询和路径接口：首次路径请求成功；
增加医院名称过滤后一次真实路径请求发生连接超时，因此实现了不重试、不丢弃医院候选的
直线距离降级。模拟测试覆盖完整成功、服务站排除和路径超时三种情况。
