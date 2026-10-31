# T374｜Demo+Common 隔离修复：共享 Failover 调度（2026-10-31）

## 业务环境隔离原则
- 当前 Order A、T371 Order B、Trade A/B、Gateway、T369 Projection、RobotSvr **保持运行**；不进行 SIGKILL、容器替换、ZooKeeper 主切或清理真实 WAL。
- 截至 2026-10-31 20:54 CST，`EBAUU3`、`NWQYBB` 的 Robot 均为 `RUNNING / 40`；`C8SMUE` 仍为 `DEGRADED / 0`。两租户历史执行数分别为 1602 与 1900，随时间继续增长。
- 已单独建立一次约 3 小时后的运行巡检计划；巡检验证实际 Order/Trade/Robot/Projection 证据，不进行故障注入。

## 精确 Common 基线
- `/Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027` 有完整源码及原始可重现的 T143 Common Jar。
- 基准 JAR `com.app.common-3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT.jar` SHA-256：
  `7cbe13f614f0abd478b02188e15660b572f1c4519866684c3b308e92593784e6`。
  **该值与现网 Order/Trade 内安装 JAR 完全一致**；因此没有使用过时的 `.work/app-common` 源码假装修复。
- 新隔离 Common 工作树：
  `.work/t374-demo-common-ha`，分支 `fix/t374-demo-common-ha-shared-control`，本地提交 **`5306c41`**。未合并至业务 `saas-crypto`，未触发 GitHub Actions。

## 已完成的 Common 改动与本地回归
- 源码：`src/main/java/com/app/common/replication/CommonCertifiedFailoverWatch.java`。
- 去除每个 Watch 自己创建 `Executors.newSingleThreadScheduledExecutor` 的模式；改为 **每 JVM 两条 daemon 控制线程**的共享 `ScheduledThreadPoolExecutor`。这只是控制面，**不修改 WAL/ACK、业务回放、RSA、Epoch/CAS 逻辑**。
- 每个 Watch 独立持有 `ScheduledFuture`，完成阶段、签名 READY 或 close 时只取消自己的任务；不 shutdown 其他分区的共享线程。关闭后不能重新 start；取消任务立即从共享队列清理。
- 新测试 `CommonFailoverControlSharedSchedulerTest` 验证 128 个 Watch 使用不超过 2 条实际控制线程、相互取消不影响其他 Watch、close-before-start 拒绝。连同 `CommonCertifiedFailoverCoordinatorTest`、`CommonCertifiedStrictCrashReadyCompletionTest`、`CommonCertifiedNodeRuntimeTest`、`CommonHomeReturnCensusTest`、`CommonCertifiedIndependentWitnessWatchTest`，隔离 Common **36/36 JUnit PASS**。
- 使用现网同版基准构建独立测试 JAR `.work/t374-demo-common-ha/target/t374-demo-common-shared-failover.jar`。打包了修改类及匿名内部类；已用完整 JAR 跑上述 36 项测试。**该 JAR 仅供 Demo+Common 隔离测试，未替换任何业务镜像**。

## 明确尚未完成（NO-GO）
1. `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay` 原有启动流程并未激活 `armAutomaticPhysicalRecoveryWatch`；**共享调度修复不等于真正自动接管**。要由 Common 的统一启动编排在真实物理 WAL/业务回放认证后，建立 `CommonCertifiedFailoverCoordinator`、独立 CatchupProof、不可伪造的物理恢复回调并激活 Watch。Order/Trade 最终只使用同一个 Common 公共机制，不加业务选主。
2. 两线程共享调度限制线程数，但每个 Watch 仍执行各自 ZooKeeper 控制查询。**下一阶段要在 Common 做节点级批量/事件驱动刷新**，不能把每个分区的 ZK 轮询搬到交易热路径。
3. 必须在真正隔离的 Demo+Common JVM/ZK 环境做 A→B→A 与 B→A→B 的真实双向故障注入，验证原有 128 主分区不中断、新主可信 WAL 追平、签名 READY、全 128 回 Home 总时间、无重复提交、无双主、无丢失及 P99；通过后再替换业务 Common 镜像。
4. 现有 T323 真实 ZooKeeper 测试依赖的 T292 本机夹具缺少部分私钥及严格业务 WAL；不能谎称全量真实测试已通过。旧 T323 证据卷保留，严禁将测试新证据当成现网 RSA 授权。

**本阶段结论：Common 共享调度修复 36/36 PASS；自动主切/回 Home/真实隔离 HA 仍 NO-GO；订单交易业务继续运行。**
