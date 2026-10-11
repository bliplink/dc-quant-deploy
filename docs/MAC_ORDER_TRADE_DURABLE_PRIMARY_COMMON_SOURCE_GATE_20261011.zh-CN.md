# Mac HA：Common 真实 Order/Trade Durable Primary HEAD 接线与灰度门禁（2026-10-11）

## 结论（不能把源码测试当成在线 HA 已接管）

本轮保留正在运行的 **10 租户 + 24 容器** 演示集群，不清数据、不执行新的 MD 故障注入、不删除归档。已实现 Common 认证恢复协议到 Order、Trade 当前 Primary 持久化状态的**第一阶段真实业务适配**，并在独立 Java 8 Maven 依赖链中测试。

**没有完成/上线：** 真实有业务变更的已提交 WAL 增量数据帧提供者、带认证的数据流到 DurableRecoveryTransactionControl 的自动恢复闭环、统一 REPLAY_COMPLETE→READY 外部安全证明、MD 全市场接管、Archive→Active 真实追平/自动删除。不得打开 `commonBinding.enabled` 或宣称全部 HA 实现。

## GitHub commits / 分支 / 可复现性

| 模块 | commit | 分支 | 说明 |
|---|---|---|---|
| Common | `528e4a7`（本轮，承接 `91ecb57`、`eb508ad`） | `saas-crypto` | 恢复期 Challenge/HMAC SourceHead V2、绑定的 Snapshot/WAL 帧、Netty HEAD 可选控制处理器；服务名称兼容 `SERVER.OrderSvr` 等规范化命名 |
| Order | `f26fb51` | `codex/order-durable-primary-common-source-20261011` | 新增真实 Primary Durable HEAD 适配、旧端口可选控制操作、失效拒绝单测 |
| Trade | `8a9cf79` | `codex/trade-durable-primary-common-source-20261011` | 新增 Trade Durable HEAD 适配、已有 Netty 端口上可选控制操作、流式 Snapshot SHA |
| dc-quant-deploy | 本报告对应提交 | `codex/mac-trade-sigkill-validated-20261011` | 真实验证证据与上线门禁 |

Common 已推送 `saas-crypto`。Order/Trade 仅推独立验证分支，**未提前合并到 `saas-crypto`**：当前业务服务的 `com.app.dc` 依赖所指 Common 正式中央仓库版本还没有上述新类，直接合并会破坏 GH Actions 编译。先固化 Common 版本号、按已验证 release 流程发布 Central、`com.app.dc` 引用新版本，业务模块再引用新的 `com.app.dc` 版本。

## 1. Common 协议接口与恢复状态机

- `ReplicatedStateMachine`：业务仅 `apply(byte[])`、流式 `snapshot` / `restore`；`StateMachineRecoveryCoordinator` 负责封存快照、序号检查、Committed WAL 连续重放、失败留 `NOT_READY`。
- `RecoverySourceAttestation`：`SourceHead` V2 只由 Primary 声明权威分区、Epoch、snapshot SHA/Seq、已提交状态/Marker 和 committed HEAD，不签副本本地路径、Epoch、seq 或策略；随机 256-bit Challenge + 物理节点专属 HMAC 密钥。
- `RecoveryTransferFrame`：一个恢复会话的 Snapshot chunk / committed WAL slot 携带来源、分区、ZK version、HEAD、Epoch、偏移/序号与 HMAC；强制最大 256 KiB 帧，SHA、严格 offset、单调 WAL 和最终 HEAD 检查。
- `RecoverySourceHeadControlHandler`：通过现有 Netty `ReplicationControlRequest` 返回 HEAD 证明，默认**不注册**；真正源端必须注入实时 ZK+durable `DurablePrimaryAuthority`，否则拒绝。
- 中央验证 `ZkReplicaRecoveryAuthority` / `DurableRecoveryTransactionControl` 仍需与业务恢复事务、源数据流和实际 READY 外部门禁进行整体接线；不能从 HMAC 头和帧通过直接跳到 READY。

## 2. Order 真实源头适配（默认关闭）

`OrderDurablePrimaryHeadAuthority`：
- 要求写可用 ZK session，使用 `ZkCluster.zk.readData(root/Pnnn, Stat)`，要求真实 ZK `Stat.version`、本机当前 Primary、与进程分区表一致。
- 使用已有 `OrderPartitionBarrier.quiesce` 独占状态锁，在锁内前后重验同一个 Epoch/Primary/ZK版本。
- 读取真正持久化的 `snapshot/Pnnn/snapshot.json`、交叉验证 `OrderSnapshotManager.loadLatest` 和 snapshotId/seq，计算原始文件 SHA256。
- 用 `OrderCommitWatermark.scan`、`OrderPartitionJournal.lastSeq/lastEpoch` 校验 Snapshot Seq 与真实 journal tail 相同、没有未提交状态、commit marker 与 Snapshot 元数据完全一致，**只签 Snapshot HEAD，不夸大为最新未提交 WAL HEAD**。若业务活跃使快照变旧，会保守拒绝，本轮没有对活动写入强制 snapshot。
- `OrderRecoveryControlRouter` 默认 `order.cluster.recovery.source.control.enabled=false`，不启用时 **原 Order FAILOVER_PROOF control handler 原样返回**，正常下单复制没有新增 HMAC IO。明确启用才要求 `OTC_ORDER_RECOVERY_HEAD_KEY_HEX` 等 per-node >=256-bit 密钥并在原 Netty 通道新增 HEAD 操作。

## 3. Trade 真实源头适配（默认关闭）

`TradeDurablePrimaryHeadAuthority`：
- 使用 Trade ZK root 的强一致 `readData(Stat)` 与本地路由交叉核对当前 Primary/Epoch；再在 `TradeStateCoordinator.withPartitionIdLock` 排他区读取镜像及提交水位。
- `TradeSnapshotStore.loadMetadata` 提取实际持久化 snapshot 元数据，另以 64KiB 块 **流式计算** `latest.json` SHA256，不整文件载入内存；默认单次证明最大 1GiB，超限拒绝。
- `TradeCommitWatermark.scan` 证明当前 Snapshot committedStateSeq/Epoch 与 commit marker 一致；物理 journal tail 和 Epoch 必须精确对应存盘 snapshot；当前有脏尾/新版写入时失败关闭。
- `trade.cluster.recovery.source.control.enabled=false` 默认使用原三参 `DirectNettyReplicationServer`，无额外控制 handler；明确启用须提供本机专属 `OTC_TRADE_RECOVERY_HEAD_KEY_HEX`，才从 Netty control 读取权威 HEAD。仍无自动 READY。

## 4. 真正执行的测试

全部通过 **Common → com.app.dc → Order/Trade** 的隔离 Maven 开发版本测试，不依赖 Central 的新 Common；不更改 Mac 运行服务的 Maven lock / Docker 镜像：

- Common 完整单测 **187/187**（含 Netty source challenge、认证帧、快照/SHA/水位、断言拒绝）。
- Order 源码全量 **330 tests、0 failures、0 errors、1 skipped**（本轮新增 7 个 Durable HEAD + 可选 Control Router 安全测试）。
- Trade 源码全量 **234 tests、0 failures、0 errors、0 skipped**（本轮新增 6 个 Durable HEAD + 可选 Control Router 安全测试）。
- Common service alias `SERVER.OrderSvr` 与规范化 `OrderSvr` 兼容性修复后，在隔离本地依赖链再运行 Common 全量 + Order/Trade 专项全部通过。
- Java8 Maven 本地验证工作目录：`~/.opentradingcore/local-common-protocol-20261011/source/{common,dc,ordersvr,tradesvr}`，其中 `com.app.common 3.0.17-dev4054560-20261011-SNAPSHOT` 和 `com.app.dc 0.0.4-dev4054560-20261011-SNAPSHOT` **仅为隔离测试 GAV，不是新源码的生产发布版本，严禁直接复用作为 GHCR/Maven Central 发布依赖**。

## 5. Mac Demo 完整最终核验

- `tests/verify-order-cluster-state-host.sh`：**256/256 READY**，A **129** Primary、C **127** Primary；B 256 个同步 Replica、**0 Learner**，256 组 Snapshot 一致；三个 Order 无 OOM、无重启。
- `tests/check-demo-tenants-readonly.py`：**PASS_10_TENANT_SNAPSHOT**，10/10 Robot RUNNING、每个 40 单、10/10 双边盘口。
- `tests/check-projection-consistency-host.sh`：Order/Trade `watermark_tail_mismatch=0`，`orphan_mutations=0`，跨分区 event ID 重复为 0。
- **24/24** `dc-saas` 容器运行，Order A/B/C、Trade A/B、MD A/B/C 无 OOM。
- 本次未替换在线镜像：Order `dc-saas/ordersvr:cluster-dev-local-orderepoch-4c7df72-20261011`、Trade `dc-saas/tradesvr:cluster-dev-local-tradeempty-a8fc334-20261011`、MD `dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101`。
- 只读租户巡检证据：`~/.opentradingcore/local-common-protocol-20261011/artifacts/final-order-trade-common-adapters-10tenants.json`。

## 6. 不得跳过的剩余门禁与执行顺序

1. **真实增量 Committed WAL 来源**：Order/Trade 当前验证器只证明磁盘完整 Snapshot HEAD；高频交易时常出现 Snapshot 落后，必须实现用已 fsync 的 commit marker、Commit Pair 来证明快照之后的增量区间，再用 Common HMAC 帧绑定该区间。未经提交的物理 Chronicle tail 绝对不能直接推给 `apply`。
2. **端到端受控恢复**：将源端经过认证的 Snapshot+WAL 数据实际暂存到不可变 checkpoint，接 `StateMachineRecoveryCoordinator.recover`，确保来源在发送→安装→replay→结束 4 次 ZK owner/epoch/version 检查；故障点逐一测试 INSTALLING ledger，失败保持 NOT_READY，成功仅记录 REPLAY_COMPLETE，READY 交外部门禁。
3. **密钥/传输安全**：为每节点安全配置唯一 HMAC secret，限制配置文件权限和日志泄露，支持轮换；有开放网络时使用 TLS/mTLS 双向认证；不能只凭“TCP 能连上”当可信。
4. **正式版本链与 Mac 小范围上线**：发布 Common（与既有 `3.0.15` 发布流程一致）、升级 `com.app.dc` 依赖，再编译 Order/Trade ARM64+Linux 镜像、按单节点顺序滚动；先单测试分区灰度与多次真实 failover，核对完整资金持仓、成交无丢单无重复、Snapshot/Projection 水位，再考虑开启全局恢复开关。
5. **MD 安全故障门禁**：`scripts/check-md-failover-preflight.py --expected-image dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101` 的 exit 2 **是预期的 BLOCKED**；256 个 MD READY、A/B 各 128 Primary，但缺 Order 权威全市场镜像、旧发布者 Fence、READY 前二次持续隔离、Robot 对单证明。证据：`~/.opentradingcore/local-common-protocol-20261011/artifacts/md-gate-post-common-source-20261011.json`。禁止真实 MD SIGKILL 直到 BLOCKED 消除。
6. **Archive→Active 恢复**：之前已对 Order P200 的两份实盘封存 CQ 归档只读核验，A/B 重叠 **22011/22011** 条 WAL 记录完全相同，但仍未完整验收从 Archive 到活动 CQ 再到 READY 的复制/Apply；retention 决策维持 HOLD，禁止任何自动删除。
7. 上述分区恢复和 MD 故障注入通过后，才扩至 **20/50/100/200 租户压测**，测实际 TPS、P99、内存/GC、CPU、磁盘 IO 与切换恢复时延。

## 关键边界

`GitHub Commit / 源码单测通过 ≠ 镜像已更新 ≠ 实际新 Common 恢复已接管`。本轮在保持 Demo 正常运行的同时向真正的公共机制接入迈进，但**未达到全部任务上线标准**，不能伪报。后续任务应优先实现真实 Commit 来源/不可变 Snapshot/WAL staging 和 READY 联合证明，再进行发布部署。
