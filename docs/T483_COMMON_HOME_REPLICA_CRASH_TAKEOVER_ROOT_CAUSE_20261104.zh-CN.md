# T483｜Home Replica 对非 Home Primary 崩溃后的自动接管：真实控制分支缺陷（2026-11-04）

## 结论

**发现并实测复现了 Common 自动 Watch 的一个独立故障切换问题；修复未提交。** 不应该继续把它归咎于 Order/Trade Spring Bean，也不应扩展新集群框架。

这是 T482 之后下一项实际发现的阻塞：对于同一分区，**当前 Primary 并不是原始 Home，而原始 Home 正在担任 Replica** 的情况，若当前 Primary 崩溃（真实 ZK 租约已退），原始 Home 必须能使用已有 Common 的 **签名 crash Stage** 接管，而不只尝试旧主在线的 cooperative Home return。

### 可复现代码路径

- `com.app.common.replication.CommonCertifiedFailoverWatch.probe()` 在 `homeCandidate` 为真时，目前**无条件**调用 `coordinator.stageHomeReturn(partition,pinnedHome)`。
- `CommonCertifiedFailoverCoordinator.stageHomeReturn(...)` 只允许 cooperative 严格签名回切，调用 `stageCooperativeRecovering`，需要当前旧主仍保持 **distinct live ephemeral lease**。
- 当前旧主真的死亡时，`requireDistinctLiveOldOwner` 拒绝离线主；Watch 的后续 catch 只尝试恢复已经存在的 stage，**从未尝试同一 Common Coordinator 已有的 `stageRecovering(partition)` crash Stage**。
- 该 `stageRecovering` 本身检查之前实际观察到活跃旧主、旧主 ZK 租约确实消失、candidate 仍为 Replica、当前签名账本/WAL 证据和新 Epoch ZK CAS；**不能直接跳过其认证条件，更不能把 Stage 等同于 READY**。

### RED 实验

新增本地 JUnit 方法 `CommonCertifiedFailoverCoordinatorTest.originalHomeReplicaTakesOverDeadNonHomePrimaryFailClosed`，以真实 Common Watch、原有可变 ZK 控制模拟器以及**现有 Demo B RSA 私钥形成的持久签名 Stage Ledger**运行。流程：原始 Home=NodeB，当前 Primary=NodeA、当前 Replica=NodeB，真实观察 old owner 曾持 lease；证明回调至少 2 次之后将 old lease 撤销；等待 Home NodeB 自动形成 Epoch 2 `RECOVERING`，并要求其他 P091 维持 READY、P090 始终 NOT_READY 直到物理 Ready 证明。

**现有 Common 版本结果 RED：13 项 JUnit 中 12 项通过、1 项失败。** 失败：
`java.io.IOException: Common automatic failover remained NOT_READY: Common partition not staged RECOVERING for this survivor`。

证据在 Mac：
- 源码 `.work/t472-common-publish-20261104/src/test/java/com/app/common/replication/CommonCertifiedFailoverCoordinatorTest.java`（新方法仅本地，**未推送正式分支**）
- 日志 `.work/t449-common-gw-rejoin/target/t483-home-crash-before-fix.log`

这是**真实 Common Watch + 持久 RSA stage 的控制层测试，ZK 是本地模拟**；不声称完成了 Order/Trade 真实生产 ZK、物理 Replica fsync 或签名 READY。

### 最小修复要求

只在 Common Watch 的 `homeCandidate` 分支选择 **同一个已有 Coordinator 的两条合法 Stage**：

1. 当当前非 Home Primary 的 ZK ephemeral lease 经真实认证已消失时，用既有 `stageRecovering(partition)`（完整 crash 校验）。
2. 当当前 Primary 仍活跃、且所有严格 RF2 物理证据齐全时，用既有 `stageHomeReturn(partition,pinnedHome)`（cooperative 签名回切）。
3. 两条路径都只产生非路由 `RECOVERING`，真正发布 READY 依旧由原有 Common `CertifiedRecoveryCompletion`、独立 RSA/Custody/CommitIndex、恢复 Snapshot/WAL、业务 replay/final CAS 控制。
4. RED→GREEN 后回归 `CommonCertifiedFailoverCoordinatorTest`、`CommonHomeReturnCensusTest`、`CommonCertifiedStrictCrashReadyCompletionTest`、Demo A→B→A 和原有 109 项基线；不能仅调整测试或禁用认证以求 PASS。

尝试修改 `CommonCertifiedFailoverWatch.java` 的分支时，WebCodex 返回 **OpenAI 安全检查拦截**，源文件实际无变化；**未尝试通过其他执行工具/远端编辑绕过拦截**。因此本轮未能实际改动 Common Watch；故意维持 RED 作为可核验证据，禁止当做已修复。

### 产品 HA 主链仍未 GO

T482 Common post-open Source Factory、Order/Trade Java8、离线镜像及 T481 实际 Demo 两次 SIGKILL 测试的旧 PASS 都有效，但不能推导出当前业务节点具备自动恢复。正式 `orderCommonCertifiedPhysicalRecovery` 和 `tradeCommonCertifiedPhysicalRecovery` 仍没有生产 Bean；实际四项 `DurablePhysicalRecovery`（signedCoordinator、independentFsyncedReplica、bothSignedPhysicalReady、recoveredBusinessWalAndSnapshot）的旧 Epoch 真实签名恢复还未交付。后续必须严格遵守 Demo 与 Common 相同代码入口、Common 持久隔离与真实签名准入，不新增业务 HA。

本轮未替换四个运行中的 Order/Trade 容器、未修改持久化业务数据或重置 Epoch；不使用 GitHub Actions。当前业务双向 HA 与 Robot 真成交依旧 **NO-GO**。

## 后续核验：T483 测试时序竞态已排除（取代前面单次 RED 推断）

复跑原始用例时，未修改 Common Watch 生产文件的情况下，有一次 **14/14 PASS**。原因不是 Watch 已修好，而是测试先等待 catchup 次数达到 2，再删除旧主租约，存在 Watch 已在旧主活着时启动合法 cooperative Home Stage 的时间窗口。因此此前单次 RED **并非确定性充分证据**。

已修改测试，加入两个 `CountDownLatch`，令 Home Watch 在**确认旧主曾经存活**后、正式进入 Stage CAS 前阻塞；测试线程先删除旧主租约，再释放 Watch。连续两轮完整测试均 **14 项中 13 项通过、1 项失败**，失败仍是 `Common automatic failover remained NOT_READY`，没有签名 `RECOVERING`；相应日志：`.work/t449-common-gw-rejoin/target/t483-home-crash-latched-red-1.log` 和 `.../t483-home-crash-latched-red-2.log`。

增加独立正向控制 `originalHomeReplicaExistingCoordinatorStagesCertifiedCrashWithoutReady`：相同 RSA 签名 Stage Ledger 和相同 ZooKeeper fixture，在确实观察到旧主活跃并撤销其租约后，直接调用现有 `CommonCertifiedFailoverCoordinator.stageRecovering("P090")`，**PASS**；Epoch 2 P090 RECOVERING (NOT_READY)，其他 P091 READY，`requireCurrentRecoveringStage` 再认证 PASS。即：**底层已有签名 crash Stage 成功，缺陷只在 Home Watch 无条件选择 cooperative Stage**。

新确定性 RED + 对照正向测试已经提交 Common `saas-crypto-latest` [9c56c03](https://github.com/bliplink/com.app.common/commit/9c56c03124faaf4ebff18435e7caca46bc7c9237)。原有在线 Home 和双签完整性测试 **11/11 PASS**，见 `.work/t449-common-gw-rejoin/target/t483-previous-home-strict-proofs.log`。

安全的最小补丁应该在 Common 原来的 **同一个 Coordinator** 内，根据当前 Old Primary 的真实 ZK Lease 是否存在选择 `stageRecovering` 或 `stageHomeReturn`，两条 Stage 都继续使用 CAS/签名 Ledger、旧 Epoch 隔离与各自原有证据门禁；所有失败保持非路由 `RECOVERING`，绝不直接 READY。不要捕获所有异常后改走另一个路径，因为这可能把证据无效、CAS 冲突或其他失败错误地降级成另一个 Stage。

本轮并未修改 `CommonCertifiedFailoverWatch.java` 的生产分支（已有执行安全检查阻断），**RED→GREEN 修复尚未完成**。Order/Trade 四容器未触动、未动现有 WAL 数据。
