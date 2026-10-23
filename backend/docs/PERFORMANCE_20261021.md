# 本地性能测试准备与环境阻塞记录（2026-10-21）

> 后续状态：Docker 已恢复，用户提供的五接口并发 30 压测结果已核验并归档，见
> [核验报告](PERFORMANCE_20261021_VERIFIED.md)。下方“尚未产生”等为此前准备阶段的历史状态，
> 不再代表本项目没有性能结果；本报告准备的独立夹具/驱动仍未执行真实负载。

## 当前结论

**尚未产生业务接口的 P50/P95/P99 或 QPS 实测结果。**
本轮已完成压测工具与统计逻辑的离线验证，不能把这些验证当作项目性能测试。

### 已确认的环境信息

- 本机 Intel Core i7-14650HX，24 个逻辑处理器，约 15.8 GiB 物理内存。
- 原普通命令失败来自 Codex Windows 沙箱初始化：给
  `D:\medicine and mannagement system` 添加写入 ACE 时 `WRITE_DAC` 被拒绝，错误码 5。
  通过批准后的沙箱外执行可运行命令；中断恢复后普通 `Get-Location` 也已运行成功。
  本轮未修改文件系统 ACL 或 Codex 配置，不能声称已永久修复原 ACL 问题。
- 用户已批准启动 Docker Desktop 和创建本地隔离压测环境；实际尝试启动后，
  Docker 日志报告 `hasNoVirtualization=true`、`docker=stopped`。
- `VirtualizationFirmwareEnabled=true`，`HypervisorPresent=false`；无法据此认定 BIOS 关闭。
  普通用户读取 Windows 可选组件和 BCD 配置时被拒绝，需要管理员诊断才能确定修复方法。
- 恢复后复查时 Docker 进程已不在运行、引擎命名管道不存在，未创建压测容器或业务数据。
- 当前仓库可见文档/代码未找到有效的既有 P50/P95/P99/QPS 报告；这不证明其他历史聊天未安排过测试。

### 管理员只读诊断补充（20:56，UTC+8）

用户批准 UAC 后执行已准备的诊断脚本，结果保存在
`data/perf-admin-diagnostics-20261021-01.json`。
`VirtualMachinePlatform=Enabled`、`Microsoft-Windows-Subsystem-Linux=Enabled`，
固件虚拟化为 true，但当前 Windows 启动项明确为 `hypervisorlaunchtype Off`。
该配置阻止虚拟机监控程序启动，与 Docker 当前虚拟化不可用的现象一致。
待用户批准后可执行 `bcdedit /set hypervisorlaunchtype auto`，原值 Off 已记录；
需要用户保存工作并重启 Windows 后再核实 Docker。此诊断没有修改 BCD 或重启系统。
恢复原设置的命令为 `bcdedit /set hypervisorlaunchtype off`（同样需要管理员与重启）。

### 已授权修复（20:58，UTC+8）

用户明确同意只修改这一项、不自动重启后，执行
`scripts/performance_enable_hypervisor.ps1`。
`bcdedit /set hypervisorlaunchtype auto` 返回退出码 0，读回当前启动项确认为
`hypervisorlaunchtype Auto`，`restartPerformed=false`。
审计结果：`data/perf-hypervisor-change-20261021-01.json`。
**当前等待用户保存工作并手动重启 Windows。** 重启后先核对
`HypervisorPresent=true` 与 Docker 引擎可用，再启动隔离库并执行上述业务 API 压测。
BCD 修改成功不等于 Docker 已恢复，更不等于性能测试通过。

## 已准备的工具

- `scripts/performance_load.py`：真实 loopback HTTP 请求；并发 1/4/8/16/32/64，
  默认每档预热 5 秒、测量 30 秒、重复 2 次。请求超时 30 秒，不重试，不跟随重定向。
- 每档输出成功请求 P50/P95/P99、全部尝试延迟分位数、成功 QPS、完成 QPS、
  状态码分布、错误率和原始请求耗时。分位数用 nearest-rank，QPS 分母含本档请求完成的排空时间。
  预热请求不进入测量结果，但写入预热会保留于隔离库。
- 响应除了状态码还检查业务内容；列表为空、鉴权失败、错误页、超时不计成功 QPS。
  预热失败即停止；测量错误率超过 5% 时停止增加负载。成功样本不足 1000 时标注 P99 样本量提醒。
- `scripts/performance_fixture.py`：仅操作 loopback:55433 的 `medical_assistant_perf`。
  种子阶段要求无用户，默认生成 64 名合成用户、704 个会话、6400 条加密消息，
  另导入当前公开原型语料；最终语料文档/块数由成功入库后统计，当前尚未入库。
  JWT 和加密使用公开测试专用值，不读取真实用户数据。夹具含测试 cookie，应保留在忽略的 `data/`。
- `compose.perf.yaml`：独立容器/项目，不挂载正式数据卷；数据库使用 tmpfs，重启/停止可能丢失数据。
  禁止自动拉取镜像，不设置自启动。尚未确认宿主机当前镜像是否可用，因为引擎不可用。
- `scripts/performance_admin_diagnostics.ps1`：需管理员的只读诊断；写出组件状态、
  Hypervisor 状态和 BCD 信息，不修改系统，不重启，不覆盖已有输出。

## 测量范围和限制

默认场景为 `GET /users/me`、`GET /consultations`、`GET /consultations/{id}/messages`，
包含真实 JWT 鉴权、数据库查询、序列化，涉及加密字段的路径也包含解密。
可选 `triage_write` 为真实 `POST /consultations/{id}/messages`，测试确定性红旗预检、
加密及事务写入；合成问题已离线确认触发 `emergency`。每并发 worker 使用独立合成用户。

临时后端单进程、关闭 MCP/新闻刷新/后台健康抽取，清空四家模型凭据。
未替换业务路由、数据库会话、认证或 SQL。客户端和后端同机运行，客户端开销会影响吞吐。
只测试已列出的本地业务 API；不测试外部 Embedding、真实模型生成、AI 首字延迟或完整回答耗时。
检索数据即使已导入也没有向量化，不能据此声称测过完整混合 RAG。

这是无思考时间的闭环并发扫描。最高成功 QPS 只能称为该配置与该工作负载下的观测吞吐，
不能直接声称生产最大容量；“能抗多少 QPS”还需确定可接受的 P99/错误率，
在固定到达率、足够持续时间和代表性数据规模下再次验证。不能把各接口 QPS 相加。

## 环境恢复后执行（从 backend 目录）

先确认 Docker 引擎可用且本机已有所需镜像。以下命令不安装依赖或拉取镜像。
数据库停启、进程启动/停止应遵循用户已确认的权限；不要操作正式数据库。

```powershell
docker compose -f compose.perf.yaml up -d --pull never --wait
.\.venv-codex\Scripts\python.exe scripts/performance_fixture.py migrate
.\.venv-codex\Scripts\python.exe scripts/performance_fixture.py seed --output data/perf-fixture-20261021.json
```

在一个由用户/项目显式启动的前台终端运行后端，结束后 Ctrl+C，不设置常驻或自启动：

```powershell
.\.venv-codex\Scripts\python.exe scripts/performance_fixture.py serve
```

在另一个终端运行负载；输出路径必须不存在（重复实验换新文件名）。

```powershell
.\.venv-codex\Scripts\python.exe scripts/performance_load.py --fixture data/perf-fixture-20261021.json --output data/perf-read-20261021.json
.\.venv-codex\Scripts\python.exe scripts/performance_load.py --fixture data/perf-fixture-20261021.json --output data/perf-write-20261021.json --scenarios triage_write
```

完整默认读扫描约 21 分钟（3 场景 × 6 并发档 × 2 次 × 35 秒，另有排空时间），
写入扫描约 7 分钟；环境恢复后先用 1 秒/单档执行冒烟，确认每个业务断言后再跑长测。
临时数据库没有真实用户或真实模型凭据，但测试参数仍应记录为合成数据。

## 本轮已执行验证

- `pytest tests/test_performance_load.py -q`：3 passed。
- Ruff 检查两份 Python 脚本和新增测试：通过。
- 宿主机通道复核：3 passed（0.12 秒）；PowerShell 管理员诊断脚本语法检查通过。
  恢复后的默认沙箱曾出现一次异步测试停滞，已停止本轮测试进程。
  后续正式压测应从宿主机终端启动服务和负载，避免把执行沙箱开销混进服务性能。
- 两份 Python 脚本 `--help`：通过。
- 红旗合成文本执行 `run_consultation_safety`：`emergency`。
- 数据库迁移、夹具入库、HTTP 接口压测：未执行，受 Docker/Hypervisor 阻塞。
- 当前无任何可写入简历的性能数字。
