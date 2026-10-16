# Trade HA 自动回迁闭环｜2026-10-16

> 本文件记录实际 Mac mini Demo 验收与尚未达成的安全机制。不要把“READY”“Replica 已接收部分 WAL”或“ZK CAS 成功”解释为可安全迁移 Primary。

## 本轮真实数据

- 运行镜像 `dc-saas/tradesvr:cluster-dev-fenced-transport-20261016`。
- Trade-B 被 SIGKILL 后，Trade-A 接管 256/256 分区；Trade-B 恢复后 A=256，B=0；Epoch1/2 各128个，均显示 READY。
- `scripts/check-trade-failback-preflight.py` 全量读取 ZooKeeper 256 个分区及 replication-health；原属 B 的奇数分区128个，预检查时124个无健康记录、4个健康记录超时。
- **自动切回资格 0/128（仅初步复制健康指标）；自动授权=false，反向故障注入资格=false。**
- Docker 24/24 运行，不意味着完成业务自动恢复。
- Trade 源码分支 `fix/trade-safe-auto-rebalance-20261016`、commit `6477fd2` 已实现健康 ACK 水位的节流发布；本地 Maven 全量300项通过；本地镜像 `dc-saas/tradesvr:cluster-dev-health-progress-20261016` 已构建，但正式 Demo 未替换。GitHub Actions 不运行。

## 已确认的机制缺口

1. `TradeFailoverController.pollOnce()` 当前只处理 **原 Primary 在 ZK 中已失联**，存活即 `continue`。恢复 B 后没有自动 failback 的触发器；要补“失联接管”和“存活主节点受控回迁”两个明确路径，但共用 Common 状态机与仲裁机制。
2. `TradeStateCoordinator.publishReplicationHealth` 原来只在角色/降级标记变化时发布，同 Epoch 正常 ACK 水位会陈旧；Trade `6477fd2` 已修复，但未部署验证。
3. ZooKeeper replication-health 目前只有10/256分区。空闲分区不能伪造“有复制成功的 commit ACK”：应复用 Common 的**可认证空分区基线**；非空分区必须有 Snapshot + 连续、原始 WAL + committed watermark / digest 的可验证接收状态。
4. `TradeRecoverySourceHeadProvider` 有挑战绑定的 HEAD，但其注释明确 HEAD **不是** 独立 Quorum ACK 或完整接收端镜像证明。当前 Trade `TradeRecoveryQuorumMembershipGate` 是恢复场景的投票成员校验，而不是允许活跃 Primary 交接的授权证明。
5. `tests/trade_cluster_transition_host.py` 的 `switch-primary --apply` 是 CAS 写分区的操作工具，并未建立“旧 Primary 先停止新提交 + B 接收端可信完成证明 + 对账 + 旧主隔离”。**不准在现有 Demo 上直接批量执行。**

## 最小正确实现（不扩新产品功能）

整个活跃主权交接必须由 Common 原有状态机、恢复 Proof / Quorum 组件提供通用安全门槛，Trade 只提供业务状态 apply/snapshot、持久提交 HEAD 和权威账户/持仓校验。

1. **候选识别**：控制器按明确的持久预期放置布局识别 B 应收回的128分区（Demo 是原始奇数分区），不能根据“当前负载均衡”推断历史主权。B 掉线时 A 持续交易，不因 B 卡住而丢失 Primary READY。
2. **目标副本准备**：B 完成 Common 可信 Snapshot + WAL 原始续传、全量前缀校验、提交序号与哈希、Epoch/assignmentVersion/物理节点身份绑定、完整接收安装事务；空分区使用可信初始空基线的专门门槛。接收端不能自称 READY 或自行修改 ZK。
3. **源端固定交接 HEAD**：A 按分区持有与业务突变共用的锁，封闭这一分区的新交易写入，完成未结事务和 WAL fsync，读取一致的最终 Source HEAD（包含原 Epoch、ZK 版本、提交 marker、state seq、签名），防止旧主在签名后继续提交。
4. **同一交接点验收**：B 按 A 冻结 HEAD 验证连续 WAL、持久 ACK、状态映像和资金/持仓权威快照；独立物理成员和真实投票成员签名、接收端恢复事务等由 Common 核验。**任一条件失败：不得 CAS；A 继续做 Primary 并解开冻结，B 只做 Replica。**
5. **Epoch 切换 + 旧主 fencing**：只有在第4步完成且 A 的逐分区业务写入仍被冻结，ZK 版本 CAS 才把 Primary 变为 B，并增加 Epoch；A 本地永久撤销旧 Epoch 写权限，B 恢复后才发布新 Epoch READY。故障重试必须幂等，无双主、不能回滚已经生效的新 Epoch。
6. **恢复正常分工**：按小批量推进，逐分区记录切换耗时、业务中断、A是否持续服务其他分区、B追平证据，最终 `A=128,B=128`；检查订单/成交/资金/持仓/Projection watermark，再做反向 `SIGKILL A`，重复闭环。


## 2026-10-16 后续源码实装（阶段一：冻结并封存 Source HEAD）

- Trade 开发分支：`fix/trade-safe-auto-rebalance-20261016`，**commit `1a01beaf5ae0c62a13ce29376799b3fb288239a4`**，未合入 `saas-crypto`。
- `TradeStateCoordinator.preparePartitionHandoff(partition,target,epoch,zkVersion)`：只对单个分区锁定；等待已开始的业务动作结束，要求真实 ZK Primary/Replica/Epoch 版本一致、健康 ACK 足够新且覆盖完整本地已提交 WAL、无已知降级；按分区 fsync，记录本地 seal，拒绝该分区后续写入。**不会更改 ZK 主权**。
- `cancelPartitionHandoff`：仅当**相同** ZK 版本/源 Primary/Epoch 和本地封存提交序号仍完整时，才安全解除写入冻结。交接期间出现 ZK 版本漂移、WAL 持久化失败或封存失败，旧主保持 fail-closed，而不是自动重新交易。
- `TradePlannedHandoffSourceHead`：封存窗口内复用 Common 既有的 `TradeRecoverySourceHeadProvider`，验证 Source HEAD 与冻结的提交 marker、Epoch 上限和 ZK 版本一致。HEAD 仍**不是** Quorum ACK、目标已完全追平证明或切主授权。
- 新增 `TradePartitionHandoffFenceTest` 并覆盖真实物理 Chronicle WAL、未提交尾部、健康证据过期、交易并发、单分区隔离、ZK CAS 竞态、过期签名 HEAD 拒绝。
- 本地 Trade Maven 全量回归：**307项，0 failure，0 error，0 skipped**。
- Mac 本地镜像：`dc-saas/tradesvr:cluster-dev-handoff-seal-20261016`，镜像 ID `sha256:81840683fedbf5def1230a15ae759fc13bd789129da6ccc93910de5c639e6f63`，Common JAR SHA256 `8cbb195a131664c96692598bef51644ced9074f01ad80b3878b84cfce9444da4`。
- **尚未替换 Demo**；当前上线仍为 `cluster-dev-fenced-transport-20261016`。新代码属于第一阶段，未接入自动 Failback 控制器，不具备实际自动切换能力。

### 下一个代码阻断

1. B 必须先完成受 Common 可信状态机保护的完整 Snapshot/连续 WAL 前缀及物理接收端事务证明，不能用 ZooKeeper 的 `replicatedSeq` 或空闲 Snapshot 代替。
2. 在冻结期间取得真正的 Source HEAD 与 B 的**独立**接收端签名/水位证明（必须同一分区、Epoch、ZK 版本、提交头），验证业务持仓/余额与 Projection 权威水位。
3. 完成 Common 主权转移授权、原 A 隔离和新 B 的 Epoch CAS + READY 流程；当前 `TradeFailoverController` 仍只支持主节点死亡后晋升。未经真实联调确认，不自动执行 `switch-primary --apply`，不做反向 SIGKILL A。


## 2026-10-16 进一步推进：B 端原始 WAL 物理多数派资格核验与 Snapshot 配置

- Trade 分支新增 `9d0fa7f79af8ef52d8b4cf03b0f6d89874ac35f1`：`TradePlannedHandoffReplicaVerifier` 在 B 本地检查**完整持久 WAL 的提交尾部与 Snapshot 哈希**，并使用 Common `VerifiedRecoveryQuorumClient.requireFreshPhysicalQuorum` 对每一物理投票节点的 WAL 摘要、提交标记和独立节点签名进行新鲜的多数派验证。复核前后 ZK Epoch/版本及 B 的本地 WAL 水位；若有任何差异 fail-closed。
- 该验证器默认关闭（`trade.cluster.failback.certifiedReplicaVerifier.enabled=false`），不会签发 CAS/READY 准许，也不能代替资金、持仓、订单、成交、Projection 的独立权威对账。新代码目前未被自动回迁 Controller 调用。
- 本地 Maven 完整回归 **314 项全通过**；新本地镜像 `dc-saas/tradesvr:cluster-dev-recipient-quorum-20261016` 构建完成，镜像 ID `sha256:4d2a08ffa4eef4ad69bdf4c41cbc2d0ff79b4b9a808951ae9a7f946a0ada2a75`，Common Jar SHA256 `8cbb195a131664c96692598bef51644ced9074f01ad80b3878b84cfce9444da4`。**没有替换运行中的 Trade-A/B**。
- Demo 真正运行日志：Trade-A 于 13:07、Trade-B 于 13:07 和 13:36 均明确打印 `Trade periodic snapshot disabled`。检查磁盘发现 256 个分区各有初始化 Snapshot，但抽样的 `snapshotSeq=0`，与正在增长的 WAL 不一致；不能用初始化快照冒充新 Epoch 的可信完整映像。
- 发现 `deploy-saas.sh` 全量集群配置以前**只在缺少** `TRADE_CLUSTER_PERIODIC_SNAPSHOT_ENABLED` 时追加 `true`，明确配置为 `false` 的旧 `.env` 会覆盖，因此修复 `apply_full_cluster_profile`：通过 `upsert_env_value TRADE_CLUSTER_PERIODIC_SNAPSHOT_ENABLED true` 强制开启 HA 验收的周期快照。其他非 full-cluster 环境仍可选择关闭。对应 `tests/test-trade-cluster-config.sh` 检验通过。
- 后续上线时，仍需实测定时快照成功（包括主/副本当前 Epoch、水位、原始 WAL 数据链）、检查磁盘 87% 占用与归档清理，再开始受控自动回迁和反向 Kill。当前 B 128 分区**没有**达成实际恢复交接验收条件。

## 防止误验收

- `python3 scripts/check-trade-failback-preflight.py`：只读检查，输出永远 `automaticPrimaryChangeAuthorized=false`，直到另行完成完整可信交接机制。工具的奇数分区候选判定**只适合本次 Demo 恢复记录**，不是真实调度的主权事实来源。
- 无任何文件尺寸、MD/Trade 表面 READY、Robot RUNNING、10 条 WAL 接收日志足以证明 256 分区恢复。
- GitHub Actions 暂时无额度，所有代码先走 Mac 本地 Maven/镜像，完整验收后再决定是否合入 `saas-crypto`。
- Demo 可清理重部署，但不得以清理数据代替对真实故障后未丢单、无重复成交、无双主的验收。
