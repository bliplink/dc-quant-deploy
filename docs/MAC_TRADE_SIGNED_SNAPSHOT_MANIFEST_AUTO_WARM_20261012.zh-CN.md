# Mac Demo：Common 签名 Snapshot Manifest + Trade Replica 自动温缓存（2026-10-12）

## 结论（实机源码和运行状态，避免混淆）

本轮完成 Common 的 **可信 Snapshot Manifest**（精确 imageBytes +
业务 Snapshot baseline commit state/epoch/marker），Trade 的
**完整 HEAD → Manifest → Source WAL → Replica verified staging →
durable seal → 本地温缓存**离线网络测试，以及低优先级、单分区、
指数退避的 **autoWarm 调度器源码**。
**源码已提交、Java8 全量通过、镜像已构建，但均未在 10 租户 Demo
打开新的同步服务或滚动替换 Trade-B。**

原因是现网接管门禁仍明确失败：Trade-B 持有十个活跃分区的较新快照，
Trade-A 完整快照仍远落后，且 A/B 使用分离的 Docker 网络命名空间，
当前源端协议要求 loopback+独立强密钥，未完成 TLS/mTLS 跨容器
认证传输。直接启用明文 Docker 私网或在 B 未具备快速备份时重启
均不符合 HA 目标。

## 代码提交和测试

**Common** repo: `bliplink/com.app.common`
验证分支：`codex/common-wal-rotation-policy-20261012`
本轮提交：`6b8fe7d3397c7b75db33a28d4fed17d9a34f087d`
全量 **237/237 passed**，0 failed/errors/skipped。

- 新增 `RecoverySnapshotManifestAttestation`：
  原 HEAD V2 wire 格式保持完全不变；单独 domain/HMAC challenge 绑定
  当前物理 Primary、ZK version、逻辑分区、原 HEAD 的 Snapshot
  SHA/epoch/seq 和最终 cumulative committed HEAD。
  Payload 携带精确 imageBytes 和业务基线提交 state/epoch/marker。
  MAC 在解码字段前验证；无效/过期 nonce、错配 identity、非法水位、
  修改过的 manifest、超大文件、重复/错位帧均拒绝。
- 新增 `RecoverySourceManifestControlHandler`：
  `RECOVERY_SNAPSHOT_MANIFEST_V1`，仅已有私有 Netty control port；
  读取前后要求相同 Primary/HEAD/ZK 版本，密钥物理节点独立。
  不修改旧 HEAD/DATA、Gateway、Order 等服务，不允许未经证明的
  Snapshot bytes 直接变成 READY。

**Trade** repo: `bliplink/com.app.dc.tradesvr`
验证分支：`codex/trade-safe-wal-archive-canary-20261012`
本轮提交：`8d0776ee9b4292611336268479601a33e7784e85`
新 Common 本地开发依赖下全量 **283/283 passed**，
0 failed/errors/skipped。

- `TradeRecoverySnapshotManifestSource`：
  由源端真实已持久化 JSON metadata 和文件哈希/长度生成 Manifest；
  重新核对同一 pinned HEAD，拒绝签署更改后的快照代际。
- `TradeRecoverySourceControlRouter` / `TradeReplicationManager`：
  原 V2 HEAD/DATA 控制入口增加可选 Manifest，功能默认 disabled；
  用接口 + Spring @Lazy 避免与 TradeStateCoordinator 的 bean 环依赖。
- `TradeReplicaTrustedHeadDiscovery.discoverSnapshot`：
  对当前可信 Primary 先取签名 HEAD，再用新 nonce 获取签名 Manifest，
  匹配 ZK exact version/epoch/身份后返回不可混用的结果。
- `TradeReplicaVerifiedStagingService.stageTrustedWithRequest`：
  使用签名 Manifest 的**精确长度、业务基线**和签名 HEAD 的最终
  累计水位自动生成 Common `RecoveryRequest`，
  避免调用方猜测 Snapshot 信息；完成 staged receipt 后保留
  完全相同的 RecoveryRequest 供温缓存安装。
- `TradeReplicaWarmSnapshotScheduler`：
  采用固定延迟独立 daemon、单次最多一个 partition，限制
  Full Image、WAL slot count（Common 4096 上限）、
  失败指数退避（1min 至 15min）、单分区防重复；
  读取 ZK assignment 并只操作本机 Replica/Learner；
  拒绝任何非 loopback 来源（仍缺跨容器加密通道）。
  **`trade.cluster.recovery.replica.autoWarm.enabled=false` 默认关闭**；
  不修改 matching hot path、Gateway、WAL GC 或 READY。
- `TradeStart` 只在显式配置后启动该后台调度器。

真实回环 Netty 隔离 `TradeReplicaVerifiedStagingNettyTest`：
认证物理 Primary 签名 HEAD → 认证 Manifest →
由二者构造精确 RecoveryRequest →
Snapshot 数据分块及真实 Trade `STATE_BATCH/STATE_COMMIT`
WAL → Common verifier → fsync staged checkpoint 和 seal →
Replica 本地 WAL commit proof → 原子缓存安装 →
重新打开完整业务 JSON。全链路测试 PASS，且没有对外 READY。

## 隔离 Maven 版本与本地镜像

新 Common 没有覆盖在线中央仓库版本；
新的 local Maven GAV：
`io.github.bliplink:com.app.common:3.0.17-dev6b8fe7d20261012-SNAPSHOT`

新的 local com.app.dc GAV：
`com.app.dc:com.app.dc:0.0.4-dev6b8fe7d20261012-SNAPSHOT`

本地构建目录：
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/source/{common-manifest-v10,dc-manifest-v10,tradesvr-manifest-v10}`
临时 Maven POM 中做版本替换；**原 GitHub Trade POM 仍指向
旧 0.0.4-SNAPSHOT**。因此正式 GHCR/Maven Central 发布前，
必须在独立版本链先解决依赖分发，不可直接拿分支做正式镜像发布。

Trade 本地候选：
`dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261012-autowarm-8d0776e`

镜像源码 SHA：
`8d0776ee9b4292611336268479601a33e7784e85`

新 Common Jar SHA256：
`34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`
**与当前线上仍用的 Common 361e3e3 JAR 不一致**，是有意的
新功能候选，不能宣称整套集群已被统一替换。

## 实机当前强制门禁

最新只读租户审计
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/tenants-post-manifest-autowarm-20261012.json`
：10/10 Robot RUNNING、每户 40 active orders、盘口买卖各 10 档。
Order A/B/C、Trade A/B、MD A/B/C、Gateway
容器 Running、RestartCount=0、OOMKilled=false。
没有替换运行容器。

Trade-B→Trade-A 快速恢复预检：
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/trade-preflight-after-manifest-autowarm-20261012.json`
返回 `activePartitionCount=10`, `blockedCount=10`,
`authorizesPrimaryRestart=false`，
表示十个活跃分区的 Trade-A 全量 Snapshot 均落后
（P023 B 278678 vs A 9712；P054 B 286946 vs A 0），
**无法证明现网快速接管**；此预检不含 Replica WAL
authoritative committed HEAD/ack 证明。

## 尚未完成（不能声称一口气上线完毕）

1. 在现有独立 Docker 网络命名空间之间建立明确的、可验的
   TLS/mTLS 私有恢复通道及每物理节点授权密钥分发，
   防止认证 HEAD/Snapshot 明文复制泄漏或冒名。
   Gateway 的消息透传逻辑无需修改。
2. 对一个活跃分区在 Demo 上有速率限制地实际开启 B→A 自动
   温缓存，核对源文件 SHA、持久 ZK Replica ACK、projection
   watermark、业务 StateMachine 无双主，并观察延迟/IO。
3. 真实 SIGKILL 主节点、回归、角色反转；核查
   MySQL orders/executions、资金、持仓、去重、订单、Trade/Projection
   watermarks、无双主/丢单/重复成交。完整通过后
   才能开始 Trade-B 镜像滚动替换和全镜像发布。
4. Common 的同 epoch 正常 WAL 物理封段及安全删除仍有独立
   SnapshotRetentionFence/Replica/Projection 权威水位门禁，
   **目前真实 WAL 自动删除依旧关闭**。
5. 200 租户机器人逐批压力测试必须在上述 HA 机制通过后进行；
   本轮未创建/启动 200 租户，不能报告 TPS、P99 等压测结果。

新的源端/Replica 功能默认关闭，没有删除任何在线历史数据，
没有动 Gateway 业务代码。
