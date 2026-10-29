# T284｜Common E4 双 RSA 恢复回执与高 Epoch Replica 受控启动（2026-10-29）

## 本轮实际完成

**Common 的高 Epoch Replica 启动接线已补齐签名恢复凭据校验，但 E4 READY/正式 2/2 客户端 ACK 尚未发布，P0 仍 NO-GO。**

1. 新增 `CommonCertifiedStrictRecoveryReceipt`：本地节点只有在独立原始 RSA 身份、已签名 E4 Stage、当前真实 ZooKeeper E4 `RECOVERING` 版本、双 RSA E4 原始快照、自身已 fsync 的 `REPLAY_COMPLETE` 恢复账本及真实本地物理快照完全一致时，才可签发 E4 恢复回执。回执包含节点/服务/分区、Epoch、ZK Stage 版本与散列、快照 SHA256，且签名独占不可覆盖持久化。**此回执不是旧 E3 写入端的撤权证明，也不是 READY 或客户端 ACK。**
2. A、B 在两次独立 Docker JVM 里分别使用原有 `node.pk8` 签发。真实证据位于 `~/.opentradingcore/t283-e4-durable-recovery/20261029144237/a/rsa-recovery/` 与 `/b/rsa-recovery/`，每个回执 476 bytes。第三个 JVM 使用 A/B 原始公钥及现存 E4 signed Stage 交叉验证，输出 `T284_REAL_A_B_RSA_REPLAY_COMPLETE_CROSS_NODE_VERIFIED=PASS`，当前仍 `ready=false ackGranted=false`。将 B 回执最后一个签名字节篡改后，校验进程按预期异常退出，`Common strict recovery RSA signature not authentic`，证据 `~/.opentradingcore/t284-rsa-recovery-tamper-20261029150854`。
3. 新增 `CommonCertifiedStrictReplicaAdmission.requireCertified`：要求旧 E3 READY LOCAL → E4 STRICT RECOVERING 的原始签名 Stage 完整，当前 Replica 是固定两票成员之一，物理本地 E4 快照与双签名镜像相同，本节点持久 `REPLAY_COMPLETE` 完整，A/B 两份独立 RSA 恢复回执都通过校验。它只生成与目标成员摘要和 E4 绑定的不可伪造型 `Verified`，**本身没有 ZK 写权**。
4. `CommonCertifiedPartitionRuntime.openWithCertifiedRecovery` 在之前无条件拒绝 E2+ Replica 的基础上增加**仅对已经持证恢复的新 Epoch Replica**的受控路径。默认旧入口继续拒绝未经认证的 E2+ Replica，已有非零 WAL 必须有可信 custody HEAD；正式路径还通过 `NodeClusterControlManager.requireReplica(P090,E4,STRICT_QUORUM)` 校验真实当前 ZK READY grant。
5. 统一 `CommonCertifiedNodeBootstrap.openAndStartWithCertifiedStrictRecovery` 仅接受每分区已认证的 Replica 恢复凭据，同时要求业务 `CommonBusinessRecoveryReadiness`；现有低 Epoch Bootstrap 和业务签名 WAL 不变。新增测试证明缺证明时拒绝，A/B 不能复用同一签名，签名损坏、快照哈希错配拒绝。**低层单测可以注入假角色许可来验证物理接线，但不构成正式 E4 真实 ZooKeeper READY 启动证据。**

## 真实回归

- 在本机 Maven 3.9.16 / Java 8 和原有 A/B/C RSA 下，Common 全量 `mvn -q test` 退出码 0：**144 suites，635/635 tests passed，0 failed，0 skipped**。仍有老配置文件 `./control/ATSConfig.ini` 找不到的日志，但测试没有失败。
- 以本轮新候选 Common Jar 重新运行隔离 Docker 三 ZooKeeper、真实 A/B 两次 `SIGKILL`、E2/E3 Common 控制线程自动 READY、A/B 双向重加入和 E3 后续 TCP/RSA/fsync。结果退出码 **0**，原始目录 `~/.opentradingcore/t124-live-kill-runs/20261029151759`，日志 `~/.opentradingcore/p0-20261029-evidence/t284-bootstrap-recovered-replica-regression-real-sigkill.log`。业务状态再次到 **85**、7 请求、E3 seq=3；历史 E2/E3 客户端 ACK 保持 `LOCAL_DURABLE_ASYNC`，不追认旧写入 Quorum。
- Common 源码本地分支 `codex/t177-common-saas-crypto-integration-20261027` 提交 `9256c41`。本轮 Common Jar SHA256：`c16523acb75789008617332a72d64c8a81c92e5125fdafc1645da37adeca64b5`。不涉及 GitHub Actions 或正式业务镜像替换。

## 继续 P0 的硬门禁

1. **真实 E3 写入端退休：** 当前 T280 的 E4 RECOVERING 隔离验证和 T283 恢复证据均真实，但与其相关的旧 E3 A/B 并不是在同一套活跃业务 JVM 上完成运行时退休签名。不能把「旧演示容器已退出」或无执行效果的回调冒充跨 Epoch 物理 fencing。
2. **E4 STRICT READY 发布：** 需要 Common 验证原 E3 WAL 最终双端 HEAD、旧 Epoch 不可再发出成功 ACK、当前 A/B 完整持证 E4 REPLAY_COMPLETE、双 RSA 恢复回执与 ZK/Custody 授权，才允许真正 CAS E4 READY。失一条件继续 RECOVERING。
3. **严格写入验收：** 两套实际 E4 Netty JVM 启动后，新增业务需经双物理 WAL fsync、严格 CommitIndex 与双 Custody 确认后才返回 `QUORUM_DURABLE`。必须继续做 SIGKILL/自动主切和业务最终一致性。P0 GO 后才替换 Order/Trade；它们仅提供业务 `byte[]` 状态机，严禁重复实现 HA。

本轮保护了 `dc-quant-deploy` 的 96 个既有未提交路径和其他服务源工作区，未变更运行中的正式 Order/Trade 容器。
