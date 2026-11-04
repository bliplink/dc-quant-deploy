# T471｜真实持久化 Snapshot 元数据重启恢复 + 根因：旧双记录标记协议与 Order/Trade 单记录严格 ACK 不一致

日期：2026-11-04。Common 已合入 `saas-crypto-latest`；Order/Trade 完整 256 分区自动业务 HA **NO-GO**。本轮 **不修老 P060 数据、不换现网业务镜像、不运行 GitHub Actions**。

## 1. 真正新增的代码

`bliplink/com.app.common` `saas-crypto-latest` HEAD **`fccd84ba321c8563331f178301984567f9d7e534`**，只添加：
- `src/main/java/com/app/common/replication/CommonCertifiedSealedSnapshotCatalog.java`
- `src/test/java/com/app/common/replication/CommonCertifiedPartitionRuntimeTest.java` 的真实磁盘/RSA Snapshot 读回归

`CommonCertifiedSealedSnapshotCatalog.requireExactSealed(root,physicalPrimary,partition,epoch,seq,maxBytes)`：

- 必须由真实仍存活、持有 Common 物理写者授权的 Primary 调用，先执行 T470 的 `requireAuthenticatedPhysicalCommitHead`，真实核对双 RSA fsync CommitIndex、双独立物理 Custody 安装 Receipt Ledger、本地无分叉尾 WAL 的 exact CLEAN HEAD。
- 不再从调用者内存临时拼造 `RecoveryRequest`；针对业务指定的**准确 Snapshot epoch+sequence**，直接重新读取既有 `DurableRecoverySnapshotSeal` 原子 fsync 持久化的 `.properties` 与 `.snapshot`。原始 Scope、Epoch、分区、序号、已提交业务 baseline、Snapshot 文件名和 SHA-256 必须一一对应。
- 严格拒绝不存在、重复、跨 Epoch、SYMLINK、错 State baseline、超尺寸、修改持久化元数据和完整镜像 SHA 不匹配；重新调用 `seal.verifySealed` 做整个原始 Snapshot 流式 SHA-256 校验。
- 从**物理真实认证的**水位构造只读 `RecoveryRequest` 和 `RecoverySnapshotManifestAttestation.Manifest`，保留磁盘的业务 baseline，不把任意 WAL 尾序号假造为最终 `STATE_COMMIT`；读完重新确认物理提交水位未变。
- 与 T465 `CommonCertifiedSealedSourceData` 的原始 byte[] Snapshot/WAL 源一起在真实 Netty A/B RSA/Custody 测试中完成原始镜像和 WAL 读回。该目录复用现有磁盘封存机制；**没有新的 Common 业务状态机或集群机制**。

> 安全界限：封存 Snapshot 的校验是本地 fsync + SHA 和现有 Common 物理提交水位，**并非**一个独立生成的双 RSA Snapshot 状态认证，也不能独自发布 SourceHead/READY。真正的业务最终 STATE 状态和原始 Snapshot 的业务 lineage 仍须由 Order/Trade 的真实 durable marker/业务解码器确认。这里未以单项单测冒充整套 E2/E3 物理恢复证明。

## 2. 验收记录

**唯一测试 Common 增量 Jar**（T470 已认证 Common + 新 Java8 Catalog 两个 class）：

`/Users/kong/dc-quant-deploy/.work/t449-common-gw-rejoin/target/t471-common-sealed-durable-snapshot.jar`

SHA-256 **`e01dba116e1edd5309ac67c71788115d72c2cdab32645a9a9ca6e872bf2264ec`**。ZIP `unzip -tq`、`javap` 真实 API、`git diff --check` PASS。不是完整 clean Maven 发布包或业务 ARM64 镜像。

| 验证 | 真实结果 |
|---|---|
| Common 新 Catalog Java 8 编译 + 真 Netty/RSA + 物理 Custody/WAL + fsync Snapshot reopen | **7/7 PASS**；原始封存 Snapshot 完整 SHA 与原 WAL 帧读回，并拒绝元数据改写、Replica 冒充来源、错误 Snapshot 序号 |
| Common 连同双 RSA HEAD、256 原始 Home、物理 Source Factory、Replica Plans、STRICT READY 边界扩大回归 | **55/55 JUnit PASS** |
| **同一 T471 SHA** 真实 3 ZK、两个物理 JVM、全部 256 分区 128:128 Home，10/50/200 模拟租户写入 | **540/540 STRICT 2/2 客户端 ACK，0 失败；256 分区 A/B 原始 WAL 全部 bit-exact PASS** |
| Order 最新候选使用相同 T471 Common Jar 全部 main Java8 | **122/122 文件 PASS、179 classes** |
| Trade 最新候选使用相同 T471 Common Jar 全部 main Java8 | **172/172 文件 PASS、219 classes** |
| Order/Trade 与新 Common Jar 的现有业务 JUnit | **Order 41/41 + Trade 46/46 = 87/87 PASS** |

真实测试证据：
- Common 55/55：`.work/t449-common-gw-rejoin/target/t471-snapshot-source-common-junit.txt`
- 真 256 2/2 ACK：`.work/t466-common-256-strict/20261104003115-75406/metrics.json`，同目录 immutable `common-tested-pin.jar` 的 SHA 与上面完全相同。
- Order：`.work/t444-order-stream/target/t471-common-business-snapshot-junit.txt`
- Trade：`.work/t452-trade-windowed-e2/target/t471-common-business-snapshot-junit.txt`

GitHub 源码 SHA (匹配实测本地文件)：
- Catalog：`5a9538f335dc3df940d1aad13614c736c4b945b4`
- 测试：`a147ab0765cc6e33e65ffba09383eb28b3ac2052`

## 3. 更关键的实际根因：恢复协议存在双记录/单记录语义冲突

此前 T457–T470 只通过了 Demo/Common 物理证明结构与特定 **`STATE + STATE_COMMIT` 双 WAL 记录**恢复协议，未完成将 Order/Trade 真实业务写入数据格式送入同一 Recovery Source 端到端验收。本轮对源码逐个核对发现：

- Order `OrderStateJournal.commitPreparedState`、`commitPreparedBatch`、`commitCertifiedAtomicMatch` 等使用 `physicalWriter().commitThenApply`：**每笔业务的完整状态变化由一条 `OrderJournalRecord` 原始 byte[] WAL 帧交给 Common 进行严格复制、双 RSA/Custody 持久化后 ACK**。包括独立 Match/Outbox 业务事件，不是每笔末尾再补一帧 `STATE_COMMIT`。
- Trade `TradeStateCoordinator.commitPreparedState` 使用 `commonBusinessWal.commitThenApply`：每笔是一条 `TradeJournalRecord(STATE_BATCH)`，实际 Common 严格完成提交后才应用；也没有额外独立 `STATE_COMMIT` 帧。
- 与此相反，旧恢复侧 `RecoveryQuorumCommitAttestation.Prefix` 验证 `stateSeq < committedHeadSeq`，`StateMachineRecoveryCoordinator.RecoveryRequest` 要求 final `sourceCommitMarkerSeq > sourceCommittedStateSeq`，`CommittedWalPrefixVerifier` / `VerifiedRecoveryStagingClient` 的传统解码器把 `STATE_COMMIT` 当独立协议记录。该假设适用于旧测试数据，却与真实 Common 业务写入的“**每条物理认证 WAL 帧已经是已提交的状态变化**”模式不一致。

**这不是简单在 Order/Trade 再加一个 Spring Bean 就能解决的问题。不能为通过恢复协议而编造 `STATE_COMMIT`，也不能直接放宽旧签名验证使未经认证尾部成为 committed。**

### 下一阶段必须修复的正确架构方向

1. **Common 引入明确版本化的“已认证 opaque byte[] WAL 单帧”恢复路径**：Common 的唯一物理提交证明是 T470 的严格双 RSA CommitIndex、两个 Custody install receipts、原始 WAL exact fsync 区间和真实 ZK Epoch；每条已认证的物理 WAL 帧都可以作为独立提交单元。无需业务侧另外写一条集群使用的 `STATE_COMMIT`。旧双记录版本保持兼容，不能模糊接受两种格式。
2. 恢复端仍在 **Order/Trade 业务状态机**内解码、检查并 Apply 该服务的每条业务 byte[]（订单、资金、持仓、成交等），并校验最终真实业务状态和独立签名 Snapshot lineage。Common 不加任何订单类型/余额类别判断，也不产生假的最终业务水位。
3. 新路径从 T471 的真实磁盘 Snapshot Catalog 取得有认证基础的 baseline，再从 T470 `requireAuthenticatedOriginalWalWindow` 取得物理证书边界，安全分批读取/恢复原始 WAL；验证全部业务状态后才请求真实 E2/E3 双 RSA READY/旧 Epoch 撤权与自动回 Home。
4. 两服务缺少的 `*CommonPersistedSignedSourceEvidence`、`*CommonCertifiedPhysicalRecovery` Bean **仍必须真实实现**；目前没有合入 Order/Trade 正式源码，也没有生产镜像。
5. Demo+Common 的 55,310 strict 压测和此轮 540 strict 测试只证明健康 E1 的物理严格复制；历史单分区 E2/E3 使用 LOCAL ACK，不能宣称 256 分区含业务故障中严格 RPO0 HA 已 PASS。实际 A→B→A/B 回 Home + Order/Trade 真租户 Robot/Trade/资金/Projection E2E 完成后才允许上线。

四个原业务容器保持不动，未修改旧 P060 WAL，且所有隔离压力容器已完成并清理。
