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

### Snapshot 正好覆盖 HEAD 的边界修复（Trade `eefcf76`）

- 在 Common 新鲜 Snapshot 恰好覆盖已提交 HEAD 时，`snapshotSeq == committedHeadSeq > 0`，虽然之后没有新的 WAL 增量，但这个**正序号的有效快照**仍可以接受独立物理节点的零长度 WAL 窗口摘要；原来的新接收端校验过于严格地拒绝 `<=`，已改成只拒绝倒退的 `<`。
- 这不表示可以接受**初始空快照**（`snapshotSeq=0`）；该情况仍需独立的可信空分区恢复协议。
- 新增回归测试，全量 Trade 本地 Maven **315 项通过、0 失败**。本地镜像 `dc-saas/tradesvr:cluster-dev-checkpoint-head-20261016`（`sha256:95bea313d5fffb5c4a80ca19464d001ef8f54e0fecbd96ff658fcc224cdf252c`），**未替换 Demo**。
- 真实 Demo 全量只读核查：A/B 各256份 `latest.json`，**全部 Epoch1 / snapshotSeq0**，且运行日志明确 `Trade periodic snapshot disabled`。这是真实恢复阻断，不是少打印一个 READY 日志。
- GitHub 的 Trade `eefcf76` 和 dc-quant-deploy `a14aea2` 均由 Mac 经本地代理推送到独立开发分支，未使用 Actions，尚未合入 `saas-crypto`。下一步必须先在新版 Demo 验证定时 Snapshot、B 的 WAL/持仓业务状态和源端冻结证据，然后再接通 Common 的受权 Epoch 交接及反向故障注入。

### A 单分区存活保障：交接准备失败后的自动安全取消（Trade `da14fcc`、`f40adb4`）

- 修复源端 `TradeStateCoordinator.preparePartitionHandoff` 在**持有分区写锁**完成本地冻结后，遇到瞬时 WAL/ZooKeeper 后置校验异常而长期冻结该分区的问题；当确认旧主仍持有**完全相同 ZK 版本 / Epoch / Primary**，提交 WAL 物理 fsync、提交 marker 和 READY 全部有效后，自动撤销失败的准备并让 A 继续交易。
- 如果控制面持续断开，保持冻结。支持在 ZK 恢复后调用 `abortIncompletePartitionHandoff`，再次校验来源与 WAL、仅解除匹配的未完成交接；即使 B 此时不在线，A 仍可在保有主权时恢复正常业务。
- **失败闭合**：若 ZK 版本已变化、B 已成为新主、WAL 存在分叉/未提交尾部、分区不 READY 或 seal 已完成且被错误调用异常取消接口，则保留冻结，拒绝不可信旧 Epoch 写入。不触及 ZooKeeper CAS，不授权自动主切。
- 新增持续断联、瞬时断联、B 离线、WAL 变动、Epoch/ZK 变动、其他分区正常交易等真实 Chronicle WAL 测试。Trade Maven 全量 **319 项通过，0失败**。
- 本地新镜像 `dc-saas/tradesvr:cluster-dev-safe-auto-abort-20261016` ID `sha256:5edc5cf78906ae2b36d4c2256be0b25554f1bb2291c2e83a79b9d701ec2b08c2`，与 Demo 使用相同的 Common 3.0.22-SNAPSHOT JAR SHA。**此镜像尚未部署。**

### B 跨 Epoch 恢复阻断（实际代码核实）

- Common 的 `SnapshotRecoveryBoundary.requireInstallable` 已抽象 `CROSS_EPOCH` 和 `SAME_EPOCH_FORWARD`。因此不必新建状态机。
- 但 Trade `TradeCertifiedRecoveryAdmissionGate`、`TradeCertifiedRecoveryReceiver`、`TradeCertifiedRecoveryAssembly`、`TradeRecoveryReplicaJournalBaseline` 当前**只允许同 Epoch 的前向 Snapshot 安装**，并拒绝有重叠/分叉物理尾部的 B。真实 Demo B 的旧 Epoch1 WAL 无法直接被当前源 Epoch2 Snapshot 安全覆盖。
- 还需设计并实现**Common 鉴权的跨 Epoch 可信完整安装事务**：源端仍有真实 ZK 主权 + 持久 HEAD，接收端旧日志不可静默删除，安装/重启中间状态继续阻止 READY；对已失去第二副本期间的 A-only 提交，不能凭空伪造 B 的历史多数派 ACK。
- 在代码与真实 Demo 上证明此链路之前，不执行自动 128/128 回迁、反向 SIGKILL A 或将简单 ZK READY 视为资金/持仓恢复成功。


## 2026-10-16 进一步验收｜Trade 跨 Epoch 旧日志完整封存

- Trade commit `1fcfc3ea0dcc7a955c6e94c90be8c6a217b6f8ce`，开发分支 `fix/trade-safe-auto-rebalance-20261016`，**已推送 GitHub**。
- 新增 `TradeCrossEpochReplicaTailSeal`：仅在 B 有真实 ZooKeeper Replica 身份且被 `TradeRecoveryReplicaFence` 的业务分区锁隔离后，先写持久 `tail-intent`，再复制旧完整 Snapshot、通过多次固定窗口读取**全部**旧 Chronicle WAL 原始 wire（而非只拿尾部 4096 条），独立 SHA256 校验并保存清单；若中途崩溃或 ZK 版本变化，旧意图仍阻止 READY。
- `TradeCertifiedRecoveryReceiver.preserveOldEpochReplica` 为显式、默认关闭的前置入口。仅保留旧数据证据，**不调用**原有同 Epoch 认证恢复、不执行 destructive rebase、CAS 或投票主切。
- `TradeRecoveryInstallGuard` 已补足旧日志封存意图扫描，防止进程重启后遗忘未完成的跨 Epoch 恢复。
- 实体 WAL 实验：旧 Epoch 实际 4102 条 Chronicle 记录封存跨越 Common 的 4095 记录单区间限制；另外验证初始 Snapshot、完整证据哈希、ZK/本地Epoch差异拒绝与重启后 NOT_READY。Trade Maven 全量 **324 项通过，0 失败/0 跳过**。
- 本地镜像 `dc-saas/tradesvr:cluster-dev-cross-epoch-tail-seal-20261016`，image sha256 `c34dff9c273dfd05886e9f614baac8397bfe3df98949fc6c62846b21eb0643aa`，使用同一份 Common JAR SHA256 `8cbb195a131664c96692598bef51644ced9074f01ad80b3878b84cfce9444da4`；仅本地构建，未替换 Demo。
- 部署仓库非破坏性回归：`test-trade-cluster-config.sh`、`test-md-cluster-config.sh`、`test-order-cluster-c-config.sh` 均 PASS；Trade 12 项前置/transition Python 测试及 MD 20 项 transition/shadow 测试通过。
- **本轮 ZooKeeper 实测：Order 256 READY（A=128、B=128），MD 256 READY（A=128、B=128），Trade 256 READY（A=256、B=0，其中 Epoch1=128、Epoch2=128）**。Trade Demo 镜像仍旧 `cluster-dev-fenced-transport-20261016`，A/B 周期 Snapshot 设置均为 false，A/B 各256份旧 Snapshot 均为 Epoch1/seq0。磁盘 88%，剩余约 52GiB。
- 只读 Trade Failback 检查：128 个原属 B 的 Epoch2 分区，健康记录 123 个缺失、5 个过期；`automaticPrimaryChangeAuthorized=false`、`safeToSigkillAForReverseTest=false`。缺失健康记录的可能包括原本没有成交的空分区，不能直接等同于丢数据；但无独立可信证明前不能用 READY 填补。
- **本次未完成 HA 总验收**：Common 已有 CROSS_EPOCH 边界判断，但生产可信接收端从 A Source HEAD 恢复新 Epoch 的**实际安装事务、回放后的资金/持仓/委托/成交及 Projection 对账、B 重新成为同步 Replica、受权 Epoch 主权转换**尚未开发/联调闭环。现有 `CertifiedRecoverySourceAuthority` 强制要求当前物理投票多数派对同一个原始 WAL 区间签名，若 B 正是落后的唯一副本，不能凭空制造历史 B 的 ACK。必须设计经 ZooKeeper 真正选主/原主隔离授权的新 Epoch bootstrap，然后恢复 B、完成新的同步多数派证据；这不是简单切换路由或删旧 WAL。


### 2026-10-16 后续推进：跨 Epoch 恢复中断修复和签名数据暂存

- Trade 新提交 [`27cdc8a`](https://github.com/bliplink/com.app.dc.tradesvr/commit/27cdc8a470641ecda4b3589541c85525eaf6afba)：补旧日志封存**mkdir 后、intent 写入前**崩溃空窗。重启后的 `TradeRecoveryInstallGuard` 现在只要发现 `cross-epoch-old-tail` 目录（即使空目录或损坏的 marker）就保持 NOT_READY。原始 Snapshot/WAL 清单现在可从磁盘重新载入并逐帧审计顺序、Epoch、原始 wire 和 SHA256；封存成功也强制走一次该磁盘审计。不允许修改、重写、清理旧证据假装已恢复。
- Trade 新提交 [`7d7da00`](https://github.com/bliplink/com.app.dc.tradesvr/commit/7d7da00f37551f9260dc12c4ab54b25fed24a3b4)：`TradeCertifiedRecoveryReceiver.stageCrossEpochSource` 作为**显式、默认关闭**的恢复阶段 1，先完整审计 B 的旧证据并要求精确匹配实际 oldEpoch/oldTailSeq，再验证真实 ZooKeeper 主副本及版本、独立物理节点密钥；调用 Common `VerifiedRecoveryStagingClient.stageWithSourceManifest` 对当前 A 的 HEAD、Snapshot 与完整提交 WAL 逐段认证暂存，事后复核 ZK 角色与旧封存证据。此过程**绝不**安装新 Snapshot、重写 CQ、清除恢复标记、授权主切或开放 READY；也不能伪造 B 停机期间不存在的历史多数派 ACK。
- 跨 Epoch 封存覆盖 >4095 条物理 WAL，额外回归覆盖旧封存内容篡改、意图/清单不匹配、仅存空目录的异常重启、源 HEAD 与封存的旧 Epoch 身份不匹配。Trade 全量 **328 测试通过，0 failures、0 errors、0 skips**。测试涉及模拟接收端与 Chronicle 旧 WAL；**当前尚未执行真实 A↔B 网络传输恢复验收**。
- 本地 ARM64 镜像 `dc-saas/tradesvr:cluster-dev-cross-epoch-signed-stage-20261016`，镜像 `sha256:93ff91ce7fb8c12a2433cadc4dafca45d4e69e538dd241eaf2713142dc92bd25`。已核验镜像 Entrypoint 的 Java `CLASSPATH=classes:config:lib/*`，新类在运行路径内。Common JAR SHA256 `8cbb195a131664c96692598bef51644ced9074f01ad80b3878b84cfce9444da4`。**没有替换 Demo，不触发 Actions**。
- **关键剩余问题仍未闭环**：独立可信 Quorum/权威恢复许可下新 Epoch 的物理 Snapshot/CQ 安装、重放后资金/持仓/委托/成交/Projection 的权威一致性、接收端业务 READY 和自动回迁的 Epoch-fenced CAS、双向真实故障注入。Common 通用 CROSS_EPOCH 边界尚不能单独给 Trade 跨 Epoch 数据删除/安装授权。当前阶段严禁将经过签名的“暂存成功”冒充正式恢复成功。


### 2026-10-16 B 端跨 Epoch 物理安装与崩溃重试（新增）

- Trade commit [`6823bd8`](https://github.com/bliplink/com.app.dc.tradesvr/commit/6823bd88dcc16283169641a7d7226917b0118e47)，分支 `fix/trade-safe-auto-rebalance-20261016`。
- `TradePartitionJournal.rebaseCertifiedCrossEpochSnapshot` 新增与现有同 Epoch 接口**隔离**的物理恢复路径：拒绝篡改旧 Epoch/旧 Seq、拒绝 Epoch 降级、拒绝重复归档同一旧 WAL。支持新 Epoch 已认证 Snapshot 的序号比 B 旧 Epoch 未提交尾部**更小**，并把旧原始 Chronicle Queue 保留在本地 `.archive`。
- `TradeRecoveryReplicaJournalBaseline.forCertifiedCrossEpoch` 新增维护模式：逐项核实 B 旧 Epoch 完整封存的 Snapshot/WAL SHA+身份，要求 Common `DurableRecoveryInstallLedger` 精确处于 `INSTALLING` 且与完整的新 Snapshot/HEAD 水位及哈希一致；进入同一业务分区 Fencing Barrier 后才允许新 Snapshot 基线安装与旧 CQ 归档。中断后同一签名请求可比对磁盘上新基线完成重试，保证旧 WAL 不会被再次归档，READY 一直关闭。
- 新增真实 Chronicle Queue 测试：旧 WAL 归档和新基线磁盘冷读；原始尾部高于新 Epoch Snapshot 时的隔离安装；旧证据被篡改、ZooKeeper 版本变化、Common Ledger 缺失、Ledger 非 INSTALLING 阶段、崩溃重试和重复封存旧 WAL 均拒绝或保持幂等。Trade Maven **333 项通过，0 错误/0 失败/0 跳过**。测试中的认证 Authority 是离线替身，**不等于 Demo HA 故障注入通过**。
- 新本地 ARM64 镜像 `dc-saas/tradesvr:cluster-dev-b-physical-install-20261016`，镜像 `sha256:671c3f68d1b6f311c0feb995a99f887da8d0d192ec8a6c064a7fa6f37bda90b9`，Common JAR SHA256 `8cbb195a131664c96692598bef51644ced9074f01ad80b3878b84cfce9444da4`。镜像类路径核查通过；未替换 Demo。
- **仍未通过生产端到端恢复**：Common 当前 `CertifiedRecoverySourceAuthority` 的物理多数派要求可能与“B 尚未恢复新 Epoch WAL”的故障状态形成循环，不能制造伪造的 B ACK。需基于合法的新主选举/旧主隔离证据单独设计可信新 Epoch bootstrap 授权，再接已实现的物理安装分支、补业务/Projection 权威对账、接收端 READY 与 A/B 128/128 Epoch-fenced 主权转移。未完成前不执行真实切主或 SIGKILL A。

## 防止误验收

- `python3 scripts/check-trade-failback-preflight.py`：只读检查，输出永远 `automaticPrimaryChangeAuthorized=false`，直到另行完成完整可信交接机制。工具的奇数分区候选判定**只适合本次 Demo 恢复记录**，不是真实调度的主权事实来源。
- 无任何文件尺寸、MD/Trade 表面 READY、Robot RUNNING、10 条 WAL 接收日志足以证明 256 分区恢复。
- GitHub Actions 暂时无额度，所有代码先走 Mac 本地 Maven/镜像，完整验收后再决定是否合入 `saas-crypto`。
- Demo 可清理重部署，但不得以清理数据代替对真实故障后未丢单、无重复成交、无双主的验收。
