# T475｜真实 Common 业务 Snapshot 排他捕获、持久引用、Order/Trade 恢复源接线和同版验收（2026-11-04）

**截至本轮：Common 真实健康严格复制和 Demo 自动双向故障切换 PASS；Order/Trade 实际业务 Replica 安装、E2/E3 一致性、资金持仓成交与 Robot 业务验收仍 NO-GO。**

## 一、架构原则及本轮改动

1. 业务 Order/Trade 只在 Common 持有认证的逐分区 commitThenApply 同一互斥区时序列化自己的业务状态。Common 不理解委托、资金或订单类型，不增加自己的业务特例，Order/Trade 不自建 HA Watch/WAL/Epoch。
2. Common `CertifiedBusinessCommandBoundary.withCertifiedSnapshot` 在真实 STRICT 双 RSA + CommitIndex + 双 Custody 头上进行捕获，阻断同分区捕获过程中的交错提交。`CommonCertifiedPartitionRuntime.sealCurrentCertifiedOpaqueBusinessSnapshot` 完成快照 fsync、SHA-256、Immutable Seal；要求非零认证 HEAD，原始空 E1 Genesis 继续用已有独立双签协议，不假造 seq0 已提交状态。
3. `CommonCertifiedOpaqueSnapshotPin` 把实际已 Seal 的 Snapshot Epoch/seq/SHA 作为不可变基线的 durable 精确引用，带单 JVM 同 pin 原子单调更新、拒绝同序号不同 SHA/倒退/不完整引用/篡改。其并非 WAL 或新的 HA 机制，也不授予 READY。
4. `CommonCertifiedAutomaticSourceWiring.fromOpenedCertifiedPhysical` 支持实际打开的 Common A/B WAL/CommitIndex/Custody + 真实落盘 Snapshot Pin + 当前经 Common ZK CAS/Watch 认证的 `Stat.version`。当快照基线固定 seq1、原始 WAL 后续 ACK 至 seq2/seq3 时，重新验证新 HEAD、返回真实 seq2/seq3 WAL，不错误固定旧 HEAD。没有快照 Pin 时 SourceData Handler 仅拒绝读取，不使用空业务镜像冒充成功。
5. Order `OrderSnapshotManager.captureAtCertifiedWriterHead`、Trade `TradeBusinessSnapshotCapture.captureAtCertifiedWriterHead` 和 `sealCommonCertifiedOpaqueSnapshot` 仅负责序列化真正业务状态。两边 `*CommonAutomaticRecoveryDependenciesWiring` 只在 Common OS-locked 物理节点实际打开后才绑定真实 SourceFactory，避免启动前伪造 SourceEvidence。

## 二、实际测试（本机 Mac / Java 8，全部在隔离测试环境）

| 验证 | 实际结果 |
|---|---|
| Common 物理 Snapshot+WAL/SHA/签名恢复回归 + ZK 控制 | **79/79 PASS**，`.work/t449-common-gw-rejoin/target/t475-common-complete-regression.log` |
| 真实物理 A/B 严格 seq1 Snapshot 捕获 / 禁止同监视器内嵌套提交 / seq2→seq3 WAL 重验 / Pin 篡改拒绝 | **7/7 PASS**，`target/t475-dynamic-source-real.log` |
| Common 的真实 ZK Manifest Stat.version 只读缓存，256 分区无额外 ZK Read，Watch 变更撤销 | **21/21 PASS**，`target/t475-source-zk-version-tests.log` |
| Order Java 8 主源码全量编译 | **122 Java 源文件 / 179 class PASS** |
| Trade Java 8 主源码全量编译 | **172 Java 源文件 / 219 class PASS** |
| Order 精选业务恢复、启动门禁、真实业务 Snapshot | **49/49 PASS**，`.work/t444-order-stream/target/t475-certified-snapshot/complete-junit.log` |
| Trade 精选业务恢复、启动门禁、真实业务 Snapshot | **62/62 PASS**，`.work/t452-trade-windowed-e2/target/t475-certified-snapshot/complete-junit.log` |
| 最新同一 Common JAR、2 JVM/3 ZK/256 分区、A/B 各128 Home、模拟 10/50/200 租户健康复制 | **540/540 STRICT 2/2 ACK，0 失败，256/256 原始 WAL 字节一致 PASS**，`.work/t466-common-256-strict/20261104072521-2162/metrics.json` |
| 同版 Common A→B→A 两次真实 SIGKILL、自主接管、E2/E3 业务续写、旧主重入追平及 E3 TCP RSA fsync | **PASS，脚本退出 0**，`.work/t449-common-gw-rejoin/target/t475-two-sigkill-run.log`、`/Users/kong/.opentradingcore/t124-live-kill-runs/20261104152551` |

本次隔离 200 模拟租户阶段实际单节点约 **45.68–46.60 TPS**、P99 **212.72–222.68 ms**；这不是 200 个真实租户或产品级 SLA。故障期间为明确的 `LOCAL ACK`，带 `rpoRisk=true` 且非回溯 Quorum/RPO0，绝不可误报成故障期严格 2/2。

**同版 Common JAR**：`.work/t449-common-gw-rejoin/target/t475-common-snapshot-barrier-pinned-source-candidate.jar`  
SHA-256：`7302b65e1f8bd812e40443b5fc8802b3e23c46bbdb0ed24242d630abf8f7e04e`  
压缩归档 CRC 检查通过，0 重复 ZIP entries，`javap` 验证新 APIs。本候选为**隔离增量合并测试 JAR，不是 clean Maven 正式构建镜像**。

## 三、正式环境状态与阻塞

- 四个现有服务容器 `otc-t453-order-b-standby-parent-watch`、`otc-t452-trade-b-windowed`、`otc-t436-trade-a-margin`、`otc-t432-order-a-restored` 仍处于 Up。本轮**未替换业务镜像**、未处理 P060 旧数据，也未触发 GitHub Actions。
- `order/tradeCommonCertifiedPhysicalRecovery` 对应的 `CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery` 真实 Bean 仍未具备可核验的 128 分区 Replica 安装、旧主证书撤权、业务 Snapshot+WAL Apply 与真实双签 READY 链路；目前没有证据证明真实 Order/Trade A/B 全链路自动 E2/E3 通过。
- 与正式业务 READY 相关的 `OrderCommonRecoveredDomainWiring` 当前仍明确只支持原始空 E1 Genesis，不能凭 E1 通过而宣称资金/委托/成交历史恢复通过。
- 下一阶段必须将已实现的真实 SourceEvidence 连接到 Common 现有的 `DurablePhysicalRecovery` / durable transaction / install ledger / signed READY，Order/Trade 仅实现业务 state machine 的真实 Snapshot restore + opaque WAL Apply，隔离验证后才能替换现有镜像，继续真实租户自动审批/Robot 报价/点价成交和最终一致性检查。

**GO/NO-GO：Common Demo+HA regression GO；完整产品业务 HA NO-GO。**

## 四、GitHub

本轮源文件已经出现在以下各仓 `saas-crypto-latest` 分支：
- `bliplink/com.app.common`：`CertifiedBusinessCommandBoundary`、`CommonCertifiedPartitionRuntime`、`CommonCertifiedOpaqueSnapshotPin`、`CommonCertifiedAutomaticSourceWiring`、`ZkNodeScopedControlPlane`、`NodeClusterControlManager` 和对应 JUnit。
- `bliplink/com.app.dc.ordersvr`：`OrderSnapshotManager`、`OrderCommonAutomaticRecoveryDependenciesWiring`、`OrderCertifiedWriterSnapshotTest`。
- `bliplink/com.app.dc.tradesvr`：`TradeBusinessSnapshotCapture`、`TradeCommonAutomaticRecoveryDependenciesWiring`、`TradeCertifiedWriterSnapshotTest`。

附注：受本机 GitHub 443 连接超时影响，部分修改经已连接的 GitHub API 分文件提交；不要把隔离工作树的本地旧 HEAD 强推覆盖现有远端分支。
