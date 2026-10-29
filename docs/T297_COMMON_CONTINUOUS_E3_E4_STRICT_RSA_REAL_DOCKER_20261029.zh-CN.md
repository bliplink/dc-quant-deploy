# Common T293–T297｜同一组真实 A/B E3→E4 STRICT 连续验收

**日期：2026-10-29**。范围：隔离 Mac Docker 三 ZooKeeper、真实 A/B 独立 JVM、Common 自有恢复/签名/角色/WAL/Custody/Netty。**结论：Common 第一关（活旧 Epoch 退休→同成员恢复→E4 STRICT READY→新业务双物理 ACK）通过。完整 HA P0、Order/Trade 实际交易验收仍 NO-GO。**

## 必须保留的原始证据

- 单一实验根目录：`~/.opentradingcore/t293-live-rsa-20261029181500/`。唯一 ZK 命名空间：`/dc/cluster/t292-20261029181500`，现存真实 3 ZK 仍运行。公共签名凭据：`shared/public/`、`shared/heads/`、`shared/stage/signed-stage/`、`shared/retired/`、`shared/e4-votes/`、`shared/e4-sealed/`。
- A/B 原始独立测试物理卷：`a/`、`b/`；原始 E3 WAL `business-e3.wal`、E4 `e4-image/`、E4 恢复 `e4-recovery-ledger/` / `e4-checkpoints/` / `e4-recovery-rsa/`，以及两端**独立、不共享**的 `private-test-identity/test-only-node.pk8`。这些 RSA 身份只属于隔离实验，节点本地以 0600 文件权限 fsync 保存；实验从未使用或覆盖用户现有业务 RSA 密钥，也未把私钥放入共享卷。
- E4 新业务物理 WAL：`strict-a/CommonTestSignedCutover/T292-A/P090/epoch-4/business.wal` 与 `strict-b/CommonTestSignedCutover/T292-B/P090/epoch-4/business.wal`。B 的 Custody 与两份 RSA 回执保存在 `strict-b` 的 Common 标准持久目录。

## 本轮连续 PASS 的真实范围

1. **T293 活 A/B 真实签名退休：** 两个独立 Docker JVM 分别 fsync E3 WAL 并用自己的 RSA 签 HEAD。Common 验证原始两份 WAL 和签名 Stage，三 ZK 上实际 CAS 到 E4 STRICT `RECOVERING`，A/B Watch 自动撤销 E3 角色，关闭旧 WAL，并分别签发旧 Epoch RSA 退休回执。A/B JVM 退出码均为 0。新 JVM 分别重新打开**同一节点自己的原始测试身份**，与老 E3 签名成员公钥匹配，结果：`T293_FRESH_E4_T292-A_JVM_REOPENED_SAME_LOCAL_RSA_IDENTITY_PASS` 和 `T293_FRESH_E4_T292-B_JVM_REOPENED_SAME_LOCAL_RSA_IDENTITY_PASS`。
2. **同成员 E4 双 RSA 业务基线：** 在新 A/B JVM 分别使用 E3 已认证 WAL 重建测试业务不透明状态（1 帧，47 字节快照），各自在原始物理卷 fsync E4 image 并签名，Common 两份签名封存并由全新 JVM 只读 reopen。三条结果：`T293_E4_T292-A_SAME_ORIGINAL_RSA_SIGNED_FSYNC_IMAGE_PASS`、B 对应 PASS、`T293_TWO_INDEPENDENT_ORIGINAL_RSA_E4_BASELINE_REOPENED_PASS`。测试用业务状态机只有 `byte[]`，Common 不包含订单/TIF/余额逻辑。
3. **T294 E4 真实 Common 恢复事务：** A/B 各自通过 `CommonCertifiedStrictBaselineInstall`、`StateMachineRecoveryCoordinator`、`DurableRecoveryTransactionControl`、实际 fsync 业务 journal 和 `DurableRecoveryInstallLedger` 完成 `REPLAY_COMPLETE`，分别用本节点原 RSA 签恢复回执。全新 JVM 重新打开 A/B 账本、快照与最终业务状态，全部 PASS。在这一阶段仍为 `READY=false`。
4. **T295 E4 正式 READY：** 两个独立真实 ZooKeeper session 持有 A/B 当前 lease 后，Common `CommonCertifiedStrictReadyPublisher` 逐一验证旧 E3 双 RSA 退休证书、签名 Stage、E4 双 RSA 快照、E4 A/B 双 RSA `REPLAY_COMPLETE`、当前 3ZK RECOVERING 版本，并真实 CAS 到 `E4 STRICT READY` version=2。标记 `T295_REAL_LIVE_E3_RETIRED_DUAL_RSA_E4_REPLAY_STRICT_READY_CAS_PASS`，没有冒发客户端 ACK。
5. **T296 真实两 JVM 新业务严格写入：** E4 B 通过 `CommonCertifiedStrictReplicaAdmission` 校验独立原始物理恢复凭据、当前真实 Common ZK Replica 角色才启动 Netty。A 使用同一份 Common Jar、原始 A RSA 身份、Netty TCP、真实 WAL fsync、CommitIndex、双物理 Custody 写入**两条新的不透明业务命令**。两个新客户端提交均返回 `QUORUM_DURABLE`（seq1、seq2），原始 B WAL fsync 达 seq2。标记 `T296_SAME_LIVE_E3_TO_E4_A_B_QUORUM_DURABLE_ACK_PASS sequence=1|2`；两个 JVM 退出码为 0。
6. **T297 严格故障：** B 在完整重启并读取旧 seq2 后实际被 SIGKILL，A 随后发起第 3 笔写入，没有 B 确认，因此拒绝任何客户端 ACK。原始 A WAL seq3、B WAL seq2。`CommonCertifiedStrictCrashPrefix` 只读打开两端旧 WAL、B 的真实 RSA CommitIndex/Custody 和双方独立签名回执，只证明已提交 seq2，认证恢复结果只包含 T296 两条新命令，排除 A 第三条未确认尾部，不修改任何原始数据。结果 `T297_SAME_LIVE_E3_TO_E4_AFTER_B_SIGKILL_CERTIFIED_PREFIX_ONLY_PASS committed=2 APhysical=3 BPhysical=2 unackedTailExcluded=true`。

## 仍未验收的门禁（不可掩盖）

- **Common 第二关：** B SIGKILL 后，Common 必须以已认证的 E4 HEAD=2 封存 A 未确认尾部，恢复 B、自动取得新安全 Epoch 授权，继续业务，并真实完成 A→B→A 双向自动故障切换，无丢已 ACK 业务、无重复业务、无双主。这次只验证了提交前缀及拒绝虚假 ACK；**没有**实际完成 B 自动追平和双向互切。
- **Order/Trade 第三关：** 当前正式 Docker `dc-saas-ordersvr-b` 退出码 1，日志主因：`Common physically fsynced WAL head mismatch`（不能用略过 WAL 校验来修）；`dc-saas-ordersvr-c` 退出码 1，日志主因：旧 `order.cluster.lifecycle.enabled` 仍开启，触发 `COMMON_ONLY_LEGACY_CLUSTER_STILL_ENABLED`。Trade A/B 当前运行。修复前应构建一致 Common Jar 的新镜像，在新隔离数据目录验证后再正式替换。最终标准：新租户自动审批、Robot 自动报价/Tape 点价、真实下单成交、Order/Trade A/B 自动互切并保持资金/持仓/委托/成交一致。

没有使用 GitHub Actions，没有重启、覆盖或删除正式 Order/Trade 容器，没有把历史 `LOCAL_DURABLE_ASYNC` ACK 冒充严格 2/2 提交；修改限于 Common 的 Demo 验收入口和证据文档。最终 P0 **NO-GO**。
