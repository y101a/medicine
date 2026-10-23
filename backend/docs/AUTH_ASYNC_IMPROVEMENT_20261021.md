# 登录密码计算异步改进与前后对照（2026-10-21）

## 实现和验证状态

已实现并通过专项验证：登录正常密码校验与不存在账号的防枚举计算移出事件循环；
密码算法仍为原来的 Argon2id。`app/core/password_work.py` 通过 AnyIO 工作线程执行，
专用 CapacityLimiter 限制每个 worker 同时最多 2 项密码计算。
请求取消时不主动丢弃正在运行的线程，容量令牌在计算完成后释放。
这不是 IP/请求速率限制；多 worker 的总密码计算并行数会随 worker 数增加。

`login_user` 在异步校验后对凭据行 `refresh(..., with_for_update=True)`，
重新核对密码哈希与锁定状态，再更新计数和创建登录会话，避免并发失败覆盖计数。
若校验期间密码哈希已经变化，返回原有的通用 401，要求重新登录。
原有 5 次错误密码锁定 15 分钟、账号禁用、cookie 和刷新令牌语义保留。
注册/重置密码的同步计算没有在本次改动中一并迁移。

`anyio>=4,<5` 已列为直接依赖；环境原有 AnyIO 4.15.1，本轮未安装依赖。
未新增迁移，未提交或推送。

## 受控前后对照

临时服务均为单 uvicorn worker、loopback:58110，使用现有隔离库
`medical_assistant_graph_eval`（55432）、同一个合成账号。
每档并发 1/10/30，每档顺序预热 5 次，测量 15 秒、重复 2 次，
并用独立客户端每次健康请求结束后等待 100ms 再请求 `/api/v1/health`。
关闭 MCP、外部模型凭据、健康抽取和新闻刷新；只请求登录和本地健康接口。
临时服务已停止，端口已释放，其他数据库和项目服务未停止。

修改前服务在临时进程内加载备份的原始 `login_user`，不覆盖工作区文件；
修改后服务正常加载当前实现。两者使用同一个脚本、硬件和数据库配置。
后台机器负载/CPU 温度未严格固定，且先跑 before 后跑 after，没有随机化实验顺序。
数据累积的登录会话行也不完全相同，因此这是开发机短时对照，不是严格实验室容量证明。

下表将同档两轮逐请求样本合并后重新计算 nearest-rank 分位数，
RPS 为成功数除以两轮含排空总时长，不对每轮分位数取平均。

| 并发 | 版本 | 登录成功数 | 登录 P50 ms | P95 ms | P99 ms | 成功 RPS | 同时健康探测 P99 ms |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | before | 384 | 77.21 | 93.13 | 103.42 | 12.77 | 67.25 |
| 1 | after | 366 | 81.15 | 97.44 | 112.21 | 12.20 | 6.82 |
| 10 | before | 413 | 672.66 | 1327.84 | 1403.53 | 13.10 | 468.98 |
| 10 | after | 751 | 402.13 | 460.60 | 555.75 | 24.44 | 15.45 |
| 30 | before | 258 | 4134.44 | 6198.62 | 8029.43 | 6.84 | 1256.27 |
| 30 | after | 737 | 1149.61 | 1747.95 | 1803.34 | 22.45 | 29.18 |

每档两轮登录和健康探测均没有错误响应，且均校验响应 JSON 的关键业务字段。
单次复测成功样本均不足 1000，各档聚合登录样本也不足 1000；尤其健康探测样本较少，
尾延迟对个别请求敏感。原始记录保留 `p99_sample_count_warning=true`。
30 并发修改后两轮 RPS 分别为 26.12 和 18.92，不能只挑较高的一轮。

本次对照说明高并发时登录排队和事件循环响应有改善；单并发登录并没有更快，
由约 77ms 变为 81ms，且增加了线程调度和凭据行重读的成本。
不能据此宣称生产最大 QPS=22.45，更不能替换成 AI 问答/首字延迟。
后续如需生产容量，应明确 P99/错误率目标，用代表性数据和固定到达率进行更长时间测试。

## 自动化验证

在明确设置的 graph-eval 隔离库上执行：

```powershell
.\.venv-codex\Scripts\python.exe -m pytest tests/test_password_work.py tests/test_login_parallel.py tests/test_auth_flow.py -q
```

结果：**9 passed（3.75 秒）**。包括真实 Argon2id 正误结果、事件循环可调度、
同时密码计算不超过 2 项、异常释放容量、AnyIO 取消时容量保留、不存在账号计算移出线程、
失败计数/锁定、10 次并发错误登录恰好 5 次 401 与 5 次 423、正确密码在锁定期仍拒绝，
以及既有注册/登录/cookie/刷新/退出链路。
测试临时用户已清理，仅操作隔离库。相关 app、脚本和测试 Ruff 检查通过。
未运行后端全部测试套件；本次验证范围是认证改动及压测脚本。

## 原始证据和复跑

- 原始代码备份：`data/auth-improvement-before-20261021/`，含修改前 auth 与 pyproject。
- 可长期核对的前后原始样本与旧登录源码：`docs/auth_performance_20261021_evidence/`。
- 驱动：`scripts/performance_auth_compare.py`，不会覆盖已有结果文件。
- 前提：Docker 及隔离库可用、同一环境密钥、存在合成账号 `bench_load_user`；
  不得切换到正式数据库。账号创建方法见原始五接口报告。

从 backend 目录启动一个前台临时服务（before）：

```powershell
.\.venv-codex\Scripts\python.exe scripts/performance_auth_compare.py serve --baseline-auth docs/auth_performance_20261021_evidence/auth_before.py
```

另一个终端运行（输出文件必须不存在）：

```powershell
.\.venv-codex\Scripts\python.exe scripts/performance_auth_compare.py load --variant before --output data/auth-before-NEW.json
```

停止该临时服务，再启动正常实现，并运行 after：

```powershell
.\.venv-codex\Scripts\python.exe scripts/performance_auth_compare.py serve
# 在另一个终端执行：
.\.venv-codex\Scripts\python.exe scripts/performance_auth_compare.py load --variant after --output data/auth-after-NEW.json
```

## SHA-256

| 文件 | SHA-256 |
| --- | --- |
| auth_before.py | 0e9eeb21f82ed7215bbc6dea78d8965706c92e96ef279dbd0563b542e3cc224a |
| before.json | 0af39f64f0332dfd2ebc63d062b3ac53f385d8821c47819ac369bf85eedaf025 |
| after.json | 1d8d81f83e454e0a38ab2e4ce843e42c3ee5378b9b87d166a51fcd3e45bc9332 |
| app/services/auth.py | 1ab9e6cd5c1ee7af61260413abc8daac67b73317d3266f7998a86f8d7d5cbef5 |
| app/core/password_work.py | 9c94d657aecfa08b50c7d3c673c888403f09041ffd488b3bae5588bb795f4b67 |

## 简历可用口径

“定位异步登录中的同步 Argon2 计算阻塞，通过受限线程执行与并发失败计数保护改进认证；
在单 worker 开发机 30 并发短时对照中，登录 P99 从约 8.03 秒降至 1.80 秒，
成功吞吐由约 6.84 提升至 22.45 次/秒。”

应同时准备解释测试条件、样本量和低并发无明显收益，不能写成生产容量或临床效果。
