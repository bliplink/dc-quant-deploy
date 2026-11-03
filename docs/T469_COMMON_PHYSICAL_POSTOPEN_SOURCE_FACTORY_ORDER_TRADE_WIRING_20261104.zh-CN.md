# T469｜Order/Trade 接入最新 Common 的真实物理恢复源启动顺序

日期：2026-11-04（本地时间）。结论：**Common 物理恢复源生命周期接线、全 256 严格写入、单分区双向 SIGKILL 回归 PASS**；Order/Trade 的完整生产业务自动 HA 仍 **NO-GO**，旧 P060 不修不迁移。

## 1. 实际定位的代码根因

在 T468，两个服务已能使用独立双 RSA 原始 Home，但 `orderCommonPersistedSignedSourceEvidence` / `tradeCommonPersistedSignedSourceEvidence` 仍缺失。其更早的启动顺序设计存在一个结构性冲突：

- Spring `*CommonAutomaticRecoveryDependenciesWiring.physicalSignedSources(...)` 需要**在 Common 的 NodeRuntime 创建之前**生成全部 256 分区的 `HEAD/MANIFEST/DATA/PREFIX` Handler；
- 真正可信的 Source HEAD/WAL 却只能来自**本 JVM 已经打开并获得 Common ZK 授权**的 `CommonCertifiedPartitionRuntime` 及物理 WAL、CommitIndex、Custody，不可能在它们存在之前完整验证；
- 如果直接用 Spring 缓存/硬编码的 `SourceHead`、测试 Snapshot、旧 Epoch 当前 ZK 分配填补，就会引入假认证或循环依赖，这是本轮明确禁止的路径。

## 2. Common 正式代码修复（已合入）

`bliplink/com.app.common`、`saas-crypto-latest`，commit：`27c8cb51ba101757089014c61cf30017ce308954`。

修改 `src/main/java/com/app/common/replication/CommonCertifiedNodeBootstrap.java`：

- 新增 `CertifiedPhysicalSourceFactory`，为 **Common 统一的启动框架**提供一个“收到本 JVM 真实已打开物理分区后，装配真正源 Handler”的入口；不让 Order/Trade 自己监听 ZK、开 WAL、选主或证明 READY。
- 新公开 `openAndStartWithCertifiedAutomaticRecoveryFromPhysicalSources(...)`，必须先通过已有 `requireCompleteAutomaticRecoveryPreflight`（所有 Replica 真实证明计划/256 完整原始 Home），再次验证业务恢复 READY；之后验证 RSA 绑定并使用现有 Common `openAndStart` 打开物理 WAL/CommitIndex/Custody；再向 Factory 传不可修改的分区 map，逐个复查当前真实授权；最后用 `CommonCertifiedAutomaticSourceWiring.requireComplete` 检查全部本地 Primary/Replica 必需源操作，**不完整直接拒绝，Netty 尚未监听**。业务恢复再次核验，然后才开始 Common Netty 监听，最后才 arm 自动 Watch。
- 既有 `openAndStartWithZkFencingAndReplay` 和 `openAndStartWithCertifiedAutomaticRecovery` 保持兼容；没有减少双 RSA ACK、ZK 撤权、Snapshot/WAL 物理认证次数，也没有修改热路径。
- `bindCertifiedSourcesFromOpenedPhysical` 检查实际 `CommonCertifiedPartitionRuntime` 服务名、物理节点、分区、current ZK role；不允许旧分区、别人的 Replica 伪装此节点，拒绝空/缺失来源、不同步的 256 census、不可修改物理 map。异常由 Common 统一关闭已打开的 WAL/Custody/Netty 对象，不留下假成功。
- 对应 `CommonCertifiedPartitionRuntimeTest.java` 使用真实 RSA Netty、两分区独立 CommitIndex、真 fsync WAL、真封存 Snapshot 和虚报 HEAD / 缺少证据 / 冒用 B 物理实例拒绝。测试中没有任何假签名/假 READY；某些附加 Handler 测试故意抛出异常以验证没有默认认证成功，**不能当成正式恢复源接通**。

## 3. Order/Trade 源码已改到新 Common 入口（候选分支）

- Order `bliplink/com.app.dc.ordersvr`：`codex/t469-order-postopen-source-wiring`
- Trade `bliplink/com.app.dc.tradesvr`：`codex/t469-trade-postopen-source-wiring`

各修改三个文件：
- `*CommonNodeRuntimeWiring.java`：原来的 `@Qualifier("*CommonSignedRecoverySources") Map` 替换为 `@Qualifier("*CommonPhysicalSignedSourceFactory") CertifiedPhysicalSourceFactory`，使用新 Common API；仍需真实的 Replica plans 和 attested business replay。
- `*CommonAutomaticRecoveryDependenciesWiring.java`：不再在 Common 启动前构造实际来源，而是返回 Factory，待 Common 完成物理 WAL、CommitIndex/Custody 创建后，在 Common 调用时匹配 service/node/ZK 当前分区/epoch、真实本地分区数及 `requireCurrentRole()`，再统一生成原 Common 最终签名控制 Handler。**真正持久化 `SourceEvidence` Bean 仍强制存在，未绕过，也没有默认空 Map。**
- `*CommonAutomaticBootstrapGateTest.java`：验证自动模式默认开启、缺真实 Source Factory / Replica plans 即拒绝，手工 E1 保留显式选项。

**注意**：服务目前尚没有真实来源的 `*CommonPersistedSignedSourceEvidence` 或完整 `*CommonCertifiedPhysicalRecovery`，新 Factory 只修复启动生命周期，不能宣称生产 256 自动恢复已经成功。候选保持独立，未合入 Order/Trade 正式 `saas-crypto-latest`，没有构建或替换业务镜像。

## 4. 实际编译/单元与物理验收

唯一 Common 运行二进制：`.work/t449-common-gw-rejoin/target/t469-common-postopen-physical-source.jar`

SHA-256：**`f32568d7bebb2fecf495649f2e9780ecaf98049b16d1f5b366e540738e61ecc7`**。T468 最新认证的原始 Home 基础 Jar + Java8 编译的 Common Bootstrap 类；ZIP 校验、实际 javap 新 API 均通过。不是完整 Maven clean package。

| 实测项目 | 结果 |
|---|---|
| Common 新生产 Bootstrap Java8 编译及物理 Netty/WAL/CommitIndex/封存 Snapshot 用例 | **7/7 PASS** |
| Common 双 RSA Home + 物理 Snapshot/WAL + 128:128 256 源 / Replica plan + NodeRuntime 兼容回归 | **55/55 PASS** |
| **同一 T469 JAR**：3 个真实 ZK、两个物理 JVM、A/B 各 128 Primary + 128 Replica，10/50/200 模拟身份写入 | **540/540 STRICT 2/2 ACK，0 失败**；**全部 256 分区的 A/B 原始 WAL 逐字节一致、序号连续** |
| 同一 Jar：独立 P090 Demo，A `SIGKILL`→B 自动 E2→A Replica 追平→B `SIGKILL`→A 自动 E3→B Replica 重加→TCP 新 WAL fsync | **PASS，退出码 0**；E2/E3 业务 ACK 是 `LOCAL`，**不可宣称严格 RPO0/正式自动 HA** |
| Order 最新 Common 完整 main Java8 源码 | **122/122 PASS**；179 class |
| Trade 最新 Common 完整 main Java8 源码 | **172/172 PASS**；219 class |
| Order Spring 启动门禁 + 实际委托/撤单/部分成交/签名交易状态 JUnit | **8/8 Gate PASS、41/41 组合 PASS** |
| Trade Spring 启动门禁 + 实际资金/杠杆/持仓/成交/签名恢复 JUnit | **8/8 Gate PASS、46/46 组合 PASS** |

原始证据：
- 256 严格写入：`/Users/kong/dc-quant-deploy/.work/t466-common-256-strict/20261103224829-68879/metrics.json`（独立 immutable `common-tested-pin.jar` 实测 SHA 与上面**完全一致**）。
- 双向 SIGKILL：`/Users/kong/.opentradingcore/t124-live-kill-runs/20261104065010`，最后 `T272_B_E3_COMMON_TCP_NEW_WAL_FSYNCED_PASS`。
- 两服务本地 Java 编译输出 `target/t469-latest-common-physical-src`，JUnit 记录 `target/t469-physical-source-business-junit.txt`。

## 5. 仍然 NO-GO 的真实下一步

缺少 **两套**有真实物理签名/提交元数据的 `SourceEvidence` Bean（Order/Trade 各一个），以及两套独立 RSA+双 Custody 的 `DurablePhysicalRecovery`（Order/Trade 各一个）。真实 source provider 必须从已完成的 `CommonCertifiedSealedSourceData` / `CommonCertifiedPartitionRuntime.requireAuthenticatedOriginalSourceWal`、实际冻结的 Snapshot、物理 CommitIndex/Custody 取得 HEAD/MANIFEST/DATA/PREFIX，不能以纯内存状态或 ZK manifest 充当已提交 WAL。

E2/E3 还需要原 Epoch 撤权、两独立 Replica 追平、真实业务状态 Apply、两个物理 READY 回执及恢复严格 2/2；不能把 LOCAL ACK 历史回溯变为无数据损失。最终验证 256 分区故障期间持续交易与 A/B 自动互切+回 Home 后，才可用同一 Common JAR SHA 统一重建四个业务 ARM64 镜像、清理旧数据/空卷全新注册租户、Robot/Tape、交易、资金/持仓/Projection E2E 与压测。

**本轮没有修改现网四个容器、原旧 P060 WAL、ZooKeeper 原业务 namespace，也没有 GitHub Actions。**
