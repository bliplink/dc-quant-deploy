# T385–T386｜Demo+Common 自动 Home 后真实 TCP 严格 ACK 与第三 JVM 独立审计

日期：2026-11-01。只在隔离 Demo+Common 中验证，**现有 Order/Trade/Robot 未改动**。

## 核心结果：PASS

在 T381–T384 新生成的真实 2/2 WAL/Custody、两份旧 Epoch 退休收据、两份 E3 Image RSA、两份 E3 状态机 REPLAY_COMPLETE Ledger、新 Epoch 两份 RSA 恢复收据齐全，且 **CommonCertifiedFailoverWatch** 自动发布 P000 E3 STRICT READY 后：

1. **B 原先仍在工作的同一 JVM/同一 ZooKeeper 会话**使用 `CommonCertifiedStrictReplicaAdmission.requireCertified` 校验完整 E3 双恢复证明，并通过 `NodeClusterControlManager` 获取真实 E3 Replica Grant，再调用 `CommonCertifiedPartitionRuntime.openWithCertifiedRecovery` 启动 Netty Replication Server。
2. A 同一 JVM 使用 Common ZK E3 Primary Grant，通过 `CommonCertifiedPartitionRuntime.open`、`CertifiedBusinessCommandBoundary.commit` 向 B 的 TCP/Netty 端点发送新的 opaque 业务指令。没有用裸文件写入冒充新 Epoch 客户 ACK。
3. B 独立 fsync 新 E3 WAL 到 `seq=1`；A 得到 `epoch=3, seq=1, durability=QUORUM_DURABLE`，证明正式新 Epoch 客户写入在自动回 Home 后可继续。
4. **A/B 写入 JVM 均结束后**，用新的第三个 Java 进程 `CommonT386PostHomeAckDiskAudit`，仅加载双方原始磁盘文件和公开 RSA 身份，运行 `CommonCertifiedStrictCrashPrefix.inspectReadOnly`，成功验证 E3 主/备物理 WAL、B 原始 Custody/2/2 收据账本及准确提交指令的全部认证前缀。此审计不依赖客户 ACK 文字日志，不会重新签名，不会自行追加交易。

源文件：
- `examples/common-only-demo/src/test/java/com/app/common/replication/CommonT385PostHomeNetty.java`
- `examples/common-only-demo/src/test/java/com/app/common/replication/CommonT386PostHomeAckDiskAudit.java`
- `examples/common-only-demo/src/test/java/com/app/common/replication/CommonT378RealWalAutoHomeProcess.java`
- `tests/run-t376-isolated-common-zk-stage.py`

**最新完整复跑**：`.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-8445aa31.log`，证据包含：
- `T384_REAL_COMMON_AUTO_HOME_SIGNED_E3_STRICT_READY_PASS ... elapsedMs=2106`
- `T385_E3_REAL_TCP_NEW_PRIMARY_A_TO_B_QUORUM_DURABLE_ACK_PASS epoch=3 seq=1 clientAck=QUORUM_DURABLE`
- `T385_E3_B_NEW_WAL_TCP_FSYNC_PASS epoch=3 seq=1`
- `T386_INDEPENDENT_3RD_JVM_E3_REAL_TCP_DUAL_RSA_CUSTODY_PASS epoch=3 committed=1 originalA=1 originalB=1 ... originalCustody=2of2`

整个含 TCP 与独立启动环节的 A/B 测试中 A 进程时间约 **9.389 秒**，不同于 READY 的 **2.106 秒**，更不是 128 个 Home 的切换耗时。

## 128 分区控制门禁：PASS（但不能混淆成 128 完成）

单独在真实隔离三 ZooKeeper 重跑 `--mode home256`，用 128 个真实 Common 自动 Home Watch 同时观察 P000–P127。由于缺真实签名物理 WAL 证明，所有 Watch 都正确阻止 CAS，256 分区 READY manifest 无变化，B lease 保持有效；共享 Watch 控制调度线程仅 **2**，没有每分区独立线程膨胀。证明缺证据不误切。

然后签名 Stage 仅允许 P000 单分区进入 RECOVERING，另一分区 Stage 被 in-flight=1 门禁拒绝；256 分区 census 正确地指出 Home 并未全部完成。新 A JVM 在重启后能恢复同一持久化 Stage 而**不会**误发布 READY。

证据：`.work/t374-demo-common-ha/target/t376-isolated-zk/t377-home-control-fc223eb4.log`。包含：
`T378_REAL_3ZK_128_AUTO_HOME_WATCH_MISSING_WAL_DENIED_PASS totalPartitions=256 replicaWatches=128 unchanged=256 oldBLease=LIVE actualSharedControlThreads=2 autoEpochCas=0`。

## 部署门禁仍 NO-GO

1. 目前**只有 P000** 完成最新真实物理 Home→STRICT READY→新 E3 TCP ACK→第三方审计。没有 P001–P127 独立实体 WAL/Custody/新 Epoch Image/Replay/2/2 收据/STRICT READY，不能宣称 128/128。
2. 必须在一个连续真实 256 分区集群里**完整 128 Home 自动回切**，验证 B 运行不中断、全部真实单分区数据一致、每个 Pxxx 的新主签名 READY 和新客户 ACK、回切总耗时/P95/P99。
3. 完整双向 A/B 故障和返 Home、真实 256 分区一致性，以及 Order/Trade 业务回归尚未验收；无这些证明不得替换现有正在稳定运行的服务。
4. 候选 Common JAR SHA256 `dabbd5feceb577394e64cc299354b7f2060a85d4399d4e12b14a9663da8c33a0` 仍只在隔离 Demo 中；当前运行的 Order Common JAR SHA256 `7cbe13f614f0abd478b02188e15660b572f1c4519866684c3b308e92593784e6` 未替换。无 GitHub Actions。
