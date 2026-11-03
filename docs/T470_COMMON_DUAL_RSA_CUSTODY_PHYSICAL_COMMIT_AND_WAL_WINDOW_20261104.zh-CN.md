# T470｜Common 真实双 RSA 物理提交水位与原始 WAL 区间证明

日期：2026-11-04。**Common 已提交**；Order/Trade 正式业务自动 HA 仍 **NO-GO**。不修复或迁移旧 P060，四个 Demo 业务容器保持运行。

## 本轮真实根因与代码变更

T469 消除了 Spring 在真实 Common 物理 WAL/CommitIndex/Custody 创建前构造 SourceHandler 的依赖循环，但缺少一个业务无关、可以同时在主和备读取的**可验证严格提交水位**，以及针对精确原始 WAL 区间的独立物理摘要。不能从当前 ZK owner、`forcedSequence` 或内存业务计数推出客户端已 ACK 的提交位置，也不能用已有一个物理节点的 Custody 充当完整双签名证明。

在 `bliplink/com.app.common` 的 `saas-crypto-latest` 新增两个仅供恢复源使用的只读 API（`CommonCertifiedPartitionRuntime.java`）：

1. `requireAuthenticatedPhysicalCommitHead()`：先核实 Common 当前 ZK grant、分区/epoch、Primary 未 poison；从当前 Primary 的真实 fsync CommitIndex 或 Replica 的真实本地 Custody HEAD 获得候选证书；对 **A+B 两个独立 RSA 投票**重新执行 `DurableWalCommitQuorum.verify`；重新验证本节点对应 Custody HEAD、两个物理 Custody install receipt 的持久化 Ledger；要求原始 WAL 没有 pending/uncertified tail、原始已 fsync 前缀与 RSA 证书严格相等，最后再次检查角色/旧 Epoch 授权。仅返回原始经过认证的 Commit Certificate，**不会签发新的 ACK、READY 或新 Epoch**；单向缺备份/未认证本地写不会被误认为 RF2 严格证书。
2. `requireAuthenticatedOriginalWalWindow(fromExclusive,expectedCommittedHead)`：前置重验以上物理 Commit HEAD，并强制查询水位 **恰好等于**当前可信双 RSA HEAD，最多 4096 个原始 WAL record/64MiB 区间；只从 OS 文件锁保护的本地 WAL 读取原始有序二进制记录，使用现有 Common `RecoveryWalWindowDigest` 实现计算完整区间 SHA-256，并为最后原始 record 计算 SHA-256；返回不可变窗口元数据，包括分区、epoch、被认证的提交水位、membership hash、已提交 WAL 前缀 SHA、原始窗口 SHA、末条原始字节 SHA、记录数量。读取后**再次**验证提交水位没变。对无新提交、跨 epoch、超出证书、非连续 WAL、尾部数据均拒绝。这里不声称最后原始记录一定是业务 STATE_COMMIT；仍须由真正持久化业务 Snapshot/Marker 证明该语义。
3. Order/Trade 仍只承担真正业务 Snapshot 的 byte[] 提取和恢复 Apply，以上严格物理水位、原始 WAL 与 SHA 均由 Common 完成，避免服务自建集群语义或信任订单类型。

变更文件仅：
- `src/main/java/com/app/common/replication/CommonCertifiedPartitionRuntime.java`
- `src/test/java/com/app/common/replication/CommonCertifiedPartitionRuntimeTest.java`

正式 HEAD：`bliplink/com.app.common` `saas-crypto-latest` **`fcbc4a3dec4b745a669cf0bf3396389bdca34b70`**。原始 T469 Common 功能保留不变；没有将其他未完成的 Common 本地 Dirty Worktree 文件一并提交，也没有使用 GitHub Actions。

## 实际验证及复现证据

**与提交源码相同的已 Java 8 编译 Common 增量候选 JAR**：

`/Users/kong/dc-quant-deploy/.work/t449-common-gw-rejoin/target/t470-common-physical-rsa-wal-source.jar`

SHA256 **`fcc8b369c1ba75230c570be798f26e4e1c00b9752bf227fe23004f5fb6f0c07b`**，通过 ZIP 完整性和 `javap` 两个新增接口检查；注意这是旧已认证 Common Jar 叠加新 Java8 class，而**不是** clean Maven package 或实际业务 ARM64 镜像。

| 实测 | 结果 |
|---|---|
| 新源码 Java8 完整编译与原真实双 RSA Netty 物理 WAL/Custody 测试 | **7/7 PASS**。独立 A/B 各自重新读取相同 seq=1、2 RSA votes、双 Custody、原始 WAL SHA；A/B 窗口与末条记录 SHA 完全一致；超越已提交序号或空窗口均拒绝 |
| Common 物理 Snapshot/WAL、256 Home、128:128 sources/plans、自动恢复安全门禁扩大回归 | **55/55 JUnit PASS**。首次测试进程因旧 `target/t464-sources-classes` 类路径前置造成 `NoSuchMethodError`，确认**不是源码逻辑失败**；修正为新 T470 唯一 Jar 优先后 55/55 完整重跑 PASS |
| **T470 同一 SHA** 真实三 ZooKeeper、A/B 两个 JVM 256 分区，128:128 Home 主备，每节点 10/50/200 模拟租户档位提交 | **540/540 STRICT 2/2 ACK，0 失败**；所有 256 分区的两份原始 WAL 逐字节一致，共 540 帧 |
| Order 最新候选源码 `codex/t469-order-postopen-source-wiring` 使用 T470 新 Common 全部 main Java 8 | **122/122 PASS，179 classes** |
| Trade 最新候选源码 `codex/t469-trade-postopen-source-wiring` 使用 T470 新 Common 全部 main Java 8 | **172/172 PASS，219 classes** |
| 对相同 T470 Common 的实际业务 JUnit 精选（撮合/撤单/部分成交/资金/杠杆/仓位/恢复启动门禁） | **Order 41/41 + Trade 46/46 = 87/87 PASS** |

实际来源：
- 256 严格验收 `/Users/kong/dc-quant-deploy/.work/t466-common-256-strict/20261103235203-73148/metrics.json`，随跑 immutable `common-tested-pin.jar` SHA 与 T470 上面完全一致。
- Common JUnit 回归 `.work/t449-common-gw-rejoin/target/t470-common-physical-source-junit.txt`，`OK (55 tests)`。
- Order `.work/t444-order-stream/target/t470-common-real-source-business-junit.txt`，Trade `.work/t452-trade-windowed-e2/target/t470-common-real-source-business-junit.txt`。
- 新代码 Git blob 完全等于实测本地字节：生产 Java SHA `a1d7bffad89a4f64a6dcd5ba832e9e017e4667a3`、JUnit Java SHA `75b1ae1a861a318da720d7562e191bda8da97c59`。

## 严格区分已经实现与尚缺的部分

**已实现**：Common 能在当前 A 或 B 真实物理节点单独证明同一个已经被双 RSA+双 Custody+fsync 认证的 HEAD，并计算任意受限原始 WAL 区间字节摘要；T469 后打开物理源生命周期、新 T470 物理数据完整性和 256 E1 严格复制回归均通过。

**仍未实现／不得宣称 GO**：Order/Trade 的两份 `*CommonPersistedSignedSourceEvidence` Spring Bean 仍需将真实**持久化业务 Snapshot、SourceHead、Snapshot Manifest、STATE_COMMIT/Marker 信息**与上述两个物理证据 API 关联，并匹配实际 ZK manifest version；两份 `*CommonCertifiedPhysicalRecovery` Spring Bean 还需要独立 physical replay/install + 2 RSA READY、A/B E2/E3 和自动回 Home 处理。这些之前缺失的 Bean **不能以空 Map、假 HEAD、无条件 READY 或 sourceSnapshotSeq=0 的硬编码构造方式绕过**。

此前 P090 Demo E2/E3 自动 SIGKILL 回归仍带 `LOCAL ACK` 与 RPO 风险；T470 本轮 256 写入是**健康 E1 严格提交验证**，不是故障后的 256-shard 真实业务 RPO0 验收。待所有证据 Provider + E2/E3 正式证书闭环、Order/Trade 真业务 E2E 自动互切通过后，再统一替换四镜像和清理旧 Demo 数据。

本轮四个正在运行的 Order/Trade 容器没有重启、替换或修改旧 P060。下一阶段首要是完成 Common 基于真实封存 Snapshot 元数据与 T470 物理头/区间的完整 `SourceEvidence` 实现，严禁业务自建 WAL/选主。
