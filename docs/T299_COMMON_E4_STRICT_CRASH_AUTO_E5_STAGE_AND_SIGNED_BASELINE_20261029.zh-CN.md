# T298–T299｜E4 STRICT 故障后 Common 自动 E5 Stage 与双节点认证快照

**日期：2026-10-29｜验收级别：Common 故障后非 READY 恢复准备 PASS；完整自动主备/业务 GO 仍未通过。**

## 真实原始数据与不变边界

前序 T293–T297 的**同一套**隔离 E3→E4 实例：ZooKeeper `/dc/cluster/t292-20261029181500`、物理证据 `~/.opentradingcore/t293-live-rsa-20261029181500/`、RSA 成员 A=`T292-A` / B=`T292-B`。E4 两笔客户写入都取得真正的 `QUORUM_DURABLE`，B 的 WAL/CommitIndex/Custody 物理 HEAD 为 2。B 实际 SIGKILL 后，A 第三笔只存在自己的原始 WAL（A=3、B=2），**没有双签名客户端 ACK**。Common `CommonCertifiedStrictCrashPrefix` 在真实原盘上验证提交水位 **2**，绝不追认 A-only seq3、绝不截断/修改旧物理 WAL。

## T298｜自动故障进入 E5 严格 RECOVERING

- 先尝试重新以旧 A E4 正式 `CommonCertifiedPartitionRuntime` 打开原始 A WAL，**启动被 Common 正确拒绝**：`Common physically fsynced WAL head mismatch`。这证明 Common 没有错误放开 A-only seq3 的热写入口；**不是安全可忽略的异常**。在获得新认证 Epoch 之前，不得使旧 A 写入器可用。
- 为单独检验自动控制面，以 A 原始 ZK 身份建立**真实独立的控制租约、但不打开 WAL、不拥有 ACK 写入口**；B 使用原始 RSA 身份和它的独立 ZK 会话运行真实 `CommonCertifiedFailoverWatch`，在启动前只读认证原始 A/B WAL + B 的真实双签名 Custody，`HEAD=2`。
- B 的 Common Watch 首先观察到 A 的**活动**临时租约，然后 A 控制进程被实际 `SIGKILL`。没有由脚本执行 E5 CAS，也没有触发业务端选主。B Watch 自动调用 `CommonCertifiedFailoverCoordinator.stageRecovering`，以原 B RSA 将 E4 READY → E5 `STRICT_QUORUM RECOVERING` 的前驱 Stage fsync、签名，再于真实三 ZooKeeper 完成 CAS，E5 B 新 Primary/A Replica、`READY=false`。成功标记 `T298_REAL_E4_A_SIGKILL_B_COMMON_AUTOWATCH_SIGNED_E5_RECOVERING_PASS`（首轮运行时的旧日志标记；源码现改为不歧义的 `T298_B_AUTOWATCH_AFTER_A_CONTROL_SIGKILL_SIGNED_E5_RECOVERING_PASS`）。
- **第三个全新 JVM**从 B 原始 RSA 公钥重新验签 Stage，核对实际三 ZK 当前版本=3 / E5 nonREADY，以及原始两份 WAL 物理认证 HEAD2、A-only seq3，结果：`T298_FRESH_JVM_ORIGINAL_RSA_VERIFIED_AUTOMATIC_E5_STAGE_PASS zkVersion=3 committed=2 aUnacknowledgedTail=3 ready=false ackGranted=false`。
- 限制：被杀的是 A 的**真实 ZooKeeper 控制进程**，不是已被 WAL 水位不一致门禁挡住的旧 A 写入 JVM。因此这是**真实独立 B Common 自动控制面 Stage PASS**，不是完整活 Primary 故障恢复 GO。没有发布 E5 READY，也没有给用户返回错误的严格 ACK。

## T299｜E5 只从已确认数据构建双独立 RSA 恢复快照

- 新 E5 B Primary / A Replica 使用同一原有物理 RSA 公钥和各自本地私钥。A、B 各自从原有已签名 E4 业务基线 + 双物理 Custody 证书认证的 E4 seq1/2 **独立计算**后续 Demo 的不透明业务状态；A-only seq3 被排除。Common 再分别通过 `CommonDurableGenesisVoterImage` 真 fsync **全新** E5 image 并用每个节点自己的原 RSA 私钥 `signLocallyDurable`。
- A/B 独立输出的快照 SHA256 均为 `1a5e90d2b2669daac8897331ad23a589ec0a750cf155492e64a8bcefd0c93142`。`CommonCertifiedGenesisQuorum.sealAndVerify` 双签名封存成功，生成字节大小 318，新 JVM 只读 `reopen` 后仍一致。
- 标记：`T299_E5_T292-A_PHYSICAL_SIGNED_CERTIFIED_ONLY_SNAPSHOT_PASS`、对应 B PASS、`T299_E5_DUAL_ORIGINAL_RSA_CERTIFIED_PREFIX_ONLY_SNAPSHOT_SEALED_PASS`、`T299_E5_DUAL_ORIGINAL_RSA_CERTIFIED_PREFIX_ONLY_SNAPSHOT_REOPENED_PASS`。
- 本测试采用 Demo 用的不透明状态编码，以 Common 现有原语封存认证数据；**不等于已在 E5 业务进程真实安装该状态机，也没有开启 E5 业务写入**。相关类 `CommonT298AutomaticStrictFailoverStageProcess`、`CommonT299SignedE5CrashSnapshotProcess`；Common 本地提交分别 `328de46`、`2895419`。

## 尚需完成的严格门禁

1. Common 对**真实 STRICT→STRICT 交换主备**的认证 E5 恢复事务，确保业务 `byte[]` 状态由已确认历史安装到 A/B 且两个 JVM 持久 `REPLAY_COMPLETE`，签发独立恢复回执。不得绕过 Common 的旧 A 未确认尾部校验，不能把 T299 测试编码当成正式 Order/Trade 交易状态。
2. 验证旧 A 被真正撤权/物理关停，E5 B/A 以认证 READY 正式恢复双 WAL、双 Custody 2/2 客户端 ACK，再执行 B→A 故障和真正连续互切（无重复成交、无已确认数据丢失、无双主）。
3. 同一 Common 接线的**最新** Order/Trade 本地编译与替换，租户自动审批→Robot 报价和 Tape 点价→真实成交→Order/Trade A/B 自动 HA 与余额/订单/成交/持仓一致性。`t178` 老业务工作树仍 pin 错误的 `com.app.dc:0.0.4-SNAPSHOT`，当前不能直接用来替换；运行的 Order B 原先出现 fsynced HEAD 不匹配、Order C 旧集群开关未关，必须重新部署新干净业务数据并验收。

**整体 P0：NO-GO。** 本轮未修改正式 Order/Trade 容器，没有删除旧 E4 原始 WAL，没有调用 GitHub Actions，保留部署仓库其他未提交文件。
