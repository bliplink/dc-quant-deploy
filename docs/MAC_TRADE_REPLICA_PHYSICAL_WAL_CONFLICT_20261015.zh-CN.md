# 2026-10-15｜Trade 同 Epoch 复制物理 WAL 冲突与 Demo 恢复门禁（真实验收）

## 结论

- **10/10 首次真实 E2E 通过不等于长期运行稳定。** 新 Mac Demo 在运行约两小时后从 10 个 Robot RUNNING、400 笔挂单降为 **8 RUNNING / 320 挂单、2 ERROR / 0 挂单**。失效租户是 `PZGR4M`（Trade partition `P190`）和 `LP3BG2`（`P220`）。Order A/B/C 的 256 assignment/snapshot 检查仍 PASS，Projection 的 Order/Trade DB tail 各 10 项匹配；这些不证明源/副本原始 WAL 一致。
- **可重复根因：** TradeSvrA 强制副本 ACK 失败后，Primary 的未提交状态尾部被局部 snapshot+archive+rebase 到已提交边界，下一条业务又重用 WAL seq。但 TradeSvrB 已持久化上次尝试的原始状态帧，正确返回 `ReplicationAck ERROR: duplicate WAL physical record differs or is outside verification window`。实际受影响 seq `P190=13917`、`P220=12469`；二者前一个 committedMarkerSeq 分别为 13916 和 12468。不能信任只有 Primary 的局部回滚，不能降低原始 WAL 完整性检查。
- 周期 Trade Snapshot 已在 Primary 产生（活跃分区含真实 location 和 committedStateSeq）；对应 Replica `latest.json` 仍可能是初始化的 seq 0、空 locations。**本地 Snapshot 文件以及 ZooKeeper READY 都不是认证恢复证据。**

## 已执行纠正动作

1. v4 极端 fail-closed 原型（[Trade PR #28](https://github.com/bliplink/com.app.dc.tradesvr/pull/28)）在 275 项本地 Java 8 单测后被临时部署，但对正常关机遗留的 WAL dirty-tail 也实行禁止同 epoch 重放，导致 10 个租户短暂全部不可交易。**立即回滚至 v3；PR #28 已关闭且不得合并。** 不以单测成功代替真实重启验收。
2. 重新实现**只隔离实际物理 WAL 冲突的分区**：Trade 提交时收到指定复制 ERROR 后，原子写入并 fsync `../../data/TradeSvr{A,B}/replica-conflicts/Pnnn.fenced`；`TradeRecoveryInstallGuard` 在正常 READY 前检查这些持久化标记；重启后仍阻断，不暴露无证明的“清理”接口。其它仅有普通未提交尾部的分区继续使用当前恢复流程。源码 [Trade PR #29](https://github.com/bliplink/com.app.dc.tradesvr/pull/29)，SHA `56ea488`；**Java 8 全量 276/276 通过，0 失败、0 错误。**
3. Mac ARM64 镜像 `dc-saas/tradesvr:scoped-conflict-fence-v5-local-20261015` 已**直接部署 Demo**的 Trade A/B，未动数据库和其他服务；镜像内 Common SHA-256 为 `af14b091151feba2caf384ae8652065fa1b12de8ef27af57b57fe955187d71de`，与原候选一致。此镜像是 Mac 本地集成验证版，不是正式授权发布镜像。
4. 真实运行恢复到 **8 RUNNING、320 笔挂单**；只有 `P190.fenced` 和 `P220.fenced` 被创建（TradeSvrA 数据目录），两个异常租户保持 `PARTITION_NOT_READY`，其它活跃分区无新增 `TRADE_PARTITION_RECOVERY_FAILED`。原 WAL、快照、归档、此前旧运行根目录均保留，没有删除、手工覆写、强制 READY，也没有 SIGKILL Primary。
5. 只读压力扩容门禁：`NOT_READY` / `nextRampAuthorized=false`，至少因 2/10 Robot 不健康。Trade 重启窗口内还暂时记录了若干 Order 分区 NOT_READY 拒绝，可能是瞬态日志，不能将这个门禁值伪称可扩容。

## 根本修复仍待完成

- `P190`/`P220` **没有真正恢复交易**：必须从可信、独立成员签名的原始 Snapshot+完整 WAL committed-range 生成确定的源 HEAD，完成目标 Replica 的隔离 staging、Chronicle 接收端事务和历史原始 WAL 续传，在新 READY 之前完成 Replica Head/ACK、旧发布者隔离及资金/持仓/委托/成交/Projection 的外部权威对账。不能直接删除这两个 replica 分区目录或者移除 `.fenced` 作为“恢复”。
- Mac Demo ZK 目前 `standalone`，且实际物理节点没有可独立签名的多物理 Quorum；Demo 功能回归仍可进行，但不能称生产级可信 Quorum/HA 已通过。已具备的 Common 完整 WAL window 认证候选与 Trade 受控接收入口需先完成运行时调度及可信凭据链，然后再执行授权真实 SIGKILL。
- 为长期健壮性，应将“源端未提交状态已在 Replica 持久化、但 ACK 丢失”设计为**明确的可认证事务恢复分支**，不能让 Primary 在相同 epoch 靠本地 rebase 复用物理 seq 后自动继续交易。PR #29 的 fence 是暂时阻止假恢复的保护层，**不是无损自动追平的实现**。

## 可追溯现场记录

- Mac runtime `~/.opentradingcore/dc-saas-runtime-ordered-20261015`；私有部署环境文件（勿提交）：`~/.opentradingcore/otc-demo-direct-20261015/demo-ordered-trade-v5-20261015.env`，回滚 v3 在同目录 `demo-ordered-adminfix-20261015.env`。
- 验收证据同目录 `acceptance-evidence/ten-tenant-after-v5-conflict-gate.json`、`trade-v5-rollback.json`，源码测试 `TradeReplicaConflictFenceTest`、`TradeRecoveryInstallGuardTest`、`TradePartitionLifecycleManagerTest` 等。敏感运行凭据未收入本文件。
