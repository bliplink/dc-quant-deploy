# T272｜Demo+Common E3 B 在线回归后的真实 Netty TCP 新写入复制（2026-10-29）

## 验收结论与边界

**T272 单阶段 PASS；完整 P0 仍 NO-GO。** 真实隔离 Docker 在 A→B→A 两次 SIGKILL 后，旧 B 使用原 RSA 与 Common 认证进入 E3 Replica；A 在 B 已回归期间新增一笔 Common opaque `byte[]` WAL，A 本地 fsync 并用原有 `DirectNettyReplicationTransport` 发往 B，B 按 E3 角色授权 fsync 并返回独立 B RSA 签名 ACK。该笔客户承诺仍是 `LOCAL_DURABLE_ASYNC`，不追认历史 ACK 为严格 2/2。

## 可复核的现场与代码

- 原始证据卷：`~/.opentradingcore/t124-live-kill-runs/20261029111022`；控制运行日志：`~/.opentradingcore/p0-20261029-evidence/t272-e3-post-rejoin-tcp-r1.log`；命令退出码 0。
- Common 源码工作区：`~/.opentradingcore/t177-common-saas-crypto-integration-20261027`，本地提交 `f165f4f`，前置 `3abab18` / `6a521f2`；固定测试 Jar SHA256：`145a48ff8ab9de86d45535b096f0d120572fe655dbcd128c49274d64c7c441a4`。
- 原始独立 A/B/C RSA 只读加载，C 第一次故障前启动，E2/E3 独立 RSA 见证均由 C 常驻 JVM 自主产生。
- Common 的 `CommonCertifiedDegradedPrimary.mirrorLocalFsyncedRecordToReplica(...)` 增加**通用无业务类型的已 fsync 数据 TCP 增量复制 API**；复用 `ReplicationBatch`、`DirectNettyReplicationTransport`、`CommonFileBusinessWal.receiveReplicated` 和 `DurableWalBatchAckProof.read`。只允许当前已授权分区、Epoch、成员身份及已 fsync 原始 `byte[]`，没有发明新的 WAL / 证书协议。
- Demo **测试编排**启用 `OTC_T125_ENABLE_DEGRADED=1 OTC_T126_ENABLE_REJOIN=1 OTC_T127_ENABLE_REVERSE=1 OTC_T128_REQUIRE_E3_INSTALL=1 OTC_T129_REQUIRE_E3_WRITE=1 OTC_T130_AUTO_C=1 OTC_T270_ENABLE_E3_B_REJOIN=1 OTC_T272_ENABLE_TCP_AFTER_REJOIN=1`，调用 `examples/common-only-demo/scripts/verify-real-auto-sigkill-genesis-replay.sh`。Test-only JVM 不是正式运行时自动生命周期。

## 实测 PASS 断言

1. A 的 E1 客户签名 Quorum 与真实 SIGKILL，B E2 `LOCAL_DURABLE_ASYNC` 写入 40→60，A 重入追平；B 真实 SIGKILL，A E3 READY 写入 60→74，均 PASS。
2. B 在 A E3 原主租约有效时验证 C 签名/完整跨 Epoch 历史，获得 E3 Replica，不获取 Primary；恢复总值 74、6 个请求，PASS。
3. 旧 B 真正启动 Common TCP receiver（29301），A E3 新增第 3 条 WAL 并通过原有 Netty TCP 镜像。`T272_A_E3_COMMON_TCP_SIGNED_B_FSYNC_PASS seq=3 total=85 localAckNotRetroactiveQuorum=true`。
4. B 收到真实 TCP 复制，对自己的 WAL fsync + RSA 签名并应用 Demo `byte[]`，`T272_B_E3_COMMON_TCP_NEW_WAL_FSYNCED_PASS seq=3 total=85 requests=7`。A/B 共 7 个去重请求、总值均 85；运行器输出 `T272_REAL_A_E3_NEW_BUSINESS_TO_REJOINED_B_TCP_RSA_FSYNC=PASS`，退出码 0。
5. 回归：Common 全量 `mvn -q test` 139 suites / 616 tests / 567 pass / 49 skipped / 0 failures / 0 errors；Demo 状态机及原 RSA E3 离线物理追平测试均 PASS。

## P0 仍需完成，禁止提前部署 Order/Trade

- 将 Watch→RECOVERING→有认证的 WAL/Snapshot 业务重放→C 见证→READY→在线 A/B 自动重入的生产常驻生命周期真正**统一到 Common**；当前运行器在故障前启动和恢复后重启节点，Demo 测试进程仍主动串联部分 Common 恢复/READY 接口。不能仅凭本测试称无人干预集群 GO。
- 正式持续 TCP 复制、明确策略切换后**未来**客户写入严格 2/2 签名提交验收（不得倒签旧 `LOCAL_DURABLE_ASYNC`）；反复故障、压力及水位一致性确认。
- 通过完整 P0 后，将**同 SHA Common Jar、相同 Bootstrap/Watch/恢复生命周期**直接装入 Order/Trade。全部业务变更以 opaque `byte[]` 走同一路径；禁止业务特殊 WAL、集群类型白名单及 Order/Trade 自己做 HA。

本轮没有变更正式 Order/Trade/Gateway 镜像，未上传私钥、原始 WAL，未运行 GitHub Actions。

> **T273 追加（本日）：** 已将 TCP 回执的 RSA 身份/前缀/签名验证完全收归 Common `mirrorLocalFsyncedRecordToReplica(...)`；再次真实 A→B→A SIGKILL、E3 B 在线回归及 Netty seq3 fsync PASS。见 [T273](T273_COMMON_RSA_TCP_ACK_VERIFIED_INSIDE_COMMON_20261029.zh-CN.md)。正式 P0 仍 NO-GO。
