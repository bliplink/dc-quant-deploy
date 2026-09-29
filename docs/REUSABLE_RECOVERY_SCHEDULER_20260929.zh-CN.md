# 可复用恢复调度与计划资源生命周期

日期：2026-09-29。源码：app-common 本地提交 `e95850b94206d699689683d61fa177ff3fa13b4d`。**未发布 Maven 依赖，未接入或部署 Order、Trade、MD；不属于异常切换验收结果。**

## 1. 交付边界

在现有注册、路由、assignment、epoch fence 和恢复协议上补 `PartitionRecoveryExecutor`，不建立第二套控制面。它只提供有界调度：

- 准备/重放在独立命名 daemon 线程执行，没有 caller-runs 回退，不在 ZooKeeper watch 回调里同步扫描日志。
- 有限并发、有限等待队列和调用方声明的资源额度；额度不足就等待，单任务超预算则拒绝。
- 同一分区去重；较新的调用方 generation 可以替换等待项，或协作取消旧运行项，但不能与旧项并行。
- 取消 Future 不代表任务已退出。旧任务真正退出前，仍占分区运行槽和资源额度；关闭也是协作 drain，不强制打断业务/存储代码。
- 小任务可有限次越过因额度不足而阻塞的大任务；达到旁路次数后预留额度给较早的大任务。等待旧 generation 退出的分区不阻塞无关分区。
- 严重 Error 或线程启动/调度失败停止接收新任务。启动失败回滚未开始任务的资源占位，保留错误原因；不伪造恢复完成。

`PartitionRecoveryCoordinator.Adapter.closePlan` 新增显式资源关闭钩子：成功 prepare 返回的计划，成功路径在 READY 前调用一次；旧 token、install/verify 失败时也调用一次。关闭失败不发布 READY，原始失败及关闭失败通过 cause/suppressed 保留。prepare 本身失败前分配的部分资源仍由 adapter 负责释放。

关闭钩子默认 no-op，兼容原来的无资源 adapter；**不会自动替服务关闭句柄**。有固定快照文件描述符等资源的 adapter 必须实现它，且不得清除已经安装到业务运行表中的状态。关闭失败被报告，不等于已经强行释放了资源。

致命错误传播给调用者；Coordinator 尝试撤销本次 epoch 的 READY，不清除更新 epoch 的 READY。Executor 停止接收后续任务，但不负责全节点所有已就绪分区的统一 fence；服务的故障处理/监督者仍必须把不可用节点隔离。

## 2. 调用契约

入口：`submit(partitionKey, generation, estimatedUnits, Work)`。generation 是调用方维护的单调尝试/归属修订号，不是持久 epoch、CAS version 或多数派证明。相同在飞 generation 去重，较旧的拒绝；只比较当前等待/运行项，不维护全历史版本数据库。

| 提交结果 | 调用方动作 |
| --- | --- |
| ACCEPTED | 观察 handle 和服务恢复结果；接受调度不等于 READY |
| DUPLICATE | 使用已有 handle，不能重复加载相同分区 |
| STALE | 丢弃旧请求并重新检查当前归属 |
| RESOURCE_TOO_LARGE | 校正容量/工作量，不能无限增大预算绕过门禁 |
| QUEUE_FULL | 保留当前目标，延迟重试；被拒的新请求不取消原运行项 |
| CLOSED | 进入故障/drain 流程，不静默创建另一个执行器继续晋级 |

generation 只应在归属变化、显式新尝试等事件递增；不要每次周期轮询都递增并取消尚未完成的恢复。角色变化必须取消旧工作并在长扫描/传输中检查 token/context，所有 mutation、install、readiness writer 仍共享同一分区屏障。

Barrier 必须同步执行并传播异常，只负责本地屏障；清理旧计划或撤销旧 READY 不能被“必须仍是当前主”之类的额外所有权判断阻断。业务入口在该屏障内同时检查归属、epoch、控制面连接、READY 和服务自身提交安全条件。

Adapter 的 `verifyPromotion` 不得是空操作：Order/Trade 要证明提交边界和业务状态，MD 要证明基线/增量序列及 freshness。库中的合成测试用空证明仅测试编排，不是服务晋级证明。

Snapshot 计数里的 completed 表示工作函数正常返回，不表示分区 READY。服务必须另外记录 Coordinator 的 READY/STALE/FAILED、失败阶段、epoch、assignment version 和提交/序列证明。handle 被取消/已完成也不意味着预算立即可复用，应看运行槽退出。

## 3. 预算与时限

- 并发上限配置 1–32，等待项上限 1–65,536；旁路次数 0–4,096，默认 8。初次服务接入保持小并发，不能按最大值启动。
- estimatedUnits 可选择 MiB 等服务约定单位，只约束在飞恢复的估算总量。**不测量真实 JVM 堆，不含已经安装的常驻业务状态，不限制实际磁盘带宽/网络流量，也不能防止 adapter 私自创建额外线程。** 容器/堆/直接内存和 IO 配额仍须独立预算。
- 前面的真实 Trade 副本已证明：仅两个大分区 GC 后约 439–477 MiB，B 的 384 MiB 堆未通过接管门禁。不能因为有执行器就自动认定容量足够。
- 公平调度只在工作能够退出的条件下推进；不承诺硬恢复时限。IO 要有超时，长扫描要定期检查 context/token；不协作或阻塞的任务不能提前释放预算，必须由服务监督者采取安全隔离/停止措施。
- 自动重试、退避、deadline、IO 限速和副本追平协议未被塞进这个原语。调用方负责有界重试；库不修改 primary，不清 journal，不跳过 dirty tail，不开启“QUORUM 可用”。

## 4. Order、Trade、MD 接入顺序

| 服务 | 准备/安装对象 | 晋级前额外证明 |
| --- | --- | --- |
| Order | 活动单、撮合簿、幂等状态及 snapshot + committed delta | 已确认订单/成交可恢复、复制提交/epoch fence、快照传输没有放大或 GAP |
| Trade | 余额、持仓、配置、完整订单镜像、执行结果/终态去重 | 历史基线/订单镜像权威核对、资金效果、degraded commit 的权威来源、完整节点容量 |
| MD | book/ticker/trades/kline 与 snapshot/sequence delta | GAP 补齐、序列连续、freshness、旧主拒绝发布与订阅收敛 |

当前 Coordinator 面向本地主恢复与晋级，不是 Replica/Learner 角色协议。MD C 的 learner/catch-up 需要独立角色/序列门禁，不能用 Primary READY 代替。Executor 可以承载工作，但不会自行选择或变更角色。

下一适配阶段先在独立目录/namespace 和小分区建立契约测试，再替换服务内重复调度；保留各服务存储格式和持久性策略。正常运行路径也要验证恢复期间读/风险计算的门禁，不只挡写请求。

现有 generic 源码项目 POM 为 `3.0.13-SNAPSHOT`，现有服务桥接依赖使用 app-common `3.0.14`。本轮未改版本、未 install/deploy，也未混入候选 Trade image；应先将源码合入正确版本并做桥接及三个服务的兼容构建，再发布固定依赖/镜像。

## 5. 验证

- Java 8/Maven 缓存容器，断网，1 CPU / 1 GiB；无真实 journal、集群连接或故障注入。
- app-common 全量 24 个测试类 / 83 个用例，0 failure/error/skipped。
- 调度器 16 个 + Coordinator 14 个契约用例；连续 8 轮共 240 个通过。
- 覆盖：不阻塞提交线程、资源/并发/队列上限、去重/新旧 generation、拒绝替换保留旧项、取消保留预算、失败排空、公平旁路、long 预算不溢出、协作关闭、严重错误停止接收、线程启动失败无占位泄漏、同 epoch 新 assignment 不被旧恢复覆盖、关闭计划早于 READY、stale/失败/关闭异常与致命错误传播。

复现（generic app-common 源码目录、Java 8）：

```sh
mvn -q test
mvn -q -Dtest=PartitionRecoveryExecutorTest,PartitionRecoveryCoordinatorTest test
```

这些是调度/生命周期契约测试，不是业务计算、MD 序列、集群 RTO/RPO、TPS 或跨宿主机 HA 的验收。
