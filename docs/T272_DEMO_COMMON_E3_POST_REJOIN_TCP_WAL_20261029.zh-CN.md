# T272｜Demo+Common E3 回归后的真实 TCP WAL 复制（2026-10-29）

## 本轮实际结果与边界

**阶段 PASS，P0 全部门禁仍 NO-GO。** 继 T271 的 B 在线 E3 Replica 回归后，隔离真实 Docker JVM 实际完成 **A E3 Primary 在 B 回归后新增业务 → Common TCP 发送 → B Common Replica 角色校验、WAL 接收及 fsync → 双方状态一致**。但历史 E2/E3 客户端写入仍承诺 `LOCAL_DURABLE_ASYNC`，B 的后补物理签名不代表旧 ACK 具备零丢失保障，本轮也未通过新的正式 `STRICT_QUORUM` ACK 回归。

证据：`~/.opentradingcore/p0-20261029-evidence/t272-e3-post-rejoin-tcp-r1.log`；该次隔离数据：`~/.opentradingcore/t124-live-kill-runs/20261029111022`（原 RSA 与业务 WAL 不上传 GitHub）。实际进程打印：

- `T270_B_VERIFIED_A_E3_RSA_GENESIS_AND_C_WITNESS=PASS` 与 `T270_REAL_B_E3_ONLINE_RSA_REPLICA_REJOIN_PASS total=74 requests=6 e3Seq=2`：先认证 B 回归与旧签名历史。
- `T272_B_COMMON_TCP_REPLICA_LISTENING=PASS port=29301`：B 作为 E3 Replica 运行真实 Netty listener。
- `T272_A_E3_COMMON_TCP_SIGNED_B_FSYNC_PASS seq=3 total=85 localAckNotRetroactiveQuorum=true`：A 追加并持久化新业务，经 Common TCP 获取 B 物理签名落盘证据。
- `T272_B_E3_COMMON_TCP_NEW_WAL_FSYNCED_PASS seq=3 total=85 requests=7`：B WAL 与业务状态追到新序号 3。
- `T272_REAL_A_E3_NEW_BUSINESS_TO_REJOINED_B_TCP_RSA_FSYNC=PASS`：驱动确认两端都实际完成上述事件。

### 架构要求继续强制执行

Demo、Order、Trade 不实现独立 Watch/Epoch/READY/复制/恢复；它们只提供业务校验与不透明 `byte[]` 状态机。Common 的复制、签名、WAL 和角色检查不能按 GTC/IOC/FOK/成交或资金类别限制。此次增量 TCP 镜像是 Common 代码路径，不能为 Order/Trade 再复制一套业务集群。

### P0 尚缺的必须验收项

1. 故障后副本恢复时，Common **正式常驻运行时**自动完成恢复/READY/在线重加入，不能由测试进程串联 Common API 或由脚本替代生产生命周期。
2. 恢复双副本后，通过明确认证的 Common 策略切换和可签名的真实确认水位，验证**未来新写入**重新满足 `STRICT_QUORUM` 2/2 物理 ACK，绝不对历史 `LOCAL_DURABLE_ASYNC` 客户端 ACK 追认 Quorum。
3. 在持续业务负载下再做 A→B→A 和双向副本重启、无双主/无重复/水位一致验收，P0 完整 GO 才允许 P1 同 SHA Common Jar 接入 Order/Trade。

关联证据：`docs/T270_DEMO_COMMON_MAVEN_DUAL_SIGKILL_RETEST_20261029.zh-CN.md`、`docs/T271_DEMO_COMMON_E3_B_ONLINE_REJOIN_20261029.zh-CN.md`。
