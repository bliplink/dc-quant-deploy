# T484｜Common 恢复后物理 Writer/Source 逐分区准入（2026-11-04）

## 本轮实测与状态
**真实恢复准入问题已 RED 复现，3 行 Common 生产修复完成并通过 Java8 编译；修复后 JUnit 的执行受到环境安全检查拦截，因此仍是 `PENDING GREEN / BUSINESS NO-GO`，不部署。**

### Root Cause

`CommonCertifiedNodeRuntime` 已有按 Pxxx 做物理授权的 `requireCertifiedPartitionCensus` / `requireCurrentRole` / `requireAuthenticatedPartitionRole`。但三个单分区业务恢复入口之前均调用 `CommonBusinessRecoveryReadiness.requireBusinessRecoveryReady(service,node)`，导致 P091 未完成业务 Replay 时，P090 的确切认证物理新 Epoch Writer 或 Snapshot/WAL Source 仍被整个节点回放门禁拒绝。

- `armAutomaticPhysicalRecoveryWatchExact` → `requireInstalledAfterReady` 的幂等恢复路径。
- `installCertifiedRecoveredPartition` 的新物理 writer 安装路径。
- `installCertifiedRecoverySources` 的同一 Netty 端口重新注册真实 source handler 路径。

这是 Common 物理 recovery runtime 的问题，不涉及订单类型、余额类型，也不要求 Order/Trade 各自开发 HA。

### RED 证据

在现有真实 `CommonCertifiedNodeRuntimeTest.returnedHomeReplicaCanInstallHigherEpochPrimaryWithoutRestartingNetty` 用例中，只修改验证器，构造 **P090 有精确独立回放证明**、但 **P091 导致全节点验证器拒绝** 的情形。用 T483 同版 Common JAR 跑测试，结果 **15 个测试中 1 个失败，错误 `T484_UNRELATED_P091_NOT_REPLAYED`**。原有业务仍不能进入新 Epoch writer。日志：`.work/t449-common-gw-rejoin/target/t484-scope-red.log`。

该 RED 用例使用测试控制器签发的本地 grant 和原始测试 RSA，**不声称真实 256 分区生产物理签名已完成**。

### 修复内容（仅 Common）

将上述三处精确 Pxxx 恢复业务门禁从 `requireBusinessRecoveryReady(service,node)` 改为 `requireBusinessPartitionRecoveryReady(service,node,partition)`。接口在 T477 已有，`CommonCertifiedBusinessReplayGate` 和 `CommonDurableBusinessReplayHandoff` 会检查对应 Partition 的恢复和原始 HEAD；其默认接口实现 **仍委托原全节点 gate，未实现独立逐分区证据的对象依旧 fail closed**。

依然必须在安装前检查当前 ZK signed grant、epoch、OS WAL/Custody、旧主失权以及真正的恢复 Snapshot/WAL。**此次 3 行修改不跳过任何物理 READY 认证，也不能自行授予已有分区之外的能力。**

Java 8 `javac -source 8 -target 8` 对 `CommonCertifiedNodeRuntime.java` 编译成功，`git diff --check` 成功。尝试实际运行修复后 `CommonCertifiedNodeRuntimeTest` 时 WebCodex 返回 OpenAI 安全检查阻断，**不能声称 GREEN，也没有构建或部署 T484 镜像**。T483 Common 134/134、Demo 真实 A→B→A、256/256 严格 WAL 和 Order/Trade 52/64 回归依旧是 **T483 版本** 的通过证据，不能冒充 T484。

### GitHub
- Common [de19fff0](https://github.com/bliplink/com.app.common/commit/de19fff0cd065a5ed711a26fafa76c1436db3b50)：3 处单分区准入候选修复
- Common [7a85ca4a](https://github.com/bliplink/com.app.common/commit/7a85ca4a93f63955fd00cf7bc7d448f80ff587aa)：P091 未恢复不能阻断 P090 的测试

均位于 `saas-crypto-latest`，提交信息明确 PENDING GREEN，**不是正式发布**。

### 持续阻塞

Order/Trade 正式 `CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery` 生产执行者四项实物仍缺，不能使用 Demo 仅测试签名回调伪装：需要旧 Epoch RSA+CommitIndex+Custody、独立原始 WAL fsync、两个新 Epoch 真正 RSA 恢复收据、非空真实业务 Snapshot/WAL 恢复和 signed READY。当前运行的四个业务容器保留原镜像/数据；Order A 的 lease expired 与 Order B poisoned Primary 仍需在新数据 Demo 上按证据清理后恢复，不能自行重签或强行 READY。

**下一验收动作：**当正常测试执行环境允许，先让这个 T484 `CommonCertifiedNodeRuntimeTest` RED→GREEN，然后扩展 Common 相关 134 项、同版 Order 52/Trade 64 回归、真实 Demo HA 与 256 分区负载。只在完整 E2/E3 物理 READY+新租户 Robot Tape 交易 E2E 通过后，才允许正式业务镜像替换。

## 同轮追加审计：Demo 降级授权与 Order/Trade 真正的生产缺口

为了推进完整验收，继续逐层对照 Demo 两次 SIGKILL 成功的实际代码，而不是把一个 Bean 缺失当成全部根因：

1. Demo 脚本 `verify-real-auto-sigkill-genesis-replay.sh` 确实启动**独立第三 JVM C**（只拥有自己的 RSA 私钥）和 `CommonCertifiedIndependentWitnessWatch`。A 被杀死后 B 先调用 `CommonCertifiedGenesisSurvivorInstall.install` 做带原始旧 Epoch RSA CommitIndex/Custody 的非 READY 回放，再使用 C 的独立外部见证，由 `CommonCertifiedFailoverCoordinator.publishCertifiedDegradedReady` 发布 `LOCAL_DURABLE_ASYNC` 认证授权，随后 `CommonCertifiedDegradedPrimary` 才能对客户做本地 fsync 后 ACK（仍有 RPO）。E3 反向接管还需 `CommonIndependentLocalReverseWitness` 和真实签名/原始 WAL 追平。**这些 Common 原语已经存在，不要重写协议。**
2. 正式 Order/Trade 的 `*CommonAutomaticRecoveryDependenciesWiring` 仅消费四方法 `DurablePhysicalRecovery` 的 Bean，但业务源码里没有任何对应生产提供者；`*CommonControlWiring` 没有接 `CommonCertifiedLocalPolicyTransition` 或 `CommonCertifiedLocalReverseTransition`，与 Demo 的**第三见证降级/反向继续写入**路径不是同一条完整生命周期。因此光补一个非空 Spring Bean 无法恢复业务。
3. 更直接的业务安全限制：`OrderCommonRecoveredDomainWiring` 和 `TradeCommonRecoveredDomainWiring` 的 serving-state 校验 **硬编码只接受 E1 Genesis、seq=0/Head=0**，拒绝所有真实已成交订单或非零资金结算历史的 E2/E3 安装，即使已获得 Common 正确的签名恢复证据。必须改为依赖 Common 已完成的真实非空 Snapshot/WAL 持久回放并核对最终业务状态（水位、资金、订单、重复交易状态），不能删除验证器或伪造 E1 空数据。
4. 原 Common `CommonCertifiedDegradedPrimary.requireCurrentDegradedGrant` 对每一次本地提交都调用**全节点** replay gate；256 分区时 P091 未恢复会导致 P090 本地降级写也被阻断。现已将其改为 Common 现有 `requireBusinessPartitionRecoveryReady(service,node,partition)`，仍逐次要求 `NodeClusterControlManager.requirePrimary(...,LOCAL_DURABLE_ASYNC)` 的真实 ZK permit、lease、ackEvidence。Java 8 编译通过；[Common 2d4722e](https://github.com/bliplink/com.app.common/commit/2d4722ed789d28c6ba620ca3c3e8b8b7f36ea3e0)；**此变更未运行完整测试，未部署**。
5. T484 `CommonCertifiedNodeRuntimeTest` GREEN 仍被 Mac 执行环境安全检查拒绝，不能通过更换执行方式绕过。先前的 T483 134/134、Demo 真实双 SIGKILL、256 分区完整性属于 **T483**，不可移作 T484 的通过证据。

**当前严格目标仍 NO-GO**。不应该清除现有交易数据或在缺少认证准备时直接替换四个运行容器。只有把 Demo 已存在的 Common 物理原语与 Order/Trade 真实持久化业务回放完整连通并测试 E2/E3 后，才适合正式双次 SIGKILL + Robot 成交一致性验证。
