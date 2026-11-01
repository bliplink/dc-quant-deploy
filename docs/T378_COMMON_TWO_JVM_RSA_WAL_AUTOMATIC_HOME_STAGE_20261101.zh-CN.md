# T378｜真实 128 Home Watch 与双 JVM 物理 RSA WAL 自动回切阶段验收

日期：2026-11-01（Mac 本地 CST）

## 严格边界

本轮 **只操作隔离 Demo+Common**。不替换正在运行的 Order/Trade Common T143 JAR，不重启线上 A/B、Gateway、Robot、Projection，不进行业务环境故障注入。

隔离源码分支：`.work/t374-demo-common-ha`，此前提交 `14ed2f0`，仍沿用同一个 Common HA 核心（自动 Watch、物理 WAL、ZK CAS、签名 Stage、Strict READY），没有新增选主/业务状态机。精确候选 JAR `.work/t374-demo-common-ha/target/t377-common-home-auto-wiring.jar`，SHA-256 `dabbd5feceb577394e64cc299354b7f2060a85d4399d4e12b14a9663da8c33a0`。

## 真实 ZooKeeper：128 个自动 Watch 的负例

- 通过 `tests/run-t376-isolated-common-zk-stage.py --mode home256` 启动独立三 ZooKeeper；真实测试 B JVM 维持独立 EPHEMERAL 主租约，A 在另一 JVM 启动自己的 128 个原始 Home Watch。没有对其中任何 Watch 提供已签名的物理旧 WAL 追平证据。
- **128 Watch 全部拒绝冒进**；分区 256/256 保持原样 READY、`autoEpochCas=0`、老 B 仍 LIVE，实际控制线程 **2** 条（没有 128 个线程），实际观察 1.5 秒。
- 接着以明确的 Common 控制面 stage 操作对 P000 生成真实 RSA 已 fsync 的非 READY Epoch 3 `RECOVERING`，在 P001 上验证单分区在途限流，255 其余分区保持原样 READY。A 退出后新 A JVM 与新 ZK 会话从原 Stage Ledger 恢复精确 P000 非 READY 证据。没有为了过测试伪造 signed READY。
- 原始日志：`.work/t374-demo-common-ha/target/t376-isolated-zk/t377-home-control-8ea3aca0.log`；包括 `T378_REAL_3ZK_128_AUTO_HOME_WATCH_MISSING_WAL_DENIED_PASS totalPartitions=256 replicaWatches=128 unchanged=256 oldBLease=LIVE actualSharedControlThreads=2 autoEpochCas=0 customerReadyUnchanged=true`。

## 真实物理 fsync + RSA quorum 的正向自动 Watch

新增 **`CommonT378RealWalAutoHomeProcess`** 两个独立 Docker JVM，测试 P000、Epoch 2：

1. B 独立 JVM：独立目录 `/srv/t378-b` 真实调用 `CommonFileBusinessWal.appendUnforced` 和 `forcePending`（OS `FileChannel.force(true)`），使用**仅供隔离测试的 B 私钥**对本机 WAL HEAD 序号 1 签名，将 RSA 签名留在 B 证据卷；B 维持旧主 ZK 会话和文件锁。
2. A 独立 JVM：独立目录 `/srv/t378-a` 同样调用 WAL append/fsync，使用不同的 A 私钥签名同一原始业务中性二进制。检查 B 的原始磁盘文件 SHA-256 与 B 签名 HEAD 同一，使用原 Common 的 `DurableWalCommitQuorum.verify` 真正验证两份不同 RSA 公钥、两个不同 JVM/持久化目录及精确 HEAD。
3. **不手工调用 `stageHomeReturn`**。A 构造带原始 Home 布局的 `CommonCertifiedFailoverWatch`，其 `LocalReplicaCatchupProof` 每次从实体 WAL/B 签名重新验证双份证明。在 B 仍独立存活的情况下，真实 Watch 自主 CAS P000：E2 READY → E3 RECOVERING、signed Stage Ledger 已 fsync、B 旧租约有效，其余 **255 分区 READY 不变**。
4. READY 发布器因旧主 B 的原 Epoch P000 WAL 仍持有物理锁和旧 Epoch 退休收据缺失而拒绝。Watch `awaitReady(900)` 与 Common `requirePublishedReady` 均没有把非 READY Stage 误报为客户写入授权。外部 B 测试进程随后停止。

真实第一次结果：`T378_REAL_TWO_JVM_DUAL_FSYNC_RSA_AUTO_HOME_STAGE_PASS partition=P000 epoch=3 total=256 otherReady=255 signedWalQuorum=2/2 onDiskFsync=true automaticWatch=true oldBLease=LIVE customerReady=false elapsedMs=534`。

增加 READY 拒绝等待后的第二次结果：同标记 **PASS**，`elapsedMs=1411`（**含约 900ms READY 拒绝观察，不能当成真正 128 分区 Home 回切耗时**）。日志：`.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-27d62991.log`。

上述“双份物理 fsync”表示**同一 Mac 上两个不同 Docker JVM 和两个不同 WAL 目录**，不是两台独立物理服务器。RSA 2/2 HEAD 是严格物理签名证据，但也**不能替代已落盘的 CommitIndex/双 Custody、原 Epoch 单分区退休签名、新 E3 Snapshot/WAL 恢复收据或最终客户 ACK**。

## 在线 Demo 只读巡检（09:21 Mac CST）

Order A/B、Trade A/B、Gateway、Projection、Robot 均在运行；主业务租户 `EBAUU3`、`NWQYBB` 都是 `RUNNING / 40`，执行历史分别 `5860/5860`、`7280/7280`（执行记录与 distinct ExecID），Projection 最近水位 `2026-11-01 09:21:50.932`。租户 `C8SMUE` 仍然 `STALE / 0`、`STALE_MARKET_DATA`，不能误报全部租户正常。

## 下一道真正的 GO 门禁

1. **Common 单分区旧主在线物理退休**：B 看到 P000 已 CAS 为 E3 RECOVERING，在**只关闭 P000 的 E2 写句柄/旧 Permit**后使用自己的 RSA 私钥签发原始 WAL 退休收据；B 的其他 255 分区仍持续服务。A 的旧 Replica WAL 同样完成独立退休签名。要防止 B 继续给已撤销的 E2 P000 发 ACK。
2. **新 Epoch A/B 物理恢复与签名 READY**：Common 验证旧 2/2 WAL+CommitIndex+Custody、两份旧 Epoch 退休签名、新 E3 封存 Snapshot/原始 WAL 和两份新恢复 RSA 收据，通过 opaque 业务 Apply 恢复，最后由 `publishCooperativeStrictReady` 在真实三 ZK 发起唯一一次 READY CAS。不能使用测试回调或脚本直接改 READY。
3. **128 分区回 Home 总验收**：使 Common Watch 无人手干预地逐个执行 128 Home 分区，记录每分区触发→撤权→恢复→严格 READY 的耗时、全体耗时、P95/P99、部分回切期间可用分区、CPU/ZK QPS、WAL P99、无双主/重复成交/数据丢失。再反向 B→A→B 并保持另一侧自己的 128 分区服务。
4. 只有上述完整 PASS，才统一替换业务 Order/Trade 使用的 Common；不改变 Gateway/Robot 或增加业务选主代码。

**结论：T378 128 Watch 真 3ZK 拒绝缺失 WAL、双 JVM fsync/RSA 正向自动 P000 Home Stage 已通过；128 分区完整物理签名 READY 与回 Home 总用时仍 NO-GO。**
