# Order / Trade 共用 Common 恢复机制：实现差异与 P071 证据（2026-10-14）

## 确认的代码事实

Order 和 Trade 已复用 Common 部分控制模块，但 Snapshot 的复制/安装流程并不相同：

- Order 的 OrderSnapshotReplicationManager 通过带序号的复制日志发送 SNAPSHOT_BEGIN/CHUNK/END，OrderReplicaSnapshotInstaller 验证身份、Epoch、序列边界和 SHA 后安装。OrderPartitionRecoveryManager 要求 Snapshot 不能超前于本地 WAL，且检查日志基线和提交状态。
- Trade 的 TradeReplicaWarmSnapshotScheduler 通过签名 HEAD/Manifest + staged Snapshot/WAL 的专用路径；TradeReplicaWarmSnapshotCacheInstaller 在单独验证本地提交标记后更新业务 Snapshot。TradeRecoveryPlanner 同样拒绝 Snapshot 超前于本地 WAL。
- 两者虽然复用部分 Common 安全规则，Snapshot 安装和 WAL 基线调整仍不是同一个事务实现。Order 暂时未观察到类似错误，并不代表没有相同风险。

## P071 真实事件时间线

- ZooKeeper 分配：TradeSvrB 为 P071 的 Primary、TradeSvrA 为 Replica，epoch=1。ZK READY 并不能代替 JVM 业务已 READY 证明。
- 03:54:47，Trade-B 记录未提交尾部归档及恢复基线：baselineSeq=309368。
- 04:02:35，Trade-B 保存 Snapshot 311482。
- 05:02:38，Trade-B 保存 Snapshot 312034。
- 06:19 开始，Trade-B 恢复报错，Snapshot 312034 但本地 journalLastSeq 309369，重复返回 PARTITION_NOT_READY；Trade-A 向 B 读取 signed HEAD/Manifest 遇 IOException。
- 另有 Trade-A 8 个分区出现 Snapshot 超前于本地 WAL 的问题。只读报告可见 TRADE_RECOVERY_GAP_AUDIT_20261014.zh-CN.md。
- 现场不能仅凭日志确定 WAL 序号为什么下降；必须在隔离副本上检查物理 CQ、归档目录、提交边界与重启/重建过程，不能猜测为某一种确定原因。
- Order A/B/C 近期日志未发现 ORDER_PARTITION_RECOVERY_FAILED 或相同 Snapshot 超前报错，只说明当前未观测到异常。

## 统一约束

1. Common 为 Order/Trade 提供**同一套**分区角色、ZK CAS、Epoch/fencing、提交 WAL、Snapshot 校验、Journal 基线切换、归档、RECOVERING→READY 生命周期。Order/Trade 只实现自己的业务状态机。
2. Snapshot 安装与 WAL 基线更新必须由同一独占分区恢复事务协调：持久化新镜像、验证物理源及 Replica 提交 HEAD、切换 WAL baseline、恢复业务数据、确认仍持有角色后才能 READY。崩溃后应能恢复到一致的某一个 generation，不能遗留 Snapshot 312034 / WAL 309369。
3. Order/Trade 共同使用 Common 现有 SnapshotRecoveryBoundary 与恢复协调器，不额外创建一个 Trade HA 框架。签名传输可以保留作为 Common 恢复事务输入，但不能绕过 Common 最终安装和门禁。
4. 对于任何 Snapshot 大于本地 WAL 的分区，先保持 NOT_READY，再校验独立权威源头及归档提交链，禁止伪造尾序号、强制回滚有提交状态、删除旧 WAL 或禁用保护以求快速 READY。
5. 在离线 P071 物理日志副本上复现并修复后，本地编译两个服务、跑同一组故障/崩溃恢复测试；通过真实 Replica 水位和业务数据一致性核验后再灰度。

目前没有对线上业务数据、主节点、Gateway 或已保存恢复文件做写入修改。
