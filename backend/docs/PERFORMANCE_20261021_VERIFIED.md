# 2026-10-21 五个核心 API 压测证据核验

> 后续：用户授权后已改进登录并完成本轮前后对照，见
> [登录改进报告](AUTH_ASYNC_IMPROVEMENT_20261021.md)。下方“尚未实施”为首次核验时的历史状态。

## 结论及状态

用户提供的 `%TEMP%\bench` 确有三份脚本和一份结果 JSON；本轮将四份文件原样复制到
`performance_20261021_evidence/`，没有覆盖 TEMP 中的原件，也没有重新执行负载。
**已经核实的是并发 30 的五个场景；并发 1/10 的原始结果未在该目录保留。**
结果文件采用 nearest-rank 分位数，单位毫秒；含 P50/P90/P99，没有 P95，
未保留逐请求耗时，无法据此补算准确 P95。

| 场景 | 并发 | 样本数 | P50 ms | P99 ms | RPS | HTTP 错误 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 登录 | 30 | 101 | 3378.6 | 7897.7 | 7.8 | 0 |
| 会话列表 | 30 | 757 | 356.1 | 1096.5 | 71.2 | 0 |
| 创建会话 | 30 | 656 | 399.8 | 1280.8 | 64.7 | 0 |
| 发送消息（不生成 AI 回答） | 30 | 507 | 376.9 | 2127.4 | 48.5 | 0 |
| 消息列表 | 30 | 511 | 539.0 | 1509.4 | 48.3 | 0 |

这是一次短时单 worker、同机、单合成账号的闭环测试。每场景顺序预热 20 次，
测量窗口约 10 秒，含排空总耗时为 10.14–13.00 秒。
RPS = 全部完成请求 / 含排空的总时长；这批状态码全部为 200/201，
所以本批 RPS 恰好也等于 HTTP 成功吞吐。
脚本仅验证 HTTP 状态码，没有逐请求校验业务响应内容；不能把“0 HTTP 错误”扩展成全部业务断言通过。
所有场景使用同一 httpx 客户端和 cookie，连接池上限取 httpx 默认值，未记录独立压测机数据。

## 本轮只读核实

Docker 已运行，宿主机 `HypervisorPresent=true`。正式 PostgreSQL 与临时 graph-eval
容器均存在。仅读取端口 55432 的 `medical_assistant_graph_eval`，得到：

| 项目 | 数量 |
| --- | ---: |
| consultations | 2726 |
| messages | 1335 |
| messages.triage_ciphertext 非空 | 265 |
| health_records | 0 |
| Alembic 版本 | 20261014_0032 |

这些是本轮核验时的隔离库快照，不是压测开始前的空库快照，不代表正式库数据量。
`20261014_0032` 是数据库迁移编号，不是 Git commit。
用户转述的“25 个文件未提交”未通过 Git 查询复核；本轮没有执行 Git 操作。

## 对原结论的修订

1. **登录存在同步 CPU 操作阻塞异步路径的问题，代码证据成立。**
   `app/services/auth.py::login_user` 是 async 函数，正常登录直接调用同步
   `verify_password`，不存在的账号分支直接调用同步 `hash_password`；
   `app/core/security.py` 内部直接执行 pwdlib 的密码哈希与校验，没有线程切换。
   所以该计算执行期间占用当前事件循环线程。当前实现还具有账号失败次数和锁定机制
   （5 次失败锁定 15 分钟），不能笼统说没有任何登录保护。
   尚未进行性能剖析或修复前后 A/B，不能断言所有排队都只由 Argon2 导致，
   也不能把“同步串行”理解为整个 HTTP 请求完全没有 I/O 并发。
2. **并发 10 是峰值、登录 P50 劣化 20 倍：目前仅有用户转述。**
   单份 `bench_result.json` 每次运行都会覆盖，只剩并发 30。
   可以记录用户提供的 1/10 档描述，但不能称为已核实的原始三档曲线。
   并发 30 的列表和创建 P99/P50 分别约 3.08/3.20，不是普遍 5–6 倍。
3. **48.5 RPS 是同账号、同会话的消息写入观测值，不是该接口的系统吞吐上限。**
   压测脚本把全部 worker 的消息发往同一 cid；`append_message` 在入口执行
   `owned(..., lock=True)`，内部使用 `SELECT FOR UPDATE` 串行化同会话写入。
   此锁用于保证消息序号和发送/删除一致性，不应为了压测去掉。
   要评估多用户总体吞吐，需要独立用户和独立会话场景；还需与同会话热点场景分别报告。
   本轮读到的 `append_message` 主要路径没有调用 conversation_memory 更新，
   不能将压缩记忆更新写成该场景的已核实耗时来源。
4. **红旗数据支持“预检路径被执行”，不等于红旗准确率验证。**
   265/1335 ≈ 19.85%，与约 1/5 的注入设计接近，不能说数学上恰好相等。
   三轮预热、各轮计数器和测试数据增量需保留逐请求记录后才能严格对账。
   聚合行数不是逐题真阳性/假阳性审计。
5. **成本证据应以受控路径和开关为主。**
   `bench_server.py` 明确关闭健康抽取和新闻自动刷新；负载脚本没有调用 `/stream`，
   所测登录、会话、消息本地路径未发现模型生成调用。
   `health_records=0` 是补充证据，单独不能证明从未发送过外部请求（失败调用也可能不落库）。
   本轮未查服务商账单或外连审计，不能称为账单级证明。

## 修复建议与验收（尚未实施）

- 将登录正常校验与不存在账号分支的密码计算移出事件循环；保留原有密码算法及强度。
  可使用受控线程池/`asyncio.to_thread`，但应限制同时进行的 Argon2 任务，
  避免并发数增加后 CPU、内存耗尽。注册/重置密码等调用也需审查。
- 限流需区分现有账号锁定与请求/IP 速率限制；后者涉及策略与多进程部署，不能靠
  一个未加边界的进程内字典宣称已经完成。
- 验收应包含事件循环响应性、密码正确/错误/不存在账号行为、原锁定语义，以及
  同配置/同工作负载的修复前后复测。线程池能改善事件循环响应性，吞吐提升幅度仍需实测。
- 在明确可接受的 P99/错误率前，表中 RPS 不能命名为生产最大 QPS。

## 保留每档结果的复跑方式

以下仅为复跑步骤，本轮未执行。复跑前确认没有另一方占用隔离库，
并确认正在使用临时 graph-eval 数据库，不能对正式库执行造号或迁移。
所需 Python 依赖已在现有 `.venv-codex`，不要额外安装或自动拉取镜像。

从 `backend` 目录打开一个前台终端，明确隔离数据库配置：

```powershell
$env:POSTGRES_HOST='127.0.0.1'
$env:POSTGRES_PORT='55432'
$env:POSTGRES_USER='graph_eval'
$env:POSTGRES_PASSWORD='graph-eval-local-only'
$env:POSTGRES_DB='medical_assistant_graph_eval'
$env:MCP_ENABLED='false'
$env:PYTHONPATH=(Get-Location).Path
.\.venv-codex\Scripts\python.exe docs/performance_20261021_evidence/bench_seed.py
.\.venv-codex\Scripts\python.exe docs/performance_20261021_evidence/bench_server.py
```

另一个终端从 `backend` 目录执行。每档单独复制脚本到新目录，防止原脚本固定输出名
覆盖前一档证据。每次实验使用新时间戳；服务退出后不得留下自动启动任务。

```powershell
$perfSource=Join-Path (Get-Location) 'docs/performance_20261021_evidence/bench_load.py'
$perfRunRoot=Join-Path (Get-Location) ('data/bench-replay-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
if(Test-Path -LiteralPath $perfRunRoot){throw 'Run directory already exists'}
New-Item -ItemType Directory -Path $perfRunRoot | Out-Null
foreach($perfConcurrency in @(1,10,30)) {
    $perfRun=Join-Path $perfRunRoot ('concurrency-'+$perfConcurrency)
    New-Item -ItemType Directory -Path $perfRun | Out-Null
    $perfLoad=Join-Path $perfRun 'bench_load.py'
    Copy-Item -LiteralPath $perfSource -Destination $perfLoad
    .\.venv-codex\Scripts\python.exe $perfLoad --concurrency $perfConcurrency --duration 30
}
```

该命令复现原负载定义，仍是同账号、同会话热点场景；不是多用户容量测试。
如需 P95 和原始逐请求记录，可使用/扩展 `scripts/performance_load.py`，
但新旧负载不同应分别报告，不能直接当成同条件 A/B。

## 归档 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| bench_load.py | 31b0a7f20e4416d82bb07e31c78ff19cce59b6c118e92601745af3bbbec98057 |
| bench_result.json | a57eb8dab6a5df42e2f61e89d923ffdd801a55fe0488b0e94cfcedbb929f10e6 |
| bench_seed.py | 95548c2ff45721b864131cdbf82368076480faf0f4f15873fc5b504eacb73c4a |
| bench_server.py | a8bee37dfa301cfa78308be29a29ff441bd27fa6e0fe6597c685d00f1402d040 |

## 简历口径

可写：“对 5 个核心 API 开展本地并发压测，记录延迟分位数与吞吐，
定位异步登录路径中的同步密码校验，以及同会话消息写入的锁竞争风险。”
只有保留三档原始数据并完成复核后，才写三档具体增减比例；
只有实施修复并通过同条件复测后，才写“已优化”或性能提升幅度。
