# Trade HA 本轮安全发布门禁与可选双分区恢复（2026-10-12）

## 核心结论

**尚不具备无中断滚动替换 Trade-A/B 的持久化证明。**
Mac Demo Trade-B 当前持有十个活跃分区 Primary，Trade-A 是
唯一 Replica；实际 `trade.cluster.replication.required=true`，
`TradeReplicationManager.replicate()` 要求每个分区
`replicaNodes()` 中的**全部**物理节点 ACK。
不能简单把副本配置改为非必需，也不能仅增加 Learner 后宣称
已有 2/3 quorum；真实维护期必须避免再次主动停唯一同步 Replica。

### 1. 源码发布门禁与真实 ZK 检验

部署仓库 `dc-quant-deploy/saas-crypto`
新增 `tests/trade_sync_replica_rolling_gate.py` 和
`tests/test_trade_sync_replica_rolling_gate.py`，
提交 `d31fd6a74fc5160c62e658fe4c0e9e1cebb863b5`。

- 单测 **6/6** 通过；检查真实
  `/dc/cluster/tradesvr/partitions/Pnnn` 中的 Primary、
  Replica 集合、READY、epoch，以及 Primary 配置的
  all-ACK 策略。部分目录永不批准滚动发布。
- 实际 10 个活跃分区检查结果：
  `status=BLOCK`、`checkedPartitions=10`、
  `blockingPartitions=10`、
  `reason=ALL_REPLICA_ACKS_REQUIRED`、
  `authorizesRollingRestart=false`。
  私有证据：
  `~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/trade-a-replica-rolling-ack-gate-20261012.json`。
- 失败后保留的停止状态旧 canary
  `dc-saas-tradesvr-failed-2ed6095`
  已设置 Docker `--restart=no`；正式 A/B
  容器仍为 `unless-stopped`，没有更改其资源或镜像。

### 2. Trade 恢复耗时机制与隔离优化

在上一轮 A 被短暂停止后，B 曾因为复制无 ACK 留下
未提交 STATE_BATCH，执行保守的
`plan → apply → checkpoint → rebase → READY`
恢复；10 分区 READY 时间相隔约 1 分钟，完全恢复超过十分钟。

Trade repo 验证分支
`codex/trade-safe-wal-archive-canary-20261012`
新增提交
`0e798cc738c3c5093637276c3a23662c6e5e1358`：

- `TradePartitionLifecycleManager` 新增
  `trade.cluster.lifecycle.maxConcurrentRecoveries:1`，
  **默认=1，原单线程行为完全不变**。
- 只有经配置显式设置为 2，且两个不同分区都被确认需要
  恢复时，才使用最大两个 daemon 工作线程；
  原有每分区的 `TradeStateCoordinator` 互斥锁、
  assignment epoch 检查、durable watermark 核对、
  dirty-tail checkpoint+archive 及 READY 栅栏均保留。
  调度周期等待工作完全结束，不能从这个优化推断多主、
  quorum 或复制容灾性能已经通过。
- `maxConcurrentRecoveries > 2` 启动阶段拒绝。
  真实并发隔离测试验证 P001/P002 同时进入恢复过程后
  分别 READY；不改变 Order/MD/Gateway，也未提高
  Mac 当前在线 Trade 的并发配置。
- Java8 Maven 运行
  `TradePartitionLifecycleManagerTest`、
  Replica WAL 和 Warm Snapshot 调度回归
  **16/16** 通过；排除仅限挂载 Mac 真实卷的临时取证
  fixture 后，最新版全量测试
  **288/288** 通过，0 failure/error/skip。

本地 Mac 构建候选：
`dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261012-archive-recovery-0e798cc`
镜像源码 SHA 为上述 `0e798cc`，
Common JAR SHA256 为
`34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`。
此前 Trade 的六个真实历史 Archive GAP 已在离线 APFS COW
克隆中全部验证通过，补读代码也包含在新镜像中。
**这依旧是本地镜像，不是 GitHub Actions 正式 GHCR 发布**。
原 git POM 尚未公开发布与该新 Common 匹配的开发依赖；
本地隔离 POM 使用
`0.0.4-dev6b8fe7d20261012-SNAPSHOT`，
不可误判为公开仓库可单独编译发布。

### 3. 数据一致性和 Trade-B 升级准入仍失败

- 当前 Trade-B→A 全量 Snapshot 预检：
  `activePartitionCount=10`、
  `blockedCount=10`、
  `fastSnapshotPreflight=BLOCK`、
  `walAndReplicaAckProof=NOT_CHECKED`、
  `authorizesPrimaryRestart=false`。
  与另一个 ACK 发布门禁相互独立；两者都不得绕过。
  私有证据：
  `.../artifacts/trade-rollout-headroom-after-new-parallel-canary-20261012.json`。
- 在线 MySQL `dc_trade_projection_watermark` 的六个分区
  P023/P054/P060/P077/P244/P246
  水位分别
  219475/223429/215797/213139/214965/212879，
  仍未被在线旧版 Trade-B 的旧 Archive GAP 代码补读；
  当前新版已做 6/6 真实历史 Archive 只读 COW 验收，但尚未
  在在线 Primary 实际验证 MySQL 水位推进。
- 额外运行了有界、只读
  `tests/check-projection-consistency-host.sh`，在 60 秒
  和 63 页内扫描 `630000` 条 Mutation，
  `orphanMutations=0`，但未扫描完整数据，
  最终 `PARTIAL_NOT_ATTESTED`；
  **必须明确写成审计不完全，而非全量一致性通过**。
  私有证据：
  `.../artifacts/projection-bounded-consistency-20261012-1932.json`。
  当前 MySQL 1.5GiB 内存上限，不宜在线反复全面扫描。

## 上线门槛与剩余 P0

1. 设计并验收满足可证明交集的**三节点持久化 quorum / joint membership**
   或提供经批准的受控停机维护流程；必须证明旧 committed
   WAL 不会在角色切换/成员替换时丢失，不允许通过关闭
   `replication.required` 伪装为高可用。
2. 受控升级 Trade，真实让 Projection 越过六个旧 Archive
   GAP 并完成 MySQL 逐业务 / watermark 对账；监控 TPS、内存、
   磁盘与故障恢复影响。
3. 只在完成 Trade-A 可接管全量快照、持久 WAL ACK、
   源主从仲裁和资金/仓位/订单/成交一致性后，执行
   Trade-B 的 SIGKILL 和角色反转。
4. WAL 安全回收、200 租户压力测试等待上述门禁通过。
   MD 自动主切、WAL 自动删除均未在本轮开启；Gateway
   始终透传，不改动。

本轮未替换在线 Trade 容器，没有清理已有 WAL。
