# T472｜Common v2 单帧提交恢复与真实压测、双 SIGKILL 回归（2026-11-04）

**状态：Common 物理层阶段 PASS；Order/Trade 完整 256 分区真实业务 HA 仍 NO-GO。**

## 范围、原则
- 保留 T471 旧 `STATE + STATE_COMMIT` 版本 1；增加显式物理认证 opaque WAL 版本 2。**不**伪造业务提交标记，**不**修改业务校验规则或建立第二套集群选主/复制机制。
- 仍由 Common 管理物理 WAL、Snapshot seal/Catalog、双 RSA、双 Custody、原始帧校验、恢复协调器及 NOT_READY。Order/Trade 只负责业务 Snapshot 的真实捕获/校验、WAL 解码及 Apply。
- 本次未替换四个业务容器，未处理 P060 旧数据，未运行 GitHub Actions。

## 已提交源码
- Common `saas-crypto-latest`：[05c204102009b962beba8e5b36feed24ed721366](https://github.com/bliplink/com.app.common/commit/05c204102009b962beba8e5b36feed24ed721366)
- Trade `saas-crypto-latest`：
  - [2171d2af40d9b329814a047b0b696430ab724118](https://github.com/bliplink/com.app.dc.tradesvr/commit/2171d2af40d9b329814a047b0b696430ab724118)
  - [acd63c4b88b92559b9ba7c2249020beeab5972a5](https://github.com/bliplink/com.app.dc.tradesvr/commit/acd63c4b88b92559b9ba7c2249020beeab5972a5)
  - [716f41049ecd36940a0eeae32642bbae81591d44](https://github.com/bliplink/com.app.dc.tradesvr/commit/716f41049ecd36940a0eeae32642bbae81591d44)

### Common v2 技术变化
1. `StateMachineRecoveryCoordinator.RecoveryRequest.opaqueFrames` 显式配置物理认证单帧协议 2；原有构造器保留协议 1，不接受非零业务快照伪造的独立 `STATE_COMMIT`。
2. `DurableRecoverySnapshotSeal` 与 `CommonCertifiedSealedSnapshotCatalog.requireExactOpaqueSealed` 持久化和重开 `format=2`，baseline stateSeq=snapshotSeq、markerSeq=0。由调用者显式固定协议，无法自动从可修改的文件名切换格式。
3. `RecoverySourceAttestation` 和 `RecoverySnapshotManifestAttestation` 在 v2 使用单独签名域，v1 保持旧签名数据格式；验证跨版本错配必须拒绝。
4. `CommonCertifiedPartitionRuntime.requireAuthenticatedOpaqueOriginalFrames` 从真实 2/2 RSA、2 Custody、fsync 原始 WAL 获取 **原始物理帧 + 业务 payload**；物理 SHA 摘要必须对原始 envelope 计算，而不是业务 payload。前后两次再次检查已认证 HEAD。
5. `CommonCertifiedOpaqueRecoveryWindow.verifiedBusinessReplay` 为已有 `StateMachineRecoveryCoordinator` 提供提前审计完整 WAL 的输入，业务解码由调用方实现。完成恢复后依然是 NOT_READY，没有伪造 READY。
6. Trade `TradeSnapshotInboundProof` 及 `TradeRecoveryStateMachine` 按请求真实协议版本校验非零业务 Snapshot；保留旧调用入口。Order 的 Snapshot 字段与 v2 baseline 兼容；未实施实际生产恢复源 Bean。

## 本机 Java 8 与真实物理证据

Common 使用现有 Demo A/B RSA 身份、真实 Netty、双 Custody、磁盘 fsync 的 12 类恢复相关 JUnit：**61/61 PASS**，总计 45.064 秒。其内：
- 非零 v2 Snapshot `P090 E1 seq=1` → 严格 WAL `seq=2` → 重启式磁盘 Catalog reopen → 原始业务帧精确 Apply **一次** → `NOT_READY`：PASS；
- v1 Snapshot 不能充当 v2、篡改 Manifest/错误 Epoch/非 Primary 来源、无独立提交标记：按预期拒绝；
- 旧 v1 Recovery/Manifest/Seal/Boundary 测试均通过。

唯一被验证的 Common v2 增量候选 Jar：
`.work/t449-common-gw-rejoin/target/t472-common-opaque-v2-tested-candidate.jar`
SHA-256 **`e3c2de2963dcdfda6e9173f2bb911bef6e3a9b2fd1c41133422cd5fb353e58b9`**；`unzip -tq` PASS，`javap` v2 API PASS，无重名 JAR entries。它是 T471 候选 JAR 增量更新，不是 Maven clean 完整发布包。

Order 使用相同 JAR，**122 Java8 源文件 / 179 classes 编译 PASS，40 项精选 JUnit PASS**；Trade **172 Java8 源文件 / 219 classes 编译 PASS，53 项精选 JUnit PASS**；Trade 新增的 v2 业务快照验证 **2/2 PASS**。

## 同一 JAR：3 ZK / 2 JVM / 256 分区严格复制压力
证据：`.work/t466-common-256-strict/20261104033940-85111/metrics.json`；脚本 `tests/run-t466-demo-common-256-strict-load.sh`。
- 共 **540/540 STRICT 2/2 客户端 ACK，失败 0**。
- A/B 分别管理 128 Home，256/256 原始 WAL 字节级一致，合计原始业务 WAL 帧 540。
- A、B 每个节点的模拟租户阶段：10/50/200；相应写入数为 20/50/200；全部 PASS。
- 该测试是**健康 Epoch1** 复制压力，不能代表故障期 RPO0 或真实 Order/Trade 的 256 分区 E2/E3。

## 同一 JAR：真实双次 SIGKILL 与追平
证据：`.work/t449-common-gw-rejoin/target/t472-real-two-sigkill-run.log`；不可变测试 Jar 由脚本现场复制。独立旧 RSA Genesis、真实 A/B/C 见证，生产 Common 自动 Watch、真实 JVM 宕机。
- A `SIGKILL` → B Common Watch E2 RECOVERING → 完整 Replay → C 证明 DEGRADED READY → B LOCAL ACK 写入，从 40 至 60：PASS。
- A 重启，以 E2 Replica 追回完整原始 E1/E2 数据，**追平 60**：PASS。
- B `SIGKILL` → A Common Watch E3 RECOVERING → 完整 Replay → C 证明 DEGRADED READY → A LOCAL ACK 写入至 **74**：PASS。
- B 以 E3 Replica 重入恢复，A 新增业务通过 TCP 复制给 B 并完成 fsync，合计 **85**：PASS。
- 故障期明确日志 `quorum=false`、`rpoRisk=true`、`localAckNotRetroactiveQuorum=true`。**不能声称严格 RPO0 或故障期 2/2 客户端 ACK**。这仍是 Demo+Common 部分分区验证，并非 256 业务分区同时自动 Home 回切。

## 当前 NO-GO / 下一段必须真实完成
1. `RecoveryQuorumCommitAttestation.Prefix`、`RecoveryStagedQuorumBoundary`、`VerifiedRecoveryStagingClient` 的旧网络 E2/E3 端到端仍假定独立 `STATE_COMMIT`。需把新 v2 签名格式贯通真实跨 JVM source staging 与双物理节点 READY，不能拿本地物理 v2 replay 冒充跨 JVM 完成。
2. Order/Trade 正式 `*CommonAutomaticRecoveryDependenciesWiring` 仍等待真实 `*CommonPersistedSignedSourceEvidence` / `*CommonCertifiedPhysicalRecovery` Bean。必须从实际业务 Snapshot lineage 和真实物理节点证据接入，不能返回 fake/empty 结果。
3. 尚未用新 Common Jar 正式替换业务 Order/Trade 镜像，未进行新租户自动审批、Robot 报价/Tape 成交、资金持仓/成交/委托/Projection 真业务 A/B 连续互切、256 分区严格一致性与自动 Home 回切。
4. 故障期单节点可用性已用显式 LOCAL ACK 证明，但严格 `RPO0` 故障场景要单独定义并验证；旧 epoch 残留不可声称已被追认多数提交。

**最终结论：T472 Common v2 非零 Snapshot + 原始 WAL 认证 Apply + 256 E1 严格压力 + Demo 双次自动故障注入 PASS；完整 Order/Trade 业务 HA 仍 NO-GO。**
