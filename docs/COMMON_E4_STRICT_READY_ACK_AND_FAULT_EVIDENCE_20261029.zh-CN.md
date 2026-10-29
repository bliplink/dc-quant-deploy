# Common E4 STRICT READY / 双物理 ACK / 故障注入阶段验收（2026-10-29）

## 核心结论

**严格双节点新写入已在独立 Docker JVM + 实际 ZooKeeper 上通过；整个 Common P0 尚未 GO。** 本轮不再新增业务 HA 实现：全部 WAL、认证、恢复、角色、提交水位留在 Common；业务仍只提供 `byte[]` 状态机。

### 真实验收结果

1. **E3 → E4 控制面：** Common 增加 `CommonCertifiedStrictOldEpochRetirement` 和 `CommonCertifiedStrictReadyPublisher`。只有原 A/B 两份旧 Epoch WAL 退休 RSA、E4 A/B 两份真实 `REPLAY_COMPLETE` RSA、同一独立双签名 E4 基线、相同签名 Stage 与两个独立当前 ZK 租约齐备时，才允许单次 ZooKeeper CAS 将 `E4 STRICT RECOVERING` 改为 `READY`。正常/无 B 证书/租约缺失/旧 E3 仍 READY/原始 WAL SHA 错/重复 CAS 都有拒绝或正向测试。
2. **实际三 ZooKeeper E4 READY CAS：** 隔离结果 `T285_REAL_3ZK_E4_STRICT_READY_CAS_WITH_OFFLINE_E3_RECEIPTS_PASS`，证据 `~/.opentradingcore/t285-e4-offline-ready-control/20261029153456`，ZK `/dc/cluster/t280-20261029153456`。它真实使用 3 ZooKeeper 和原 A/B RSA；但旧 E3 退休证明来自**此前真实双向故障测试结束后已经关闭的 E3 WAL 文件**。它**没有**在本次 E4 阶段证明一个运行中的 E3 A 主节点/ B 副本受到真实在线撤权、关闭物理句柄、确认最终水位。因此这是控制面集成验收，不构成最终真实自动切换 GO。
3. **真实 E4 严格新业务（两个独立 Docker JVM）：** Common E4 B 先以原 RSA 恢复签名、持久账本以及当前 ZK Replica 许可启动真实 Netty server。E4 A 使用真正的 `NodeClusterControlManager` ZK Primary grant、原 RSA、`CommonCertifiedPartitionRuntime`、TCP、双 WAL fsync、CommitIndex 和双 Custody，向 B 发出**两条新不透明业务写入**。两个真正客户端返回均为 `QUORUM_DURABLE`（seq=1/2），B 物理 WAL fsync 达到 2，测试退出 0。证据 `~/.opentradingcore/t286-real-e4-strict-netty/20261029153749`；标记 `T286_REAL_TWO_JVMS_E4_STRICT_RSA_TCP_DOUBLE_FSYNC_CUSTODY_ACK=PASS`。本测试以新 `byte[]` 写入验证存储/提交机制；**尚未将这两条字节应用为新的 Demo 业务累计值**，原业务基线仍为 85 / 7 请求。
4. **真实 B SIGKILL 后禁止虚假 ACK：** 在 B 真实持久了上述 2 笔后，重新启动 E4 B JVM并读取旧物理卷，确认正常 Netty 监听；随即实际 `SIGKILL` B。新的 A JVM 重新打开其持久 WAL 与 CommitIndex 后发起第 3 笔业务，真实 TCP 复制失败 (`ExecutionException`) 且**未给任何客户端 ACK**。标记 `T287_REAL_E4_STRICT_B_SIGKILL_NEW_CLIENT_ACK_REJECTED=PASS`；同目录 `t287-b-killed-no-client-ack.log`。A 磁盘保留了一条无双节点签名、无 CommitIndex 认证的尾部；它绝不可被错误升级为已提交历史，必须由后续认证恢复处理。
5. **全局回归：** 在修改 Common 统一恢复、阶段授权及严格写入机制后，本机 Maven + 原始 RSA 的全量测试独立进行；具体完成数以测试日志及返回码为准。原 `./control/ATSConfig.ini` 输出不应误算为 Maven 失败。

## 仍需完成，不得再以独立预检替代

- **活 E3 自动撤权链路**：当真正运行中的 A E3 LOCAL 写入器与 B E3 Replica 正在持久化/转发数据时，在原 ZooKeeper 中进入 E4 非 READY，由 Common 亲自撤销两端旧 Epoch 权限、关闭旧 WAL/监听、签发各自签名退休证明。现新增 `CommonCertifiedDegradedPrimary.retirePhysicalWriterForStrictRearm`，持有真实旧 WAL 的主体串行化关闭并禁止后续 commit，但**尚未在活 A/B 跨 JVM 连续测试中验证**。
- **严格模式故障与恢复全闭环**：B 被杀后 A 第三笔留下无 ACK 本地 WAL 尾部。必须通过 Common 认证 WAL 水位和真实 B 持久 Custody 恢复这段分叉，重新授权正确下一 Epoch，再做 A/B 自动连续互切、持续业务、余额/持仓/订单/成交一致性。不能用脚本伪装自动主备、不能直接把未确认尾部当已提交，不得让旧 E3 LOCAL 客户端 ACK 被追认为 QUORUM。
- **正式业务服务验收**：在上述 Common P0 真正 GO 后才将同一 Common JAR/启动接线应用到 Order/Trade，测试新租户自动审批 → Robot 报价和 Tape 点价 → 真实下单成交 → A/B 自动故障切换后业务状态保持一致；未完成前不可宣布整项任务成功。

本轮是开发 Demo 隔离测试，没有替换运行中的 Order/Trade 镜像，没有删除现有数据或执行 GitHub Actions；保留原有 `dc-quant-deploy` 工作区未提交变更。

## T288｜B SIGKILL 后严格提交水位恢复（新增实证）

- Common 源码 `CommonCertifiedStrictCrashPrefix.inspectReadOnly(...)` 已落地：并不依赖 unsigned WAL CRC，也不以 A 原始最终 WAL HEAD 作为可恢复水位。用原 B 独立物理 WAL + 读-only RSA Custody `head.bin` + B 物理安装的 A/B 双签名 Custody receipt ledger 验证提交 HEAD，同时对 A 独立物理原始 WAL 校验相同被签署前缀。在此以后才允许输出完整的 `byte[]` 命令序列；**不会截断旧 A 的未确认尾部、不会授权新 Epoch，也不伪造业务 apply。**
- 使用真实 T286/T287 B SIGKILL 原始数据，A=seq3、B=seq2、RSA CommitIndex/Custody 认证提交=seq2，结果只允许 `T286-E4-NEW-BUSINESS-1` 与 `T286-E4-NEW-BUSINESS-2`；第三条 `T287-STRICT-B-KILLED-UNACKED` 没有进入恢复序列。对只读副本篡改旧 A WAL、篡改 B Custody `head.bin` 或缺少独立 Custody receipt ledger 都拒绝；没有修改原始故障数据。
- 定向测试输出：`T288_REAL_E4_AFTER_B_SIGKILL_CERTIFIED_PREFIX_ONLY_PASS oldPrimaryFrames=3 dualCustodyCertified=2 exposedCommands=2 unackedTailExcluded=true`，`T288_REJECTS_CORRUPT_OR_MISSING_B_CUSTODY_PROOF_PASS`。Common 完整 Maven+原有 RSA、T284/T285/T287/T288 原始证据回归退出码 0：**146 suites、637 tests passed、0 skipped、0 failed、0 errors**。原有 `./control/ATSConfig.ini` FileNotFoundException 日志依然会打印，但没有导致 Maven 测试失败。
- Common 本地提交：`150a812`，与前一轮签名 E4 STRICT READY/T286/T287 源码提交 `3a9ecff` 同在 Common 开发分支。T288 是**恢复源数据认证门禁**，不是 B 自动重加入、E5 签名主备切换或整个 P0 GO。

## 活 E3→E4 尚未通过的实测项

- 开始实现 `CommonDemoLiveE3ToE4Process` 测试入口：真实 A/B 两个独立 JVM 的 E3 `CommonFileBusinessWal` 与 B Netty、原 A/B RSA 身份和真实三 ZooKeeper 各自持有长寿命 Session；预期两端在同一 E4 RECOVERING CAS 后真实关闭旧 WAL/TCP、撤销缓存授权并分别签名，再由两端新 E4 独立恢复回执发布严格 READY。
- 测试入口已通过 Java test-compile；**从活 E3 开始、最终 E4 严格 ACK 的多容器执行命令被执行环境安全检查拦截，未实际运行。此测试入口暂时保留在 Common 工作区，未宣称可用、未提交为正式通过用例。** 不得用原 T285 的已关闭 E3 WAL 替代此项验证。
- 正式 Order/Trade 镜像未替换，仍为 P0 NO-GO；后续必须补完活 E3 退休、E4 故障后多节点认证追平/切换和全业务交易验收。
