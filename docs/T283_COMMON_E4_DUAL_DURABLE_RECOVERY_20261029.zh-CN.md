# T283｜Common E4 双独立 JVM 持久恢复事务与重启核验（2026-10-29）

## 本轮新增的 Common 代码与真实结果

**T283 局部恢复门禁 PASS，完整 P0 仍 NO-GO；不得据此发布 E4 STRICT READY 或替换正式 Order/Trade。**

- 新增生产可复用的 `CommonCertifiedStrictBaselineInstall.install`：在业务未就绪、ZK 仍处于签名的 E4 `RECOVERING` 状态时，验证 A 原始 RSA 签名 Stage、A/B 双份签名的不可变 E4 快照、**当前节点自己的**物理签名快照；之后只通过现有 `StateMachineRecoveryCoordinator` + `DurableRecoveryTransactionControl` + `DurableRecoverySnapshotSeal` + `DurableRecoveryInstallLedger` 执行恢复。所有状态机数据依然是业务注入的 `byte[]`，没有订单/TIF/余额/持仓类型规则。
- 安装前、事务中、事务结束后重复校验 ZooKeeper 的相同 `RECOVERING` manifest/version、原 RSA Stage 以及本地原始快照。状态机恢复前先封存快照、持久化 `INSTALLING` 和基线 fsync、再写 `REPLAY_COMPLETE`。任何失败均不发布 READY 或客户 ACK。
- `CommonDurableGenesisVoterImage.requirePinnedPhysicalVoter` 防止以 B 的本地快照冒充 A 的物理证据，即使业务字节完全一样；定向拒绝测试通过。
- 新增 Demo 隔离测试 `CommonDemoE4DurableInstallProcess` 和可复跑脚本 `examples/common-only-demo/scripts/verify-e4-dual-durable-replay.sh`。Demo 自己实现其业务 checkpoint/journal 标记的 `fsync+reopen`、状态机解码/恢复；没有在业务中实现 HA。这只是 **Demo 测试适配器**，不能算 Order/Trade 的业务持久化验收。

## 实际运行证据

- E4 RSA 快照输入：`~/.opentradingcore/t281-e4-snapshot-dual-jvm/20261029141049`；RSA Stage 与三节点 ZooKeeper CAS 证据：`~/.opentradingcore/t282-e4-stage-dual-baseline-real-zk/20261029141217`；命名空间 `/dc/cluster/t280-20261029141217`。
- 真实运行：`~/.opentradingcore/t283-e4-durable-recovery/20261029143823`；使用 A/B **两个先后启动的独立 Docker JVM** 分别执行 Common E4 持久恢复，分别在本节点目录写入 `P090.recovery` 和经 fsync 的业务基线，恢复到总值 **85**、7 个不同请求。两端各自 `REPLAY_COMPLETE`，且 `ready=false`、`clientAck=false`。
- 用**另两个全新 JVM** 分别重新打开持久恢复账本与封存的快照，重放相同业务总值与请求数。两端结果均为 `T283_E4_..._RESTARTED_DURABLE_REPLAY_LEDGER_PASS`。
- 已以 `verify-e4-dual-durable-replay.sh` **重复全流程并成功退出码 0**，最新证据：`~/.opentradingcore/t283-e4-durable-recovery/20261029144237`，输出 `T283_TWO_JVMS_E4_REPLAY_COMPLETE_AND_RESTARTED_FSYNCD_PASS`。
- 所有 JVM 都在同一台 Mac 的 Docker 虚拟机里，节点卷独立、RSA 身份不同，但不等于跨物理宿主机；A/B 也尚未作为长驻 E4 业务主备服务同时运行。

## 仍未完成且不可绕过

1. T280 在真实三 ZK 的 E4 `RECOVERING` 是签名且不可路由的，但本轮**尚未实证两个活跃 E3 进程的物理写入端同时退役/关闭**。不能把已关闭的历史测试进程等同于正式 E3 撤权证书，测试中的空回调不具备生产写入端退役的认证效力。
2. 两份业务状态 `REPLAY_COMPLETE` 是恢复证明的一部分，**不是** E4 多节点同一签名水位的 READY 授权。发布 `E4 STRICT READY` 还需当前真实身份/租约、旧 Epoch 撤权证明、两份独立恢复结果的可验物理凭据和准确 ZK CAS；不得直接给 `CommonCertifiedNodeRuntime` 虚构授权。
3. 后续 E4 新业务必须通过两个独立活跃 Netty JVM 的真实 WAL fsync、签名 CommitIndex 和双 Custody 后才给 `QUORUM_DURABLE` 客户端 ACK；再做 SIGKILL A/B 互切与完整状态/水位一致性。**旧 E2/E3 的 LOCAL_DURABLE_ASYNC ACK 永远不追认 QUORUM。**
4. 完整 P0 GO 之前不替换 Order/Trade；将来两个业务只复用同一 Common Jar SHA/Bootstrap/Watch/恢复，业务只实现状态机与适配持久基线，不增加第二套集群实现。

本轮未执行 GitHub Actions，未更换 Demo/Order/Trade 正式容器，也未覆盖其它工作区的未提交修改。

## 代码、回归与下一接线阻塞

- Common 候选源码提交：`d7fe78e`，分支 `codex/t177-common-saas-crypto-integration-20261027`；本轮本地候选 Jar SHA256 `4a2d04204ae3d05d16c787ff14409b9938e929efbadb1c19c9ad8414ed376d93`。这不是 Order/Trade 正式 Jar，也没有替换正式服务。
- Maven 3.9.16 + Java 8、原始 A/B/C RSA 环境执行 Common 全量 `mvn -q test`，退出码 0：**142 suites / 633 tests / 633 passed / 0 failures / 0 errors / 0 skipped**。原项目仍打印 `./control/ATSConfig.ini` 缺失的历史日志，但这次 Maven 未报测试失败。
- 真实 E4 双 JVM 恢复再次复跑脚本后退出码 0，最新输入参数环境包括 `OTC_T283_STAGE_ROOT`、`OTC_T281_BASELINE_ROOT`、`OTC_T283_ZK_ROOT`，最新输出目录：`~/.opentradingcore/t283-e4-durable-recovery/20261029144237`，单节点真实安装和独立全新 JVM 账本恢复各 2 次全部 PASS。
- **当前明确的正式运行时阻塞**：`CommonCertifiedPartitionRuntime` 对所有 `E2+` Replica 仍执行 `Common newer Epoch replica certified recovery required`，尚未把这次新的 Common 持久 `REPLAY_COMPLETE`、外部签名 Stage、真实老 Epoch 物理撤权接成正式的新 Epoch Replica 入场许可。**不能删除这项拒绝或把快照双 RSA 当作 READY。** 需先在 Common 建立基于这些现有证据的受控恢复授权，再创建 E4 主/备实际 WAL/Netty，完成严格 2/2 客户端 ACK 与自动故障切换。
