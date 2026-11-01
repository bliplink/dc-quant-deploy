# T381–T384｜Demo+Common 单分区完整认证 Home 回切：严格 READY PASS

**验收日期**：2026-11-01（Mac 本地北京时间），与现有 Order/Trade 完全隔离。  
**实际被测候选**：`.work/t374-demo-common-ha/target/t377-common-home-auto-wiring.jar`，SHA-256：`dabbd5feceb577394e64cc299354b7f2060a85d4399d4e12b14a9663da8c33a0`。  
**现有 Order/Trade 线上安装的旧版 Common JAR**：SHA-256 `7cbe13f614f0abd478b02188e15660b572f1c4519866684c3b308e92593784e6`，**本轮没有替换**。

## 一、本次真正实现的 Common 自动 Home 单分区物理闭环

- 全新隔离 Docker Compose 三节点 ZooKeeper，独立 A/B Docker JVM、独立持久化数据目录、分别持有自己真实测试 RSA 私钥。模拟 B 接管后掌管 P000–P255、A 为 P000 的原始 Home。
- A/B 的 **P000/E2 原始实体 WAL** 实际执行 FileChannel.force(true)，各自 RSA 签名并用 Common DurableWalCommitQuorum 验证 2/2。
- B、A 分别使用 `DurableWalCertificateCustody.install` 物理安装相同 CommitIndex/Custody，`signInstalled` 独立签署安装收据，`DurableWalCustodyReceiptLedger.persist` fsync 2/2 Custody 接收账本。A 的旧 Replica Custody 也是实际安装并独立可重读的原始权威来源。
- A 的 `CommonCertifiedFailoverWatch`（而非手工改 manifest）验证双份原始 WAL/收据后，在 B **仍在线**时自动将 P000 从 E2 STRICT READY CAS 到 E3 RECOVERING。B 的其余 255 个分区路由仍 READY、其会话仍 LIVE。
- B 物理关闭 **仅 P000** 的原 E2 WAL/锁后使用自己的 RSA 签 `CommonCertifiedStrictOldEpochRetirement.signAfterStop`；A 也独立关闭自身原 Replica WAL/锁并签名。Common `requireBoth` 核验两份真实退休收据的原始文件 HEAD/Stage/hash。
- `CommonCertifiedStrictCrashPrefix.inspectReadOnly` 使用原始 B+A WAL 及 A 原始 CommitIndex/Custody 双收据，确认唯一已承诺业务中性指令 `seq=1`；没有丢弃或追认任何未认证 WAL 尾部。
- A/B 各自从这个**同一物理认证的 E2 提交前缀**重建 181 字节的 E3 opaque Image、独立 fsync 与 RSA 签名，`CommonCertifiedGenesisQuorum.sealAndVerify` 双签封存，并在两个 JVM 分别 reopen。封存 Image SHA-256：`9e0e829b247673043de5b671b759b65b5202e4b0397e051d7eedcec935413c0c`。
- A/B **分别**通过 `StateMachineRecoveryCoordinator.recover`、`ReplicatedStateMachine.restore` 和 `DurableRecoveryTransactionControl` 将状态实际恢复到各自进程/文件，持久化业务 Journal，并使各自 `DurableRecoveryInstallLedger` 达到 `REPLAY_COMPLETE`。双方独立签 `CommonCertifiedStrictRecoveryReceipt.issue`，持久化两份 E3 recovery-rsa，使用 `requireBoth` 验证。
- 上述完整原始 RSA/WAL、双方退休、新 RSA Image 和双方已安装恢复证明齐全后，**相同 Common 自动 Watch** 调用既有 `CommonCertifiedStrictCrashReadyCompletion.recoverAndPublish` 和 `CommonCertifiedStrictCrashReadyPublisher`，真正完成三 ZooKeeper `P000 E3 RECOVERING → E3 STRICT READY` 的受认证 CAS。紧随其后复核两个 REPLAY_COMPLETE Ledger、两份恢复 RSA 和全部 256 分区。
- 最终：P000 新主=A，E3 STRICT READY；B 仍有有效 lease，其他 **255/255** READY 且角色/Epoch 未变。没有脚本强行直接写入 READY。

## 二、最新实测关键标记

严格测试入口（只使用隔离 Docker 与测试 RSA）：

```bash
python3 tests/run-t376-isolated-common-zk-stage.py \
 --mode home256-signedwatch \
 --worktree .work/t374-demo-common-ha \
 --base /Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027 \
 --expected-sha256 dabbd5feceb577394e64cc299354b7f2060a85d4399d4e12b14a9663da8c33a0
```

最新证据：`.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-e7ebdf15.log`。严格 Runner 必须看到以下真实标记才接受：
- `T381_E2_REAL_TWO_JVM_COMMITINDEX_CUSTODY_RSA_RECOVERY_SOURCE_PASS`
- `T382_E3_TWO_REAL_VOTERS_RSA_FSYNC_SNAPSHOT_SEALED_PASS`
- `T383_E3_COMMON_TWO_JVM_REPLAY_AND_RECOVERY_RSA_BOTH_PASS`
- `T383_E3_CommonHaDemoB_REAL_COMMON_REPLAY_COMPLETE_RSA_RECEIPT_PASS`
- `T384_REAL_COMMON_AUTO_HOME_SIGNED_E3_STRICT_READY_PASS`

实际 `T384` 标记包括 `originalWalCommitIndex=2of2 oldRetirementRsa=2of2 newImageRsa=2of2 replayLedger=2of2 newRecoveryRsa=2of2 real3ZkCas=true elapsedMs=2003`。

这是**1 个分区 P000 的闭环总耗时约 2.0 秒（同一台 Mac 上两个隔离 Docker JVM）**。之前一次约 2.504 秒的完整测试也 PASS。该耗时**不是** 128 分区总耗时，也没有跨实体物理服务器网络/故障域的证据。

## 三、仍然 NO-GO：部署 Order/Trade 的不可跳过门禁

1. **T385 真正新 E3 客户 ACK**：新 A 主在签名 READY 后用正式 Common CertifiedBusinessCommandBoundary 发新业务，经实体 TCP/Netty 复制到重新认证的 E3 B Replica；验证 B fsync、新 Epoch 2/2 WAL+CommitIndex+Custody 与 `QUORUM_DURABLE` 客户 ACK。此项的测试接线本轮被执行环境安全检查拦截，**没有完成、更不能算 PASS**。安全检查不得通过绕过或伪造证明规避。
2. **128 Home 分区**：从已经在运行的真实 Common Watch 自动顺序切回 P000–P127，分区级旧 E2/新 E3 真实独立 WAL/Custody、旧主退休、E3 Image、StateMachine Replay、双收据与最终 128/128 signed READY；统计所有分区状态、全部回切总时间/P95/P99，以及部分已完成期间的未切分区是否仍能真实写入。现在只完成 1/128 的物理闭环，不得冒充 128/128。
3. **双向完整循环**：A 挂→B 自动接管→A 追平→Home 正常回 A、B 挂→A 自动接管→B 追平→Home 正常回 B，故障中有真实业务写入/结算/ACK；验证无双主、丢单、重复执行、错账和 256 物理分区一致性。
4. **性能与边界**：ZK 节点级控制面，不进入 WAL/ACK 热路径；记录 CPU、ZooKeeper 控制 QPS、严格复制吞吐/延迟 P99。单节点只能声明 LOCAL_DURABLE 和非零 RPO 风险，不能追认严格 Quorum ACK。
5. **上述全部 PASS 才允许部署**：同一 Common 公共逻辑集成到 `saas-crypto` Order/Trade；业务服务只注入状态机，不自建 HA。Mac 本地统一编译镜像、逐台替换并验证新租户自动审批→Maker/Tape Robot 持续报价→真实下单成交→Projection→A/B 自动切换。现有 Order/Trade、Gateway、Robot **一直保持运行，不提前替换或清理数据**。GitHub Actions 暂时不使用。

**结论：T381–T384 单分区真实自动 Home + 独立双节点物理严格 READY 全链路 PASS。T385、完整 128 Home、256 分区物理一致性和业务真实交易未完全通过，整体 HA 仍 NO-GO，禁止提前替换 Order/Trade。**
