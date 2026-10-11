# Common 状态机按 Assignment/Epoch 注册和 Chronicle 磁盘水位门禁（2026-10-11）

## 范围、代码与完成事实

本轮延续统一 Common 状态机恢复设计，不重复在 Order/Trade 做选主。三个仓库代码均已提交并推送：

| 仓库 | commit | 分支 | 变更 |
|---|---|---|---|
| Common | `fb6bd8a` | `saas-crypto` + 独立验证分支 | `AssignmentBoundStateMachineRegistry`、`DurableJournalBaselineProof` |
| Order | `72d1f38` | `codex/order-durable-primary-common-source-20261011` | `OrderCommonRecoveryBinding`、生命周期入口、真实 Chronicle 基线校验入口 |
| Trade | `6fbae73` | `codex/trade-durable-primary-common-source-20261011` | `TradeCommonRecoveryBinding`、生命周期入口、真实 Chronicle 基线校验入口 |

原有 Common Snapshot/WAL 双向认证、Staging、Committed WAL Pair 检查、`StateMachineRecoveryCoordinator.recover()` 和 Order/Trade 业务 Restore/Apply 继续复用上轮的工作。**没有更新线上镜像、没有在真实 Mac 集群 SIGKILL、没有归档删除或业务数据重置。**

## 一、公共 Assignment/Epoch 注册机制

- 新增 Common 类 `AssignmentBoundStateMachineRegistry`，只在服务分区生命周期调用，不在撮合、风险或 CQ append 热路径中执行。
- 默认 `enabled=false` 不做任何操作。明确启动后要求**非空、去重、最多 8 个** `Pnnn` canary 分区白名单；错误配置拒绝。
- 只有 ZooKeeper census 返回合法 ROUTABLE assignment，且本物理节点是指定 Primary、Replica **或 Learner**，才注册相应的业务 `ReplicatedStateMachine`。Replica/Learner 也必须注册，否则故障接管时将找不到合法状态机。
- Epoch 变化时撤销旧机器并创建新实例；分区不再归本机时立即取消注册。调用 `requireRegistry(partition,epoch)` 必须与已录入的分区/Epoch 精确匹配；未知分区、错误 epoch 拒绝。
- 不会自行调用 Common `recover()`、Fencing、READY、Promotion 或 ZooKeeper CAS。
- **开关**：Order `order.cluster.recovery.commonBinding.enabled=false` + `order.cluster.recovery.commonBinding.partitions=`；Trade 对应 `trade.cluster.recovery.commonBinding.enabled=false` + `trade.cluster.recovery.commonBinding.partitions=`。只有显式开启且配置了 canary 分区时，现有 `OrderPartitionLifecycleManager` / `TradePartitionLifecycleManager` 才注册。
- 更底层的 `SourceHead`、`RecoverySourceDataControlHandler`、`Staging`、自动 Restore 和 READY 门禁目前仍独立关闭。**不要将 canary registration flag 当作 failover enable 或恢复批准。**

## 二、Common 持久化 Baseline 证明

- 新增 `DurableJournalBaselineProof.requireDurable`：从真实 Chronicle 逻辑分区目录 **重新读取** `baseline.properties`，拒绝 Symlink、非标准分区、无效大小、缺失字段；核对 SnapshotId、`snapshotSeq`、目标 `localEpoch`、`committedStateSeq`、`committedStateEpoch`、`commitMarkerSeq`。
- 对文件及分区目录执行 fsync/force；读取后再复核完整属性值，任意不符 fail closed。目录 fsync 不支持时不会视为安全成功。
- Order、Trade 的 `PartitionJournal.attestInstalledBaseline(partition,snapshotId,request)` 增加**真实内存 baseline 与磁盘 baseline 双重比较**，供以后 `DurableRecoveryTransactionControl.JournalBaseline.attest` 正式接线；只读，不执行 rebase，需处于外部 exclusive barrier。
- 请勿混淆：**磁盘验证原语已完成，但本轮没有实现正式 JournalBaseline.install 的全自动状态安装**。没有启动时 Ledger 回放/隔离验证和真实故障注入，不满足自动 READY 条件。
- 在真实 Chronicle `rebase` 后篡改归档及磁盘文件的新端到端故障测试被执行环境安全检查阻止，故**没有**该测试通过证据；原有独立 Chronicle rebase 测试仍属于这次全量回归。

## 三、完整测试与限制

在 Mac 的独立隔离 Maven 源树 `~/.opentradingcore/local-common-protocol-20261011/source/` 使用 Java 8 Docker Maven 编译（不依赖 Docker 已部署服务镜像，不执行现网重启）。

- Common 新 `AssignmentBoundStateMachineRegistryTest` **4/4 PASS**（默认关、Replica/Learner 注册、Epoch 切换/撤销、非法分区/配置阻断）。
- Common 新 `DurableJournalBaselineProofTest` **2/2 PASS**（磁盘元数据精确匹配、错 Epoch/Snapshot、缺失或符号链接拒绝）。
- Common 完整 `mvn clean test install`：**205/205 PASS**。
- Order `mvn clean test`：**338 项、0 失败、1 跳过**。
- Trade `mvn clean test`：**244/244 PASS**。
- 总计 **787 项、0 失败、1 跳过**。测试结果不意味着真实 ZooKeeper Primary/Replica 的新自动接管已经通过。

## 四、明确后续门禁

1. **真实 CQ JournalBaseline.install**：在独立 canary 分区且已取得真实 ZK 物理 owner、Stat.version、Epoch、NOT_READY/独占 barrier 后执行；安装前先 durable seal 原始 Snapshot 到本节点权威 SnapshotStore（原样 SHA 和目录 fsync），再 Archive/Rebase 真正 CQ 基线；随后用本轮持久化证明复核，Ledger 才能从 INSTALLING 进入 BASELINE_DURABLE。中途断电重启不得 READY。
2. **真实业务恢复全链路**：由服务从真实可重试 Snapshot/WAL 读取会话调用 `VerifiedRecoveryStagingClient`，注入已注册的 Order/Trade 状态机，完整执行 `restore(byte[]) → apply(byte[]) → finishReplay`；最后再证明真实 CQ4 HEAD、资金/持仓/执行/挂单和 Projection watermark 一致、旧 Primary 被 Fencing。
3. **真实单分区故障注入**：故障期间持续下单/撤单/成交，SIGKILL Primary、接管、rejoin、role reversal；验收无双主、丢单、重复成交。
4. **性能/安全**：目前源端为每个传输块重算来源 HEAD，需 immutable Snapshot+WAL pin、可重试 transfer session；独立 HMAC 是双端身份，不代替 TLS/mTLS 隐私及密钥轮换。
5. **MD 自动主切 / Archive 自动清理**：继续保持阻断。MD 先证明 Order 全市场权威、旧发布者 Fence、MD/Robot READY；Archive 先验证跨归档边界追平及所有副本的最小 durable watermark。不能因为现有 10 租户健康就开放 200 租户或自动删除。
6. **发布链**：Common 正式 Maven Central 版本、`com.app.dc` 引用与 GHCR Linux/ARM64 发布尚未处理。Order/Trade 改动保留验证分支，不得当作线上正在运行的新镜像。

## 五、当前环境

Mac Demo 保留原 10 租户数据，不清数据、不重启容器、不自动恢复旧镜像。最终实际只读巡检结果：

- Order `tests/verify-order-cluster-state-host.sh` **PASS**：256/256 分区 READY、256/256 Snapshot 集合一致、0 Learner；Order A 129 Primary、C 127 Primary，B 为 256 分区 Replica，三节点无 OOM、0 重启。现网仍为**旧本地镜像**。
- `tests/check-projection-consistency-host.sh` **PASS**：Order/Trade `watermark_tail_mismatch=0`，`orphan_mutations=0`、`cross_partition_event_ids=0`；24 个 `dc-saas-` 容器运行。
- `tests/check-demo-tenants-readonly.py` **严格单次结果 FAIL**：第一次 `CZUURC` 39/40，第二次 `V6L43Q` 39/40；10 个租户 Robot 均 RUNNING、双边盘口均有效。**不得将上述两次失败声称 PASS**。
- 针对上述两个租户只读抽取 12 次、约 22 秒活动委托数：两者大部分时间为 40/40，最后一轮 `CZUURC` 39，属于可能的成交补单瞬时窗口，但未证明 10 分钟以上稳定补单时延。证据文件：`~/.opentradingcore/local-common-protocol-20261011/artifacts/final-common-epoch-register-10tenant.json`、`final-common-epoch-register-10tenant-recheck.json`、`common-epoch-binding-robot-transient-samples.json`。
