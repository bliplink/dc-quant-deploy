# T280｜Common E4 STRICT 签名 Stage 与真实三 ZK RECOVERING CAS（2026-10-29）

## 本轮完成与证据

**控制面第一阶段 PASS；完整 P0 仍 NO-GO。**

- Common 在原 `CommonDurableFailoverStageLedger` 的同一种 RSA-signed、fsync、原子硬链接、不可覆盖 Stage 格式上增加**同主 A、同备 B、Epoch+1、LOCAL→STRICT** 的严格相邻转换。原有 A/B 互换、原策略不变的 Failover Stage 不变。任何任意政策转换、乱序 Epoch 或其它分区变动仍拒绝。
- Common `CommonCertifiedStrictEpochRearm.stageNonRoutableStrictRearm` 要求先验证真实 E3 两节点同 WAL HEAD、双方原始 RSA 身份签名、无额外尾部；在真实 ZooKeeper 会话及独立 A/B ephemeral 租约存在的条件下，将签名 Stage **持久化在 CAS 前**，随后仅发布 **E4 STRICT RECOVERING（READY=false）** 的原子 ZK CAS。这个接口**不授权 E4 业务写入/ACK**。
- 在 E4 签名 Stage 仍为 RECOVERING 时，`requireStagedAndSealed` 二次核对签名 Stage、ZK 版本和旧 E3 两份物理 HEAD，额外尾部或 ZK 状态变更都拒绝，不能直接发 READY。生产仍必须用真实 Common 旧写入端撤权/物理关闭证据代替测试夹具的空回调；本轮**没有**宣称已经验证生产撤权完成。
- 单元测试覆盖正常 Stage、丢失 B 租约、并发 CAS 版本竞争、CAS 失败后不可篡改签名 Stage 持久保存和相同状态下恢复、CAS 后新增 WAL 尾部仍不能 READY。原始高 Epoch Replica 恢复认证拒绝门禁不删除。

## 真实三节点 ZooKeeper 控制面实测

- 使用真实运行的 `otc-t84-source-integrated-otc-ha-zk1/2/3` 三节点及独立隔离命名空间 `t280-20261029134326`；原始 A/B RSA 和之前两次 SIGKILL 后的 E3 原始物理 WAL 只读挂载，确认 E3 seq=3、SHA256 `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689`。
- 测试在**一个独立 Docker JVM 内建立两个真实但同进程的 ZK 会话**，模拟 A/B 活租约，演示 Common 在真实 ZK quorum 上将版本 0→1 CAS 为 `E4 STRICT RECOVERING`，新 READY=false，退出码 0，打印 `T280_REAL_3ZK_SIGNED_E4_CAS_RECOVERING_NOT_READY=PASS`。
- 证据目录 `~/.opentradingcore/t280-e4-stage-real-zk/20261029134326`：含冻结候选 Common Jar、签名 Stage、只在此测试环境创建的临时 WAL 副本与日志 `real-three-zk-e4-stage.log`。**这不是两个真实长期存活的业务 JVM，也没有 E4 的双节点恢复或客户端 ACK**。
- Common 生产 Jar 及服务中涉及的多 Epoch strict 机制尚未完整启用；Order/Trade 容器没有替换，也没有使用 GitHub Actions 或上传原始密钥。

## 余下 P0 GO 必需项

1. 在两个真实独立 JVM 中，通过 Common 完成旧 E3 写入端 fencing、关闭旧 WAL、确认双盘终态与签名业务快照，再分别恢复 E4 baseline/Replica（遵守高 Epoch Replica 认证）。
2. 由 Common 对 A/B 恢复、Epoch4 双端实物身份、旧 Epoch 撤权、签名 Stage、物理双签名水位和必要 Custody 执行**严格 READY 授权**，真正 CAS `E4 STRICT READY`。任何一个必要证明缺失都留在 RECOVERING，不得只因测试时间到就放行。
3. 在 READY 后对 **E4 新业务**测试双份真实 TCP fsync、签名 Custody 与 CommitIndex 持久化、客户端 `QUORUM_DURABLE` ACK，故障中无误确认、自动 A→B→A、副本追平以及业务状态一致；过去 E2/E3 LOCAL ACK 不会被追认为 STRICT。

本报告只陈述已运行的阶段性证据，不能替代 P0 GO，不能据此提前部署 Order/Trade。

## 本轮最终本地构建记录

- Common 代码提交 `e754bba`，分支 `codex/t177-common-saas-crypto-integration-20261027`；使用当前候选 Common Jar SHA256 `cc60b924483cd5bd3e97c8eda170c9b69646aa108d1dd4c8bde76550a5a855ff`（尚未用于正式 Order/Trade）。
- 带原始 RSA 的 Common 全量 `mvn -q test` 退出码 0：**141 套件 / 630 tests / 630 passed / 0 skipped / 0 failures / 0 errors**。日志仍包括项目既有 `./control/ATSConfig.ini` 未找到的异常输出，但未使 Maven 失败。
- 原 E3 双向真实 SIGKILL + A/B RSA/TCP 的上一轮证据仍为 `~/.opentradingcore/t124-live-kill-runs/20261029133129`。T280 没有重跑完整 A/B 故障注入，也没有在 E4 做真实客户端 strict ACK，严禁把 E4 阶段性控制面 PASS 当成 P0 GO。
