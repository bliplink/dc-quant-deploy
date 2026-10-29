# T300–T308｜Common 同一 A→B→A 严格持久化、恢复、主备切换验收

日期：2026-10-29。主线：继续 T293–T299 **同一套** Mac 隔离真实三 ZooKeeper、真实不同 A/B JVM、原始私有 RSA 身份、Common 真 Netty TCP/双 WAL fsync、双签名物理 Custody/CommitIndex。**不使用 GitHub Actions；未替换或删除正式 Order/Trade 数据或容器。**

## 核心结果

| 连续阶段 | 真实 Common 动作 | 验收 |
|---|---|---|
| E4 A 主/B 备 | 原有 A/B JVM 独立 fsync/认证，双 Netty WAL、2 次 `QUORUM_DURABLE` | PASS |
| E4 B 故障 | B 原始 JVM SIGKILL；A 第 3 笔仅本地 WAL，严格 ACK 被拒绝 | PASS |
| E5 B 主/A 备 | Common 控制面自动签名 `RECOVERING`；已认证水位 2；A/B 双 RSA 快照、`REPLAY_COMPLETE`、签名回执；严格 READY；Netty 严格 ACK seq1/2 | PASS（分阶段验收调用） |
| E5 B 故障 | **运行中的真正 B Primary**、原始 E5 WAL/CommitIndex/Custody 打开，独立 A Watch 先观察 B 存活，随后真实 SIGKILL B（退出码 137） | PASS |
| E6 A 主/B 备 | A Watch **自动**签署 E6 `STRICT RECOVERING`；两个节点 fsync 588 字节业务快照、双 RSA `REPLAY_COMPLETE`；严格 READY；Netty 新业务 ACK seq1/2 | PASS（分阶段验收调用） |
| 全历史 | 全新 JVM 只读打开 E4/E5/E6 的**原始物理 WAL**、双 Custody、双 RSA snapshots，在 E5 image 中嵌入 E4 两条承诺业务、E6 image 中嵌入 E5 两条承诺业务，精确匹配 | **6 个不透明业务命令，6 个唯一、全部物理认证、没有丢失/重复，旧 E4 A-only seq3 未恢复** |

原始连续证据目录：`~/.opentradingcore/t293-live-rsa-20261029181500/`。三 ZK `manifest` 路径：`/dc/cluster/t292-20261029181500/manifest`，已从 E4 READY version 2，经 E5 `RECOVERING` version 3 / READY version 4，到 E6 `RECOVERING` version 5 / **E6 STRICT READY version 6**。原始 E4 data 目录 `strict-a/strict-b`，E5 `strict-e5-a/strict-e5-b`，E6 `strict-e6-a/strict-e6-b`。各 Epoch WAL 均**保留原始数据**，没有就地删除/截断旧 A-only 尾部。

关键输出：

- `T303_REAL_E5_B_PRIMARY_SIGKILL_A_AUTOWATCH_SIGNED_E6_RECOVERING_PASS oldConfirmed=2 ready=false newClientAck=false`。
- `T303_NEW_JVM_VERIFIED_REAL_A_RSA_E6_AUTO_FAILBACK_STAGE_PASS oldE5=2 e6Ready=false newAck=false`。
- `T304_E6_DUAL_ORIGINAL_RSA_CERTIFIED_PREFIX_ONLY_SNAPSHOT_REOPENED_PASS bytes=588 previousCommitted=2`。
- `T305_FRESH_JVM_REOPENED_TWO_ORIGINAL_RSA_E6_REPLAY_RECEIPTS_PASS snapshotBytes=588 ready=false clientAck=false`。
- `T305_OLD_E5_T292-A_REAL_PHYSICAL_CLOSED_RSA_RETIRE_PASS originalHead=2`，B 对应也通过。
- `T306_REAL_E5_B_SIGKILL_TWO_RSA_E6_A_PRIMARY_STRICT_READY_PASS zookeeperVersion=6 priorCommitted=2 clientAckYet=false`。
- `T307_REAL_B_TO_A_E6_STRICT_QUORUM_DURABLE_ACK_PASS sequence=1` / `sequence=2`；E6 B 物理 fsync 到 seq2。
- `T308_ORIGINAL_E4_A_TO_E5_B_TO_E6_A_SIX_CERTIFIED_MUTATIONS_PASS e4Committed=2 e5Committed=2 e6Committed=2 allSixDistinct=true dualRsaCustodyEveryEpoch=true oldAUnackedThirdExcluded=true originalE4WALPreserved=true signedE5E6SnapshotsChainExactly=true finalE6StrictReady=true`。

## 仅 Common 通用代码修改，无业务集群实现

1. `CommonCertifiedStrictRecoveryReceipt`：允许且只允许**真实 RSA 签名**的两类严格恢复前驱：同主 `LOCAL→STRICT` 和原主备角色互换 `STRICT→STRICT`。虚构原主 A 或跨 Epoch E6 拿 E5 签名重用的测试应拒绝。
2. `CommonCertifiedStrictReplicaAdmission`：副本准入复用同一认证前驱方法，校验物理 image、独立 RSA 恢复回执与 durable ledger，不再仅识别同主 rearm。
3. `CommonCertifiedStrictCrashReadyPublisher`：Common 冷控制面严格主备互换 READY：验证原始 E4/E5 旧主/副本 WAL 物理 Head、**已 ACK 提交水位与未 ACK 尾部之分**、两份旧 Epoch 物理退休 RSA、E5/E6 双签名基线、双恢复凭据、独立当前三 ZK 会话，再版本化 CAS；未完成任何一项均不 READY。无 ZK 轮询进入订单 WAL/ACK 热路径。
4. `examples/common-only-demo` 含 T300–T308 的真正 Docker/JVM 集成执行入口；Demo 业务快照与事件仍然只是用户注入的 `byte[]`，**Common 不限制 GTC/IOC/FOK/市价/限价，不解析资金/订单/持仓，不能把 Demo 的字节格式当成正式 Order/Trade 状态机格式**。

## 不可宣称 GO 的剩余门禁

- Common 的 `CommonCertifiedFailoverWatch` **自动**检测租约消失并进入签名 `RECOVERING`；但 T300–T307 的重放恢复、双方回执和 READY 在验收流程中仍**显式调用** Common 接口。必须将这些已认证 Common 操作绑定实际服务生命周期的 `CertifiedRecoveryCompletion` 回调，在一场完全无人介入的连续杀主场景下自动做到 `READY`，随后才有完整自动 HA GO。不能把上面的人工验收步骤说成真实生产“完全自动完成”。
- 要覆盖 B 故障时 A 单节点**仍可在明确 `LOCAL_DURABLE_ASYNC` 风险模式下继续服务**，需要另外独立的 Common 降级授权与 RPO 验收；当前 `STRICT_QUORUM` 有意拒绝缺副本时的 ACK，**没有**把它描述为继续交易成功。
- Order/Trade 正式构建与完整真实业务验收尚未执行；此前 `t178` 旧源码存在 `com.app.dc` 版本不一致，而 Order B/C 原镜像有旧 Head/Cluster 配置问题。正式标准仍是新租户自动审批、Robot 自动盘口报价和 Tape 点价、正式真实下单成交、Order/Trade A/B 自动互切并核对订单/成交/余额/持仓。

**结论：Common 真实两方向严格写入/认证状态正确性验证 PASS；全自动完成环和 Order/Trade E2E 仍 NO-GO。**
