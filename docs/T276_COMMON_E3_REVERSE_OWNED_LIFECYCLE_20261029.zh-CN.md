# T276｜Common 控制线程接管 E3 反向恢复与 READY 实测（2026-10-29）

## 结论

**E2 和 E3 两个切换方向，都有 Common 自己的 `CommonCertifiedFailoverWatch` 控制线程执行恢复事务并验证签名 READY 的隔离实测证据：PASS。完整 P0 仍 NO-GO。**

- Common 测试仓：`~/.opentradingcore/t177-common-saas-crypto-integration-20261027`，本地提交 `7cea593`；基于 Common 生产自动生命周期实现 `f4ef67c`。本轮将 `DemoCommonRejoinProcess` 测试场景 E3 反向恢复从 `awaitStage()` 后的测试进程主线程挪为 Common `CertifiedRecoveryCompletion` 控制线程中的认证恢复调用；不在 Demo 生产业务层新增任何 HA 代码。
- Common 调度器调用既有 Common `CommonCertifiedCrossEpochSurvivorInstall.installE3`、`publishCertifiedLocalReverseReady`、签名 WAL/第三方 C RSA 见证。新断言 `T276_COMMON_WATCH_THREAD_VERIFIED_E3_RSA_READY=PASS` 同时核查实际线程名前缀 `common-certified-failover-control-` 和 Common `requirePublishedReady()`；缺证据时仍非 READY。脚本会强制检查该标记，不通过则失败，不能用主线程手动发布替代。

## 本轮新运行证据

- 命令：使用 `examples/common-only-demo/scripts/verify-real-auto-sigkill-genesis-replay.sh`，在原有 T275 全部参数上额外开启 `OTC_T276_COMMON_E3_LIFECYCLE=1`，A/B/C 原始 RSA 仅本机只读，使用真实 3 ZooKeeper、Netty JVM、真实物理 fsync 和双次 SIGKILL。脚本退出码 **0**。
- 原始运行：`~/.opentradingcore/t124-live-kill-runs/20261029115834`；汇总日志：`~/.opentradingcore/p0-20261029-evidence/t276-e3-common-thread-verified-r2.log`。此前另一次 T276 无新增显式断言的运行亦退出 0，但**本文件只将 r2 作为正式断言证据**。
- 新增验证日志：`T275_COMMON_WATCH_THREAD_VERIFIED_E2_RSA_READY=PASS`、`T276_COMMON_WATCH_THREAD_VERIFIED_E3_RSA_READY=PASS`、`T270_REAL_B_E3_ONLINE_RSA_REPLICA_REJOIN_PASS total=74 requests=6 e3Seq=2`、`T272_REAL_A_E3_NEW_BUSINESS_TO_REJOINED_B_TCP_RSA_FSYNC=PASS`。
- 新建业务的两次真实 SIGKILL A→B→A 以及 B 再加入后原始 E3 WAL TCP 复制到双方；E3 序号 3，双方最终业务值 **85**、7 个请求。E2/E3 客户端 ACK 仍是 `LOCAL_DURABLE_ASYNC`（有 RPO 风险），不因回归副本 RSA fsync 而追认任何历史 Quorum 保证。
- 带原始 A/B/C RSA 的 Common 完整 Maven 回归：**139 suites / 619 tests / 619 passed / 0 skipped / 0 failures / 0 errors**。测试日志仍包含已有 `ATSConfig.ini` 查找异常，但 Maven 进程退出码为 0。
- 使用的 Common 候选 Jar SHA256 为 `7a86a17dbfd3bf35a99c0b9a0101cc34ce881de62646698f18307e649e81796f`。T276 本身只修改了 Demo 隔离测试接线，并未替换 Common 生产 Jar，更未替换正式 Order/Trade 服务。

## P0 下一步严格门禁

1. **生产常驻自动重加入仍缺**：E2/E3 的原始认证恢复已由 Common 线程发起，但测试脚本仍启动重加入的 JVM，旧 B 的 Genesis/Epoch WAL 回放与角色授权由隔离测试入口组合 Common API。需要将这个统一为 Common 正式进程启动时根据签名成员状态自动进行的受权恢复，业务只注入 `byte[]` state-machine。
2. **严格未来 2/2 ACK 尚缺**：E3 回归 B 已证明真实 TCP+两端 fsync，但 Epoch 3 的原客户端策略依然固定 `LOCAL_DURABLE_ASYNC`；不允许直接把它改为 STRICT。需要一个新的、经 Common 证明两端物理 HEAD、无分叉尾、旧 Epoch 已撤权和签名 ZK manifest 的原子新 Epoch 激活后，才对**未来新写入**授予严格 RF2 `QUORUM_DURABLE`。现有 Common 高 Epoch Replica 仍有 `Common newer Epoch replica certified recovery required` 拒绝门禁，这是安全边界，不能直接删除。
3. 以上完整真实验收才是 P0 GO；之后 Order/Trade 只能使用**相同 SHA Common Jar / Bootstrap / Watch / 恢复 / WAL 协议**，不能开发第二套集群。业务类别、订单类型、TIF 或资金流水不得作为 Common 的持久化/签名准入条件。

本轮没有重新部署 Order/Trade，没有使用 GitHub Actions，没有上传 RSA 私钥及真实 WAL；不对用户说 P0 已经 GO。
