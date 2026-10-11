# Common HA 状态机业务接口：Order/Trade 真实适配第一阶段（2026-10-11）

## 结论

**已实现并提交 Order 与 Trade 的 `ReplicatedStateMachine` 薄适配层、复用业务原有 `restore/apply`，通过隔离 Java 8 Maven 全量测试。未升级 Mac 现网镜像、未开启自动恢复、未执行新的 SIGKILL/MD 故障注入。**

| Repo | GitHub commit | 分支 | 本轮代码 |
|---|---|---|---|
| Common | `7bdd352`（上轮） | `saas-crypto` | Snapshot 基线/最终 Committed HEAD 分离，网络验证→Staging→recover()→REPLAY_COMPLETE |
| Order | `13dd0eb` | `codex/order-durable-primary-common-source-20261011` | `OrderCommonRecoveryStateMachine` / `OrderStateRecovery.applyRecoveredMutation` |
| Trade | `ff2cd05` | `codex/trade-durable-primary-common-source-20261011` | `TradeCommonRecoveryStateMachine` / `TradeRecoveryApplier.restoreCommonSnapshot/applyCommonCommittedBatch` |

### Order 业务适配

- `snapshot(ChunkSink)`：在上层恢复/快照分区屏障下，调用**现有** `OrderSnapshotManager.capturePartition`，保留真正的簿单、FIFO/时间优先、client ID 幂等预留。只传送业务快照的 JSON 字节分块，单个镜像上限 64MiB；若超过则拒绝，不能静默截断。
- `restore(ChunkSource)`：完整读回已认证镜像，校验目标 `Pnnn`、源 Epoch、SnapshotSeq、CommittedStateSeq 和 CommitMarker 基线，再调用 `OrderSnapshotManager.restore` 重建内存订单簿；不在 Common 里重新实现业务恢复算法。
- `apply(byte[])`：只接受已由 Common 验证 commit 的 `STATE_UPSERT/STATE_REMOVE` 对应 `OrderStateMutation`，调用新增的 `OrderStateRecovery.applyRecoveredMutation`（恢复专属幂等语义）。`STATE_COMMIT`、COMMAND、控制帧拒绝进入业务状态机。`finishReplay` 只完成业务幂等恢复清理，不自动 READY。
- `decodeCommittedBusiness(byte[])`：只从认证的真实 `OrderJournalRecord` 解码目标分区的 STATE JSON，用作 Common `businessApply` 解码器，不能绕过先前 `CommittedWalPrefixVerifier`。
- 新增两个隔离单测：真实 DTO Snapshot JSON 来回分块、恢复入口调用；错分区 Snapshot 被拒绝且未改写业务。

### Trade 业务适配

- `snapshot(ChunkSink)`：调用现有 `TradeSnapshotManager.capturePartition` 后，**重新加载磁盘持久化** `TradeSnapshotStore.load`，确保取得包括 ExecutionDedupe 的真实完整快照（不是只序列化轻量元数据）；对外分块，当前上限 128MiB。
- `restore(ChunkSource)`：校验分区、格式、源 Epoch 不可大于当前合法 assignmentEpoch、SnapshotSeq/CommittedStateSeq，再调用 **`TradeRecoveryApplier.restoreCommonSnapshot`** 复用真正的余额、持仓、挂单、配置、ExecutionDedupe 恢复。在 TradeStateCoordinator 分区锁中校验本机仍属该 Assignment；不会在这里调用 `markRecovered`。
- `apply(byte[])`：保留完整 `TradeJournalRecord` 的 seq、epoch、eventId，严格只接受目标分区 `STATE_BATCH`，调用 **`TradeRecoveryApplier.applyCommonCommittedBatch`** 中已有的 `prepareMutation`，按原业务规则验证并更新余额、持仓、挂单、去重和资金参数；不重装 Snapshot、不标 READY。拒绝 seq<=SnapshotSeq、跨分区、Epoch 回退、重复 state、错误批次版本。
- 基于真实 **`TradeRecoveryApplier` + 真实 AccountBalanceFacade/PositionFacade** 的专项测试：恢复资金 1000 与 BTC 持仓 1，随后仅 Apply 已提交余额增量到 950，**BTC 持仓仍为 1**，证明没有重复 installSnapshot 的破坏性影响。
- `finishReplay` 不调用 `coordinator.markRecovered`，因为外部 Fencing/Projection/READY 尚未验收。

### Java 8 测试证据

本次使用 `~/.opentradingcore/local-common-protocol-20261011/source` 隔离 Maven 依赖编译，避免 Common 正式版本尚未发布时污染 Maven Central/正式 GH Actions。

- Order 专项 `OrderCommonRecoveryStateMachineTest` **2/2**。
- Trade 专项 `TradeCommonRecoveryStateMachineTest` **2/2**，真实 `TradeRecoveryApplierTest` **4/4**（含一条本轮新增 balance/position 保全）。
- Order Java 8 `mvn clean test` **338 项，0 failures、0 errors、1 skipped**。
- Trade Java 8 `mvn clean test` **243/243，0 failures、0 errors、0 skipped**。特别包含额外边界保护：SnapshotSeq=10、已提交状态 Seq=8 的副本拒绝旧 WAL Seq=9。
- Common 之前已证明 **199/199**，本轮只改变 Order/Trade 业务仓库，没有额外 Common 源码修改。合计 199+338+243=**780** 个已执行测试项，0 失败、1 skipped。

### 上线安全门禁（尚未完成）

1. 本轮只完成业务状态机适配对象，**没有自动 Spring Bean/PartitionStateMachineRegistry 注入到运行中的 Order/Trade 生命周期**；正式注册需依赖已认证的 ZK assignment、分区恢复独占 barrier 及 startup readiness 默认为 NOT_READY。不能把“接口类可实例化”写成“自动 failover 已接管”。
2. `DurableRecoveryTransactionControl.JournalBaseline` 目前在 Common 隔离测试用受控模拟的 journal fsync；**必须由 Order/Trade 的真实 CQ4 rebase/fsync/reopen 与 physical local epoch fencing 证明接管**，特别要保证 install 中途进程退出时 ledger startup 不准继续 READY。
3. `TradeSnapshotStore.load` 采用较大的完整 Trade JSON，对超 128MiB 快照会拒绝；正式对外需流式 snapshot，避免大租户导致高内存/OOM。Order 当前 64MiB 限制同理，属于受控 Demo 阶段功能而非无限吞吐发布保证。
4. 源端 SourceHead 和 DataRead V2 当前每次读取反复证明 Snapshot+ZK，活动交易期间可能频繁安全失败，正式要做不可变快照和可 Pin 的 committed WAL 区间、Node TLS/mTLS 和密钥轮换，验证旧 Primary Publisher Fence。
5. 单分区灰度需要实现 **真实业务`ReplicatedStateMachine`注册→Common `recover()` → journal fsync/ledger `REPLAY_COMPLETE` → 挂单/余额/持仓/成交、Projection 水位独立验收 → 外部门禁 `READY`**，再进行持续业务 SIGKILL Primary 的真实 failover、rejoin、逆向切换。
6. MD 自动主切仍由 `scripts/check-md-failover-preflight.py` BLOCKED；归档保留 `HOLD`，不能自动删除。200 租户压测仍在此之后逐级验证。

### Mac Demo 最终只读核验

- `tests/check-demo-tenants-readonly.py`：**PASS_10_TENANT_SNAPSHOT**，10/10 Robot `RUNNING`、每租户 40 活动委托、10/10 双边盘口各 10 档。留存证据：`~/.opentradingcore/local-common-protocol-20261011/artifacts/final-business-state-machine-10tenants.json`。
- `tests/check-projection-consistency-host.sh`：Order/Trade `watermark_tail_mismatch=0`，`orphan_mutations=0`，`cross_partition_event_ids=0`；运行 `dc-saas-` 容器 **24**。
- `tests/verify-order-cluster-state-host.sh`：**256/256 READY、256 组 Snapshot 一致、0 Learner**，Order A 129 Primary、C 127 Primary、B 256 同步副本；Order 三节点无 OOM 或容器重启。现网依旧使用 `cluster-dev-local-orderepoch-4c7df72-20261011` 旧镜像，不是本轮业务状态机版本。

**本轮操作保持 10 租户 Mac Demo 不清理、不滚动镜像。** 真实业务源码已经上传验证分支，但 Common 自动 Restore/READY 尚未在线注册/故障注入，仍不得宣布线上 HA 闭环完成。
