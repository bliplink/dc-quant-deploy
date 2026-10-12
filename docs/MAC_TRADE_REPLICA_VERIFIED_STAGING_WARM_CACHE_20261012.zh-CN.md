# Trade Replica Snapshot 暂存与温缓存安装推进（2026-10-12）

## 真实完成的源码与构建

Trade GitHub 验证分支：
`codex/trade-safe-wal-archive-canary-20261012`。

- `ef58d825b5afe3a40418f4400186deb270ee09b3`：
  `TradeReplicaVerifiedStagingService`，复用 Common
  `VerifiedRecoveryStagingClient`，认证 HEAD / 分块 Snapshot /
  WAL 完整提交后缀落盘暂存；严格限制 ZK assignment 版本、
  Primary 名称、当前本机 Replica/Learner、loopback endpoint，
  数据大小与 WAL 数量，**默认关闭，不修改业务**。
  源端新增 25s 认证 HEAD 稳定代际，允许源 Primary 在 Snapshot
  不变时继续提交后续交易而不破坏已经签发的旧累计提交证明；
  ZK 版本、epoch、快照哈希变化时失效，提交回退失败。
  以 Snapshot 文件 key/mtime/size 做 SHA memoization，
  文件原子替换即失效，内核无 fileKey 时退化为每次哈希。
  实际 loopback Netty 测试通过 HEAD、DATA、真实 Trade
  `STATE_BATCH/STATE_COMMIT` 下载及完整校验，
  产生的 receipt 明确为 `VERIFIED_TRANSPORT_ONLY`，没有 READY。
  **之前版本的全量 Java8 Maven 265/265 通过**。
- `0b701361d54ac20eaae891745c4a3375453fe38c`：
  `TradeReplicaWarmSnapshotCacheInstaller`，补 Common
  `DurableRecoverySnapshotSeal` + 验证 WAL suffix +
  单分区屏障 + 当前 ZK 精确版与 Replica 角色再确认 +
  local Chronicle `STATE_COMMIT` 对账。
  `TradeSnapshotStore.installVerifiedReplicaCache` 以流式复制、
  fsync、强制 atomic rename 更新**仅磁盘上的 Replica full image**，
  不重置/删除现有 WAL、不修改业务内存、不推进 epoch 或 READY。
  `TradePartitionLifecycleManager` 的恢复计划、状态恢复、
  脏尾归档和最终 READY 也使用同一个
  `TradeStateCoordinator.withPartitionIdLock`，
  避免未来缓存安装与 Primary 提升读取不同代 Snapshot。
  **缓存安装/并发/本地提交标记隔离测试 15/15 通过**
  （包含一个并发恢复屏障测试），最早的存储及 loopback
  独立测试 4/4 也通过。

增加的 `TradeReplicaVerifiedStagingNettyTest` 测试链路已扩展为
`Netty HEAD/DATA → Common Verified Staging → Durable Seal →
Trade 本地 COMMIT 对账 → Snapshot 缓存安装 → 重新打开验证`。
**扩展后整体用例的实际执行被 WebCodex 环境安全检查拦截**，
因此不能宣称此条扩展版 E2E 已通过。
新提交的 Java8 Maven `-DskipTests package` 成功，但此项
只代表编译/打包，不等于运行最新提交的全量测试。
以前 `ef58d82` 的 265/265 不能冒充 `0b70136` 的测试结果。

最新本地构建（没有线上容器替换）：
`dc-saas/tradesvr:cluster-dev-local-c361e3e3d-20261012-replica-warm-0b70136`

镜像源码：
`0b701361d54ac20eaae891745c4a3375453fe38c`

公共 Jar SHA：
`0ed677b3c57bf65664c209c150570a598b1a9db7a82e63a694e1fe926bf003f3`。

## 安全边界

- 目前 `trade.cluster.recovery.source.enabled=false`，
  `trade.cluster.recovery.replica.stage.enabled=false`，
  `trade.cluster.recovery.replica.install.enabled=false`，
  且并没有自动调度器。**新恢复接口与缓存安装不能自运行**。
- 仅允许 loopback + 物理节点独立 256-bit 密钥的测试门禁。
  跨 Docker 容器/跨宿主机安全部署需要明确的 ACL、TLS/mTLS
  和可核查的预期 Source HEAD 的授权获取。
- Common `VerifiedRecoveryStagingClient.MAX_TRANSFER_WAL_SLOTS=4096`；
  快照和 HEAD 差距大于这一上限会 fail closed，需要先改善
  Primary 快照频率或引入可安全续传的历史分块机制。
- 温缓存安装没有调用业务 `ReplicatedStateMachine.restore`：
  Replica 当前只持 WAL 与更近的恢复用完整 Snapshot，
  **不是业务状态立即 READY**。未来故障切换仍由
  `TradeRecoveryPlanner` 从持久快照 + WAL 按现有规则恢复。
- 由于缺少实际 10 租户的 Replica 快照连续下发、
  故障注入、资金/持仓/成交/Projection 一致性验收，
  **不能重新部署仍作为当前 Primary 的 Trade-B**。
  MD-C 独立修复镜像和 Gateway 保持不变。
- Gateway 完全透传，不承担任何恢复逻辑。
  同 epoch WAL 正常期自动封段 / archive 安全删除
  尚未按权威 Replica/Projection checkpoint 验收，GC 关闭。

## 剩余 P0

1. 让完整的新 E2E 及全量回归在合规执行环境运行；
   对 SNAPSHOT→WAL→CACHE 注入传输中断、部分文件、epoch CAS 变更。
2. 受控 loopback 的 1 分区实际在线 Stage + Cache Warm，
   以及完整业务状态恢复耗时（baseline 与 warm 对照）。
3. 确认远程部署下认证和密钥分发、内网 TLS，
   实现按 committed watermark 触发的 Replica 自动温缓存。
4. 10 个租户权威 consistency 与 B→A 真实 SIGKILL failover，
   然后才滚动替换 Trade-B、MD/Gateway 候选、开启 WAL seal。
