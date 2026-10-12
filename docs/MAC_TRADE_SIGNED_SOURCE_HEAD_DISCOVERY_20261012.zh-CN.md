# Mac Demo Trade HA 可信签名 HEAD 发现：Common 5a5c125 / Trade 102eebe（2026-10-12）

## 本轮已完成的实测工作

- 前轮被执行环境阻断的隔离 E2E 再次实际运行并通过：
  `TradeReplicaVerifiedStagingNettyTest` 从回环 Netty
  HEAD/DATA、完整 Snapshot + 真实 Trade `STATE_BATCH` /
  `STATE_COMMIT` WAL 传输开始，Common
  `VerifiedRecoveryStagingClient` 完整校验、fsync 暂存、
  `DurableRecoverySnapshotSeal` 持久化封存，Trade
  `TradeReplicaWarmSnapshotCacheInstaller.verifyLocalSnapshotCommit`
  验证本地 WAL 边界，`TradeSnapshotStore.installVerifiedReplicaCache`
  安装后重新打开正确，但**没有提升角色或 READY**。
  此前相关定向用例 **4/4 通过**。
- Trade 最新旧 Common `361e3e3` 候选 `e2cbf0c` 已完成
  **全量 275/275**，0 failures/errors/skipped。
- **重要协议缺口修复**：原 Common `RecoverySourceAttestation.requireVerified`
  必须由接收者预知源端完整 HEAD，不能从源端自行签名的响应
  自动生成 Replica 恢复计划。Common 加入
  `requireVerifiedSourceHead`：先对完整有界 Statement 以
  物理节点独立密钥验证 HMAC，再严格校验原随机 Challenge、
  来源 Physical Primary、ZooKeeper assignment version、
  逻辑分区及过期时间，才返回 `VerifiedHead`。
  Common 本轮 **230/230 全量测试通过**。
- Trade 新增 `TradeReplicaTrustedHeadDiscovery`：显式
  `trade.cluster.recovery.replica.headDiscovery.enabled=false`、
  ZooKeeper Replica/Learner 身份及 exact-version 检查、
  loopback source host 限制、Netty HEAD 控制请求、
  Common HMAC+challenge+源 identity 验证、事后重新读取 ZK
  并拒绝角色/version 变化。
- 更新隔离真实 Netty E2E：
  首先调用 HEAD，依当前挑战认证发现物理 Primary 自己签署的
  snapshotSeq、committedHeadSeq 与 SHA，然后进入原
  Verified Staging/Seal/WAL prefix/Replica cache 安装。
  用**全新的本地依赖**编译后，Trade **278/278 全量测试通过**。

## 提交及离线候选镜像

Common：
`bliplink/com.app.common`
验证分支 `codex/common-wal-rotation-policy-20261012`
提交 `5a5c125cc1845f507191946c9575b419f14af319`。

Trade：
`bliplink/com.app.dc.tradesvr`
验证分支 `codex/trade-safe-wal-archive-canary-20261012`
提交 `102eebe762ab0ee32d33307fec7f8bbb6bbcf1ad`。

本地离线隔离构建而非 Maven Central 公共发布：
- Common：`io.github.bliplink:com.app.common:3.0.17-dev5a5c12520261012-SNAPSHOT`
- com.app.dc：`com.app.dc:com.app.dc:0.0.4-dev5a5c12520261012-SNAPSHOT`
- Trade 临时离线源码：`~/.opentradingcore/local-ha-wal-seal-20261012-v1/source/tradesvr-head-discovery-v9`
  仅此 **临时副本 POM** 使用新 dev com.app.dc 依赖；
  原 Trade repo POM 仍指向 `0.0.4-SNAPSHOT`。
  因此 **最新 Trade feature branch 依赖新 Common 尚不能
  单独以旧公开依赖直接重新编译**；完成集成版本发布前必须保留
  独立开发依赖或一起升级依赖链。这并不构成线上已发布。

本地候选：
`dc-saas/tradesvr:cluster-dev-local-c5a5c125d-20261012-signed-head-102eebe`
源码 SHA：`102eebe762ab0ee32d33307fec7f8bbb6bbcf1ad`
Common Jar SHA256：
`629dd66737050013177b133e30edd253d2360938e4464d2c4b703dfba7ca94e7`
与线上现有 Common `361e3e3` **不同**，不可误以为都是
同一镜像依赖版本，更不能无条件统一覆盖当前 Demo。

## 明确剩余的发布阻塞

1. **认证 HEAD 发现现在只包含 snapshot SHA、seq、epoch 与最终提交
   HEAD，没有完整 Snapshot 的精确字节长度，也没有源端 Snapshot
   基线的业务 committedStateSeq/Epoch/CommitMarker**。
   必须让 Common 安全传递且认证这三个元数据和大小上限，
   然后才能**真正自动构造** VerifiedRecoveryStagingClient 的
   `RecoveryRequest`，而不是用调用者手工预先填好的字段。
2. 目前 `TradeReplicaTrustedHeadDiscovery` 为显式 opt-in 的单次读，
   尚未与 `TradeReplicaVerifiedStagingService.stage` 和
   `TradeReplicaWarmSnapshotCacheInstaller.install` 封装为自动调度。
   没有独立限流/退避/任务取消和线上效果监测，**绝不启用在线自动温缓存**。
3. Source 只允许回环地址+强 nodeKey，Mac 分离 Docker
   network namespace 的 Trade A/B 并非同一 loopback。
   需为跨容器传输提供受控 TLS/mTLS 或验证网络命名空间部署，
   不得改 Gateway 或开放私有同步明文公网端口。
4. 验证一个活跃分区的初始 Snapshot 安装到 Replica、
   中断/epoch CAS/failover+role reversal、资金持仓订单成交与
   Projection 的权威一致性之后，才可替换当前 Trade-B。
5. 正常期 WAL auto-seal/retention GC 仍未通过 HA 门禁；旧日志自动
   删除关闭、定时 Snapshot 配置保持原状。

这次**没有重启或者替换在线 Trade-B、MD 或 Gateway**。
