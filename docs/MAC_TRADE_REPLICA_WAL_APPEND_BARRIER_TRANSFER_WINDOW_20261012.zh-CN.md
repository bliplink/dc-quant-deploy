# Mac Demo Trade HA Replica WAL/快照互斥修复（2026-10-12 16:30 CST 后）

## 本轮现场与验收边界

- Docker 实机仍维持 Order A/B/C Common `361e3e3` 的新镜像，
  Trade-A `c361e3e3` 新镜像；Trade-B 仍为承载十个活跃分区的稳定旧
  `a8fc334` 镜像；MD-A/B/C 和 Gateway 未替换或修改。
- **十租户只读业务审计 10/10 PASS**，每租户 Robot RUNNING、
  40 活动委托、买卖各 10 档；Order、Trade、MD、Gateway 容器
  均无新增 restart/OOM。
- 最后一次 Trade-B→Trade-A Full Snapshot 快速接管预检：
  `activePartitionCount=10,blockedCount=10,fastSnapshotPreflight=BLOCK`。
  最新 P023 的 B Snapshot seq=268598、A seq=9712；P054
  B=274934、A=0。**这并不等于 A WAL 数据不完整**，但不能证明
  立即快速接管，更不能批准重启仍承载全部活跃交易的 Trade-B。
  私有证据：
  `~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/trade-preflight-after-barrier-20261012.json`。

## 提交的 Trade 修复

Trade repo: `bliplink/com.app.dc.tradesvr`
验证分支: `codex/trade-safe-wal-archive-canary-20261012`
新增提交:
`e2cbf0cc2dc41f49185e0173ca2adbe2e30e5992`

### P0：Replica WAL append 与温缓存安装统一同一分区锁

发现之前 `TradeReplicaReplicationHandler.handle()` 在自己判断角色/epoch
后直接向 Chronicle Queue 批量追加，并没有获取
`TradeStateCoordinator` 用于业务状态提交、Snapshot 安装及 Primary
恢复提升的分区屏障，存在复制和本地快照封存并发交错风险。

修复：
- 新增进程内共享的 `TradePartitionMutationBarrier`，
  与 TradeStateCoordinator 的分区锁使用同一轻量 monitor。
- Replica 每次 batch 的**角色/epoch 再校验与整个 journal append**
  现在置于该锁内部；并没有额外增加磁盘写入。
- 这个共享 lock 不使用 `TradeStateCoordinator` Bean 注入，
  从而避免 `StateCoordinator -> ReplicationManager ->
  ReplicaHandler -> StateCoordinator` 循环依赖。
- 单测真并发：线程 A 在快照安装锁中，Replica B 等待；
  期间分区归属翻转；B 获取锁后返回 NOT_REPLICA，
  日志条目不会落盘。
- 额外普通持久复制回归：新一条 WAL 写入 OK，原条重放
  DUPLICATE，保留原有复制语义。

### 恢复传输窗口感知的主节点定时快照（尚未启用）

Common `VerifiedRecoveryStagingClient.MAX_TRANSFER_WAL_SLOTS=4096`，
而当前 Mac Trade-B `minCommittedMutations=20000`，正常
`STATE_BATCH + STATE_COMMIT` 一次交易就是两条 WAL，
差距容易大于协议单次传输的 4096 条上限。
为了防止自动温缓存总是拒绝，增加**明确关闭的 opt-in**：
```properties
trade.cluster.snapshot.periodic.recoveryTransferAware.enabled=false
trade.cluster.snapshot.periodic.recoveryTransferAware.maxWalSlots=2048
```

当单独开启且 Primary 已 READY 时，Snapshot 调度会将
`committedHeadSeq - latestFullSnapshot.snapshotSeq >= 2048` 视为
待生成新快照的额外条件；原有快照周期在关闭时完全不变。
2048 为 4096 的安全余量，**不保证多分区的批量捕获能跟上任意 TPS**：
当前调度每次仅选最繁忙的一个分区，需配合实际 TPS、轮询
频率和 Snapshot IO 测试，才可调整 Demo 生产配置。
这仅是 Snapshot **触发条件**，不是自动在 Replica 安装的调度器。

## 测试/构建证明

Java 8 Maven 容器编译与定向测试：
`TradeReplicaReplicationBarrierTest` 2、
`TradeSnapshotSchedulerTest` 5、
`TradeReplicaWarmSnapshotCacheInstallerTest` 3、
`TradePartitionLifecycleManagerTest` 9，
共 **19/19 通过，0 failure/0 error**。
上轮已有 Common 认证传输的普通 loopback 隔离测试通过；
**扩展后的完整 Netty→持久 Seal→Replica 安装 E2E
此前被环境安全检查拦截，没有新的通过证据**。
当前提交尚不可表述为全量 Java 测试或正式真实故障验收通过。

最新 Mac 本地构建候选镜像（构建成功，**未替换在线容器**）：

`dc-saas/tradesvr:cluster-dev-local-c361e3e3d-20261012-replica-barrier-e2cbf0c`

镜像源码：
`e2cbf0cc2dc41f49185e0173ca2adbe2e30e5992`

Common Jar SHA-256：
`0ed677b3c57bf65664c209c150570a598b1a9db7a82e63a694e1fe926bf003f3`
与在线 Order 三节点 Common SHA 相同。
Mac 候选清单：
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/local-ha-images.env`。

## 不可越过的发布门槛

1. 新 Trade Replica 温缓存服务默认 disabled，Source HEAD/DATA
   只允许 loopback+独立节点密钥；跨 Docker network namespace
   不能简单当作已经具备 TLS/mTLS 的跨宿主机安全同步机制。
2. 缺真实的**自动可信 HEAD 元数据发现、调度及批量 Replica
   暂存安装**。Common staged receipt/业务缓存安装并不表示 READY，
   也没有提前改变活跃主副本的业务状态。
3. 需要先在隔离环境完成扩展端到端及中断/epoch 变化测试，再
   开启一个活跃分区安全 warm cache，验证确实缩短切换耗时。
4. 完成权威 MySQL/Projection/Trade 一致性、Order/Trade 故障注入
   后才可滚动更新当前 Trade-B 或声明 Demo HA 验收完成。
5. Gateway 仅透传，**本轮完全没动**。真实 WAL 自动物理封段
   和回收删除还没有全链路门禁验收，GC 继续关闭。
