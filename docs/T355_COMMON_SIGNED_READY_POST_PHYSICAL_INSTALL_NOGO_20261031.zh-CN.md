# T355｜Common 自动主切 READY 之后必须安装本地物理分区与业务状态（2026-10-31）

> **代码完成、定向回归 PASS；完整自动 A/B 互切、Home 回切和 Order/Trade 交易仍 NO-GO。** 依照 `COMMON_AB_HOME_PRIMARY_AUTO_FAILBACK_ARCHITECTURE_20261031.zh-CN.md`，不得再创建第二套选主、业务恢复协议或修改 Gateway 透传。

## 发现的真实闭环缺口

- `CommonCertifiedFailoverWatch.completeStagedRecovery` 原逻辑在 `CommonCertifiedFailoverCoordinator.requirePublishedReady(stage)` 成功时立即 `ready=true` 并退出 Watch。**这只证明当前 ZooKeeper 的签名 RECOVERING→READY CAS，不能证明该 JVM 的新 Epoch WAL writer、Snapshot/WAL 回放、订单与账本状态已经实际安装。**
- 发生“先签名 READY，随后 JVM 在本地物理安装前中断”的崩溃窗口时，旧 Watch 重新启动仍直接视为完成，物理分区留在旧 Epoch，网关可读到 READY 但业务 ACK 无法恢复。
- T351/T354 已有 `CommonCertifiedNodeRuntime.installCertifiedRecoveredPartition` 和 `installCertifiedRecoverySources`，但它们尚未由 Watch 统一的后置完成门禁触发，留下签名控制与本地运行时不一致。

## 修复：不增加新控制面

Common 本地 commit **`2bb029f`**：

1. `CommonCertifiedFailoverWatch.CertifiedRecoveryCompletion` 新增兼容的 `default requireInstalledAfterReady(Stage)`。Watch 保留旧签名 Stage：若 READY 尚未发布，原 `recoverAndPublish` 仍必须完成独立 RSA、旧主隔离、实际业务回放与 CAS；若 READY 已经发布，则**不再重复发布 CAS**，而是继续调用本地后置安装校验。仅此校验通过才 `ready=true` / Watch 结束。
2. `CommonCertifiedNodeRuntime.armAutomaticPhysicalRecoveryWatch` 将已有 `CommonCertifiedStrictCrashReadyCompletion` 等签名发布回调与同一节点物理运行时安装相结合。仅接受恢复来源返回的真实下一 Epoch 物理运行时和**已有** `CommonBusinessRecoveryReadiness` 验证器；复用内部单分区原位换代及现有 Netty listener。中断后的同一已安装物理分区只允许在新 Epoch 与业务证明依然有效时幂等完成。
3. 此改动**不**自己伪造新物理恢复凭据、不生成签名、不复写旧 B WAL、不推断交易成功；若无恢复后的双节点 WAL/RecoveryReceipt/READY，仍然拒绝。

## 定向真实回归

`CommonCertifiedFailoverCoordinatorTest.signedReadyMustWaitForPhysicalBusinessInstallAndRetryWithoutSecondCas`：

- 原独立 NodeB RSA Stage，故障旧 NodeA 后进入 E2 RECOVERING；实际 ZK Fixture CAS 进 READY；在**本地物理安装条件故意拒绝**时，Watch 必须继续未完成并重试，不能重复写 READY。
- 本地物理安装验证解除后，相同 Watch 完成，Ready 回调成功，并确认签名 CAS 发布**恰好一次**。
- Maven 原始 RSA 测试路径复用原始 Demo：`CommonCertifiedFailoverCoordinatorTest 8/8`、`CommonCertifiedStrictCrashReadyCompletionTest 4/4`、`CommonCertifiedNodeRuntimeTest 14/14`，总计 **26/26 PASS，0 failures/errors**。测试 ZK 用代码内存状态机，不能当真实 ZooKeeper/完整自动 A/B 通过。
- Common 全量回归与 Order/Trade Java 兼容测试结果以当前 turn 的最终 exit code 补充记录，不能从上述定向回归推断全链 GO。

## 下一项真阻塞（不可混淆为已经完成）

- 现有 `CommonCertifiedFailoverCoordinator.stageRecovering` 仍要求旧 Primary **整节点 ZK lease 消失**。A/B 每节点同一时刻既是 128 分区 Primary 也是 128 分区 Replica：当 P193 单分区故障或已恢复 Home A 要归主、B 还正常承担另 128 主时，**不能杀 B 整节点来取得授权**。必须在唯一 Common 主备控制面内实现**分区级可验证的当前持有者协作交接/撤权**，保留旧 Epoch fencing 与已 ACK CommitIndex + 双签 Custody。
- 现有 Order/Trade Spring 未将 `CommonCertifiedFailoverWatch` 与实际恢复后的 Common 物理/业务回调接入常驻运行时；旧的 RECOVERING 单独空 Handler 模式无法完成这条生命周期。Common 自动 Watch + Snapshot/WAL + 回主须做成通用 byte[] 流程后在 Order/Trade 使用。
- 真实验收必须在两个 JVM/真实 ZooKeeper 下完整跑 256 分区，A 挂 B 接管、A 追平自动回 128/128、B 挂 A 接管、B 追平回 128/128，并通过冷启动续单、资金/仓位/订单/成交一致性。
- 在线 Order T335、Trade T336 与停运 Robot 本轮保持不变，原 P193 A=22667/B=22668 的无双签尾部保留。**NO-GO 时不替换在线 Order/Trade 或宣布交易恢复。**
