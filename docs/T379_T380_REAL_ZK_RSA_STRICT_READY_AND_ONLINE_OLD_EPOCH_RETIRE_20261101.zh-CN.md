# T379 / T380｜隔离 Common 真实三 ZK STRICT READY 与在线 Home 物理撤权

日期：2026-11-01，Mac 北京时间。所有动作发生在 **Demo+Common 隔离测试**，与正在提供真实交易的 Order/Trade、Gateway、Robot、Projection 容器完全隔离。没有更新在线 Common JAR、清空业务 WAL 或中断机器人。

## 使用的真实 Common 版本

- 源码：`.work/t374-demo-common-ha`，基线 T143，原始业务部署 JAR SHA-256 `7cbe13f614f0abd478b02188e15660b572f1c4519866684c3b308e92593784e6`。
- 最新 Demo 测试候选：`.work/t374-demo-common-ha/target/t377-common-home-auto-wiring.jar`，SHA-256 **`dabbd5feceb577394e64cc299354b7f2060a85d4399d4e12b14a9663da8c33a0`**；此 JAR **没有进入 Order/Trade 镜像**。
- 真实 ZooKeeper 使用每轮新的 Compose project、网络和 3 个独立 ZK 容器，无复用业务 ZK 根目录。测试结束已经拆除测试 ZK 容器；原始 RSA、WAL 和阶段证据保留。

## T379｜历史真实 RSA/WAL 的独立真实 ZooKeeper STRICT READY

新增测试 `CommonT379RealZkStrictReadyFixtureProcess`，入口 `tests/run-t376-isolated-common-zk-stage.py --mode historical-strict-ready --signed-fixture /Users/kong/.opentradingcore/t293-live-rsa-20261029181500`。

- T293 是过去真实 A/B 实际签出的、已持久化的真实 WAL、旧 Epoch 双退休签名、独立双恢复签名、新 Epoch 双签名封存 Image、CommitIndex/Custody、不可变签名 Stage 的**历史测试证据**；本次先将其完整复制到临时隔离目录，原始文件不写入。
- T293 的签名 Stage 含固定 `/dc/cluster/t292-20261029181500/manifest` 与固定 ZK 版本；最初直接在全新版本 0 的 ZK 上验证被正确拒绝。改为**仅在完全隔离的测试 ZK 中**重现其历史 `beforeVersion`，再写入**完全相同的原始 RSA 签名 RECOVERING 字节**，不修改签名文件、不伪造客户 ACK。
- A 作为独立 JVM 保持独立 E5 Replica ZK 会话；B 另一独立 JVM通过 `CommonCertifiedStrictCrashReadyCompletion.recoverAndPublish` 与 `CommonCertifiedStrictCrashReadyPublisher.publish` **真正核验原始的 2/2 RSA/WAL+Custody、旧 E4 退休收据、新 E5 两份恢复收据、封存 Snapshot 和签名前序**，最终完成真实三 ZooKeeper `E5 RECOVERING → STRICT READY` 的一次 CAS。
- 证据：`T379_REAL_ZK_T293_RSA_STRICT_READY_CAS_PASS epoch=5 signer=historical-original-A-B originalDualRetirement=true newDualRecovery=true sealedImage=true custody=true independentZkSessions=true elapsedMs=139`。原始日志：`.work/t374-demo-common-ha/target/t376-isolated-zk/t379-actual-strict-ready-0bd101e7.log`。

**严格范围：以上证明现有真实 RSA 证据的 Common STRICT READY 发布器不依赖内存伪造的 ZooKeeper。它不是本轮新 P000 在线 Home 的 READY，不证明 256 份物理 WAL、128 个真实 Home 或任何交易系统切换时长。**

## T380｜真实在线 Home 中 A/B 独立 fsync WAL 锁退休

延伸之前 T378（在真实三 ZooKeeper 中，两个独立测试 Docker JVM 先 fsync 同一 P000/E2 原始 opaque WAL，并分别以 A/B RSA 签名，经 Common `DurableWalCommitQuorum.verify` 证明 2/2，最后由 Common Watch 自动 E3 `RECOVERING`）：

1. **旧 Primary B** 在 Watch 自动 CAS 之前持有原 E2 `P000` 的真实 WAL 文件锁、独立 ZK EPHEMERAL lease；CAS 为 E3 `RECOVERING` 后，B 才关闭自身 **P000** WAL 文件句柄并调用 Common `CommonCertifiedStrictOldEpochRetirement.signAfterStop`。签名严格绑定最新真实 E3 ZK manifest、已持久化的 A 原始签名 Stage、旧 Epoch E2、真实 P000 WAL 文件的 SHA256 和 seq=1；产生 B 独立 RSA 退休收据并 fsync。B ZK 主进程/会话和其他 255 分区不停止。
2. **原 Replica A** 在自身 Watch 获取真实签名 E3 Stage 之后才关闭自己的 P000/E2 WAL，再由不同 RSA 私钥调用同一 Common 退休签名接口并 fsync；随后 A 以旧 B Primary / 旧 A Replica 顺序运行 `CommonCertifiedStrictOldEpochRetirement.requireBoth`，证明双方旧 Epoch 已按该 WAL HEAD、该版本 Stage 独立退休。
3. A/B 两份新的真实退休签名文件分别保存于
   `target/t376-isolated-zk/t378-physical-b43ae475/a/old-epoch-retirement/CommonHaDemoA-epoch-2.retired-rsa` 和
   `target/t376-isolated-zk/t378-physical-b43ae475/b/old-epoch-retirement/CommonHaDemoB-epoch-2.retired-rsa`。
4. 证据：`T380_B_P000_OLD_PRIMARY_REAL_WAL_CLOSED_RSA_RETIRED_PASS epoch=2 closed=P000 otherShards=255 BLease=LIVE`、`T380_BOTH_OLD_E2_P000_REAL_FSYNC_WAL_RETIRED_RSA_PASS oldBLease=LIVE primaryB=closed replicaA=closed head=1 oldEpoch=2 nextEpoch=3 newRecoveryReceipts=MISSING customerReady=false`。
5. 原始日志：`.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-b43ae475.log`。这套真实测试**同一台 Mac 上的独立 JVM/独立磁盘目录**，尚不是跨两台实体主机互备。

**本轮明确没有**新造 E3 严格 READY、没有拿旧 T293 的签名来给 P000 授权、没有伪造 E2 Custody 或 E3 恢复收据。即使两份 E2 真实退休签名 PASS，P000 仍必须保持非 READY。

## 业务状态

已完成只读巡检，Order A/B、Trade A/B、Gateway、Projection、Robot 连续运行；EBAUU3、NWQYBB 两租户 Robot 为 `RUNNING/40` 且成交执行记录与 distinct ExecID 一致。C8SMUE 仍然 STALE、0 挂单，不得声称该租户恢复。运行中 Order 的 Common SHA-256 仍为 T143。

## 部署 Order/Trade 之前**必须全部通过**的门禁

1. 本轮真实 P000 E2 **双份 CommitIndex + Custody 实体签名及持久化**：通过独立实际 WAL fsync 的 A/B 签名和每个节点的正式 CommitIndex/Custody 安装流程，不能只有两个 WAL HEAD 单据。
2. E3 双物理节点各自恢复真实 Snapshot+WAL、业务中性状态机 Apply 与 REPLAY_COMPLETE ledger；双方各自签 E3 新 RSA recovery receipt；完整双签 Image Seal。仅在这时复用现有 Common `CommonCertifiedStrictCrashReadyPublisher` 完成真实 ZooKeeper E3 STRICT READY；B 仍服务其余分区。
3. 在**真实 256 分区、真实物理数据**上完成无人手工干预的 A 故障→B 接管→A 追平→自动按 Home 回 A 的 128 个分区，记录全部分区实际 READY、全程总秒数、P95/P99、部分进度时 255 分区持续提供服务；再从 B→A→B 反向重复，不能丢单、双主或重复成交。只回切 1 个 P000 的成功，不能代替 128 个完整回切。
4. 全面覆盖严格 2/2 物理 ACK，避免 ZK 进入 WAL/ACK 热路径，并确保单节点可安全 LOCAL_DURABLE 工作但**如实标明非零 RPO 风险**。
5. 通过之后，把本地 Common 标准版本集成到 **同一 `saas-crypto` 分支的 Order/Trade**（只有业务 state machine，不自建选主），本地统一编译两套镜像，逐台替换当前 Demo，然后用新租户自动审批、Robot Maker/Tape、真实交易、Projection 和实际 Order/Trade 双向切换做最后验收。GitHub Actions 暂不使用。

**总体状态：T379 独立真实 ZK 历史严格 READY PASS；T380 本轮 P000 在线旧主及旧副本真实退休 PASS；本轮新 E3 完整 RSA 签名 READY 和真实 128 分区 Home 尚未通过。部署 Order/Trade 仍 NO-GO。**
