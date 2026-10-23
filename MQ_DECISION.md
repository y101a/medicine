# 是否引入消息队列（MQ）的决策记录

结论（2026-10-06，DSH）：**当前不需要引入 MQ。** 项目已经在用「数据库当队列」的标准做法，
而且 MQ 会在最关键的删除一致性上造成倒退。等出现明确的触发条件再迁移，路径与阈值见第 4、5 节。

## 1. 现状证据（代码依据，不是推断）

本项目**没有任何**消息队列/任务框架依赖：全仓库 grep `redis | celery | arq | rq | dramatiq | kombu | APScheduler | pgmq` **无匹配**。
异步任务全部落在数据库任务表上，用行锁领取：

| 机制 | 位置 | 作用 |
| --- | --- | --- |
| `FOR UPDATE SKIP LOCKED` 领取任务 | `services/document_generations.py:760,792`、`services/generated_document_deletion.py:99`、`services/image_deletion.py:109`、`services/image_generations.py:500,646,711`、`services/medical_image_cleanup.py:62,75`、`services/knowledge_graph_publication.py:156` | 多个 worker 并发领取互不抢同一行，天然支持多实例 |
| 租约（lease） | `services/knowledge_graph_publication.py:127` 注释原文：「取一个可跑的任务并加租约（`FOR UPDATE SKIP LOCKED`，多个 worker 不会抢同一条）」 | 任务被抢走后不会被别人重复处理 |
| `pg_try_advisory_xact_lock` 单例锁 | `services/medical_image_cleanup.py:42`、`services/speech_limits.py:33` | 全局只能有一个实例跑的清理/限额任务，多实例安全 |
| 进程内触发（少量） | `api/routes/news.py:67,133`（`BackgroundTasks` 跑每日自动刷新与手动重试）、`services/health_records.py:497`（`asyncio.create_task` 跑一次计划抽取） | 只在「非关键路径、可重试」的地方用 |

也就是说，「队列语义」里真正需要的三件事——**并发领取不重复、失败可重试、多实例安全**——已经由
数据库 + 行锁 + 租约 + 咨询锁实现，且不需要额外运维一个有状态服务。

## 2. 为什么现在引入 MQ 是负收益

1. **一致性倒退**：项目刻意把「物理删除意图」与「业务逻辑删除」放进**同一事务**（迁移 `20260923_0020` 的设计，
   支撑失败重试与磁盘孤儿对账）。引入 MQ 就变成双写：要么消息发出但事务回滚（幽灵任务），
   要么事务提交但消息丢失（漏删）。要修就得再上 outbox 表——**那等于把 MQ 的一半复杂度又搬回数据库**。
2. **运维成本**：多一个有状态服务（部署、监控、备份、扩容、版本升级、连接管理），
   与项目既有纪律「本地不启动多余常驻服务、不留后台自启动」直接冲突。
3. **调试与可观测性变差**：现在任务状态就在 `generated_documents` / `image_generations` 等表里，
   一条 SQL 就能查「卡在哪个阶段、重试几次、谁在处理」；消息在 broker 里则要跨系统排查。
4. **本项目的瓶颈不在这里**：真正的风险是**多实例并发重复处理**，而这一点已被 `SKIP LOCKED` + 咨询锁覆盖。

## 3. 现状仍需自查的两个点（不是 MQ 问题，是可靠性细节）

- `api/routes/news.py:67,133` 用 `BackgroundTasks`：进程重启会丢掉当次刷新的执行（已有 run 表记录，
  但**恢复路径未验证**）。
- `services/health_records.py:497` 的 `asyncio.create_task`：同样不跨重启，且没有重试/租约。
  这两处若要变可靠，第一选择是**把任务写进任务表交给 worker 领取**，而不是引入 MQ。

## 4. 触发条件：出现以下任一条，才值得启动 MQ 评估

1. worker 需要独立伸缩，且**实测** DB 轮询成为瓶颈（先量：每秒空轮询次数、任务等待时间 p95、连接池占用）。
2. 需要跨服务/跨语言消费者，或一个事件需要 fan-out 给多个下游（现在没有第二个消费方）。
3. 需要消息级延迟重试、死信队列、优先级队列（现在用「下次重试时间」字段 + 租约到期实现，够用）。
4. 突发写入超过数据库连接池承受能力，需要削峰缓冲。
5. 任务量级达到每天数十万以上，且数据库任务表成为写入热点。

在 1–5 都不成立时引入 MQ，属于「用复杂度换不到东西」。

## 5. 迁移路径（真到那天，按性价比三步走）

1. **零新依赖**：把定时轮询改成 Postgres `LISTEN/NOTIFY` 事件触发，延迟从「轮询周期」降到毫秒级。
2. **仍在同一个 Postgres**：需要延迟投递/重试/死信/可见性超时，就用 `pgmq`（Postgres 扩展）或
   Redis Streams（消费组 + `XACK` + pending 列表）。
3. **只在多语言、高吞吐、事件溯源场景**：才上 RabbitMQ（路由灵活）或 Kafka（分区、回放、高吞吐）。

无论走哪一步，**保留数据库任务表作为事实来源**，MQ 只做「通知/加速」，这样事务一致性不会被破坏。

## 6. 面试话术（这条比「我用过 MQ」更值钱）

被问「为什么不用消息队列」时，按这个顺序答：
① 现状：任务表 + `FOR UPDATE SKIP LOCKED` 领取 + 租约 + `pg_try_advisory_xact_lock` 保单例，多实例安全；
② 收益：删除意图与业务删除同事务提交，避免消息与数据库双写不一致；
③ 代价：MQ 要多一个有状态服务与 outbox，可观测性下降；
④ 阈值：给出上面第 4 节的 1–5 条量化触发条件；
⑤ 路径：`LISTEN/NOTIFY` → `pgmq`/Redis Streams → RabbitMQ/Kafka。