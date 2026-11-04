# T472｜Common 单帧已认证 WAL 恢复：真实物理窗口阶段验收与后续阻塞（2026-11-04）

## 范围与约束
- 目标仍是 T472 的五项：单帧认证 WAL 协议；真实业务 Snapshot/WAL；Order/Trade E2/E3 安装；256 分区双向自动 HA；业务状态一致性。
- 本次 **未替换** 四个 Order/Trade 容器（otc-t453-order-b-standby-parent-watch、otc-t452-trade-b-windowed、otc-t436-trade-a-margin、otc-t432-order-a-restored）。**未处理 P060 旧数据**，未运行 GitHub Actions。
- 只允许 Common 处理物理 WAL、Snapshot、认证、恢复和选主；Order/Trade 只解码、校验、Apply 业务原始 byte[]。

## 已完成并提交
1. Common `CommonCertifiedOpaqueRecoveryWindow`（新增类）：
   - 消费 T471 从真实磁盘重开的 `CommonCertifiedSealedSnapshotCatalog.Verified`；
   - 从 **真实 Current Primary** 要求 `requireAuthenticatedPhysicalCommitHead`，认证双 RSA、双 Custody、exact fsync WAL head；
   - 调用 `requireAuthenticatedOriginalWalWindow` 严格验证 Snapshot 后原始 WAL 的连续物理已提交区间；
   - 在读前和读后检查 Primary 身份、Epoch、membership、commitPrefix 与 waterline 不变；无提交标记的单帧 WAL 可以作为物理已提交数据；
   - **仅提供物理证据，不 Apply 业务、不发布 READY**，旧 `STATE+STATE_COMMIT` 机制保持不变。
2. 在 `CommonCertifiedPartitionRuntimeTest` 实际 Netty A/B 双 RSA/Custody 测试中增加 v2 原始业务 WAL 的断言，拒绝 Replica 冒充来源。

GitHub：
- [Common 源码提交](https://github.com/bliplink/com.app.common/commit/ae756c9b61c8f898d44f2b6f2ec74272d121119a)
- [Common 实测断言提交](https://github.com/bliplink/com.app.common/commit/1ef3f342c6e14d25fa93bb012481e3d9165b5d92)

## 实测证据
- JDK：本机 Zulu 8 1.8.0_504，`javac -source 8 -target 8`：新增 Common 类与测试均 **编译 PASS**。
- 使用已有 Demo A/B 物理 RSA 密钥（只读）运行 `JUnitCore com.app.common.replication.CommonCertifiedPartitionRuntimeTest`：**7/7 PASS，26.081s**，带输出 `T472_REAL_OPAQUE_SINGLE_FRAME_PHYSICAL_WINDOW_PASS`。
- 验证覆盖真实 Netty、两个 RSA 投票者、Custody、Snapshot 物理 fsync seal/SHA、原始 WAL 序号 1 的物理 committed HEAD、Replica 拒绝。日志路径：`.work/t449-common-gw-rejoin/target/t472-singleframe/junit4-real.log`。
- **无 `-Dotc.demo.existing.keys` 的初次 7/7 JUnit 仅为 Assume 跳过，不能算测试**；其后已补真实 RSA 配置重新运行，完整执行 26.081s。
- **未运行 T472 的 256 分区双向自动 HA 或完整真实业务 E2E**。T471 的 540 strict ACK/256 字节一致性是前一版物理健康写测试，不是本次业务 E2/E3 GO。

## 源码核查后的未完成项（严格 NO-GO）
1. T471 Catalog、DurableRecoverySnapshotSeal 和 RecoverySnapshotManifestAttestation 仍是 **legacy snapshot format=1**，其非零 Snapshot 基线隐含 `baselineStateSeq=snapshotSeq-1` 与独立 `STATE_COMMIT`。因此本次单帧物理窗口通过**不代表真实非零 Order/Trade 快照恢复已经接通**。必须明确新旧协议版本并从磁盘持久格式起贯通到签名 Manifest、HEAD 和 staging 验证，而不是伪造 marker。
2. `StateMachineRecoveryCoordinator.RecoveryRequest` 仍强制 `sourceCommitMarkerSeq>sourceCommittedStateSeq`；`SnapshotRecoveryBoundary`、`RecoveryQuorumCommitAttestation.Prefix`、`RecoveryStagedQuorumBoundary`、`CommittedWalPrefixVerifier` 的旧恢复签名亦按双记录语义。不能直接解除验证门禁或把原始业务 WAL 尾部冒充标记。
3. Order/Trade `*CommonAutomaticRecoveryDependenciesWiring` 仍依赖 `order/tradeCommonPersistedSignedSourceEvidence`、`order/tradeCommonCertifiedPhysicalRecovery`，正式业务源码没有定义对应真实提供者 Bean。必须按同一 Common API 提供真实磁盘证据、业务状态机 Apply，不能返回 fake/empty success。
4. 尚无新 Common v2 与 Order/Trade 共用 Jar SHA 的 clean 全量业务镜像，更没有真实 Order/Trade A→B→A、连续写入、E2/E3 严格 ACK/降级语义、Home 切回、256 分区资金/委托/成交/Projection 一致性验收。**整体 GO=NO**。

## 最终原则
真实已提交 WAL 帧以现有 Common 双 RSA、双 Custody 和 original fsync WAL 为唯一物理权威；业务只在认证后解码/Apply。保留 legacy 接口兼容，协议显式版本化，任何无真实签名/无业务 Snapshot lineage/无 E2/E3 Ready 证据的场景都继续 FAIL CLOSED。不得以 7/7 物理单测冒充五项完整交付。
