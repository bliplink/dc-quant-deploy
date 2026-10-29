# T275｜Common 自主持久恢复调度与 READY 生命周期（2026-10-29）

## 结果

**本轮 Common E2 Watch→RECOVERING→已签名 WAL/业务 Replay→独立 C RSA 见证→READY 已在 Common 自己的控制线程真实运行并通过双向故障复测。完整 P0 仍 NO-GO，不能替换正式 Order/Trade。**

- Common 候选源码：`~/.opentradingcore/t177-common-saas-crypto-integration-20261027`，本地提交 `f4ef67c`。与此前一样，保持服务 `Demo/Order/Trade` 只提供不透明 `byte[]` 状态机与必要认证配置，不增加业务类型/GTC/IOC/FOK 持久化限制。
- Common `CommonCertifiedFailoverWatch` 现在可由正式 `CommonCertifiedNodeRuntime` 注册持久恢复完成过程，保留自动故障监测、恢复重试、无签名见证拒绝 READY。签名 Stage 生成后，Common 继续调度认证恢复而非自行关闭 Watch。不能因回调返回就认为 READY，必须读取并验证真实 ZK successor READY CAS、原始签名 Stage、当前存活节点租约和旧节点租约撤权。
- Common 在执行恢复回调前验证真正的 `RECOVERING`，关闭旧 Epoch 的物理 WAL/Netty 和相关分区句柄，然后恢复。**不成功关闭必须拒绝 READY，不准因第二次尝试而跳过之前的关闭失败**。不增加 Demo/Order/Trade 业务服务的集群选举/复制代码。
- Demo 隔离测试使用新的 Common 调度接口和现有恢复证明材料做 E2 故障测试。`T275_COMMON_WATCH_THREAD_VERIFIED_E2_RSA_READY=PASS` 验证实际执行线程是 `common-certified-failover-control-*`，且同线程调用 Common 的签名 READY 校验。独立 C 见证 JVM 在 A 故障前就已启动；未提供独立见证不能越过 Common READY。

## 本机真实验收

- 复测命令基于原有 `examples/common-only-demo/scripts/verify-real-auto-sigkill-genesis-replay.sh`，启用 `OTC_T275_COMMON_LIFECYCLE=1`、`OTC_T125_ENABLE_DEGRADED=1`、`OTC_T126_ENABLE_REJOIN=1`、`OTC_T127_ENABLE_REVERSE=1`、`OTC_T128_REQUIRE_E3_INSTALL=1`、`OTC_T129_REQUIRE_E3_WRITE=1`、`OTC_T130_AUTO_C=1`、`OTC_T270_ENABLE_E3_B_REJOIN=1`、`OTC_T272_ENABLE_TCP_AFTER_REJOIN=1`。原有 A/B/C RSA 仅本机读取。
- 证据目录 `~/.opentradingcore/t124-live-kill-runs/20261029114457`；脚本日志 `~/.opentradingcore/p0-20261029-evidence/t275-watch-thread-verified-real-sigkill.log`，退出码 **0**。
- E1 A/B 真 Quorum 持久写入 → 真 `SIGKILL A` → Common B E2 自动 RECOVERING+Replay+独立 C 见证+Common 控制线程验 READY，B LOCAL 持久写到总值 60 → A E2 在线回归、签名追平 → 真 `SIGKILL B` → A E3 RECOVERING+独立 C 见证后写到 74 → B E3 在线回归 → Common TCP+A/B RSA ACK/B fsync 新增 WAL seq 3，双方总值 **85**、去重请求数 **7**。全部阶段 PASS。
- 带原始 RSA 执行 Common 全量 Maven 回归：**139 suites、619 tests、619 passed、0 skipped、0 failures、0 errors**。测试曾打印旧配置文件 `ATSConfig.ini` 的异常日志，但 Maven 最终退出码为 0，该日志本身不构成本次测试失败。
- 本轮 Common Jar SHA256 `7a86a17dbfd3bf35a99c0b9a0101cc34ce881de62646698f18307e649e81796f`，只是候选本地 Jar，尚未替换正式业务服务。

## 不得提前宣布完整 GO 的剩余两项

1. **正式 Common 业务无关、跨 Epoch 的自动重加入/常驻恢复全链路**：本次 E2 READY 控制线程是 Common 拥有的，但仍由隔离 Demo 测试提供已签名恢复安装参数；E3 反向恢复和 B 的重启启动仍使用测试进程及脚本编排。必须归并为 Common 正式节点运行时，业务服务只注入状态机和必要配置。
2. **恢复 2/2 后的未来严格 ACK**：当前 E2/E3 写入是 `LOCAL_DURABLE_ASYNC`，历史 ACK 不可追认为 Quorum。应执行一个经过授权且改变 Epoch 的持久策略切换，确保新 Epoch 新写入以真实 A/B 物理持久签名后才返回 `QUORUM_DURABLE`；反复主切、持续负载、快照和水位一致性必须真验收。

完成 P0 全部门禁后，再在 `saas-crypto` 对 Order/Trade 使用完全相同的 Common Jar SHA/Bootstrap/Watch/恢复语义，清除业务侧任何越界集群代码。GitHub Actions 未执行，正式 Order/Trade 容器未更换，也未上传 RSA 私钥或业务原始 WAL。
