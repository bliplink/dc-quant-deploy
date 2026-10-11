# Mac Demo：MD 二次 Fencing、Common 恢复接线及 Archive 样本核验（2026-10-11）

## 背景与范围
此前 10 租户环境中的 Order 256/256 READY、B 恢复为同步副本、Trade 持仓与空分区故障恢复均已有独立证据。本轮**不重装、不清数据、不 SIGKILL MD**，检查真实运行环境后，在 MD 独立工作树补充两阶段 CAS 的安全门禁，检查 Archive 实际文件。

## MD RECOVERING → READY 二次安全门禁
- MD 现有 `MdImageRecoveryFailoverController` 采用 `READY(epoch N)→RECOVERING(epoch N+1)→READY(epoch N+1)` 两次版本化 CAS，恢复状态禁止发布实时数据。
- **已发现的不足**：此前 READY 阶段要求 Order 完整镜像，但是不再独立验证该恢复 Epoch 对旧 MD 发布者的**持续隔离**。在恢复镜像期间，原发布者可能重新连接；早期故障识别时的安全证明不能自动延伸到 READY。
- 新增 `Safety.requireRecoveryEpochPublicationFence(recovering)`，默认实现**直接拒绝**，即任何旧实现若未提供最新 Epoch 的独立网关/发布者 Fence 证据，都不得将分区从 RECOVERING 切回 READY。
- 当前实现在证明 Order 全量镜像之后、写入 READY CAS 之前再次调用独立 Safety 证明；失败结果为 `FENCING_UNPROVEN`，保留 RECOVERING。CAS 的 ZK 版本、控制器 Lease 与候选者当前存活检查仍继续执行。
- 针对性 `MdImageRecoveryFailoverControllerTest` + `MdAutomaticFailoverServiceTest` **16/16 PASS**；MD 全量 Java 8 Maven 测试 **126/126 PASS**。
- MD 源码 `com.app.dc.mdsvr` GitHub `saas-crypto` commit `2305aea` 已推送，**未替换 Mac 在线镜像**。自动故障切换默认仍关闭，尚无可信 MD `Safety` 实现；因此本次不能宣称 MD 自动 HA 通过。

## MD 实盘前置安全检查
当前已运行 `scripts/check-md-failover-preflight.py --expected-image dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101`，独立本地镜像白名单审计：
- 256/256 分区 READY；MDSvrA / MDSvrB 各 128 个 Primary。
- 三台 MD 均在线、有 ZooKeeper 临时成员 ZNode；256/256 分区有至少一个被分配的候选恢复副本。
- `canInjectMdPrimaryFault=false`、`decision=BLOCKED`：尚需**权威 Order 最新全量市场镜像**、恢复期间及 READY 前旧发布者 Fence、恢复后整盘口一致与 Robot 对单证明。这些不能用本地镜像名、进程在线、ZK READY 或内存书上的10档报价替代。
- 原始证据 `~/.opentradingcore/local-common-protocol-20261011/artifacts/md-failover-local-lock-20261011.json`。

## Common 公共恢复接口目前真实状态
- Common 已具备 `ReplicatedStateMachine.apply(byte[])`、`snapshot(ChunkSink)`、`restore(ChunkSource)`、`PartitionStateMachineRegistry`、`StateMachineRecoveryCoordinator`、签名/校验与安装账本。
- 上轮 Common `3a77c61` 和 Order 验证分支 `e885491` 的 `Common→com.app.dc→Order` 隔离 Maven 编译测试通过（Common 170/170、Order 323 项零失败，1 跳过）。
- **关键剩余依赖**：Order 和 Trade 的 `OrderCommonRecoveryController.VerifiedTransport` / `TradeCommonRecoveryController.VerifiedTransport` 定义已经存在，要求同一传输源负责来源认证和 committed WAL，但生产中还没有真实认证的网络来源实现/启动接线，`commonBinding.enabled` 默认关闭。不能只改开关替换成熟的 HA 主流程。

## Archive / Journal 只读证据与限制
- 本轮核对真实 Order P200（此前故障后 Epoch 2→3 重基线的核心分区）两份**封存**归档：
  - Order B: `P200-epoch2-seq22015-1791715909739`，3 个文件，逻辑长度 `84,017,357` Bytes。
  - Order A: `P200-epoch2-seq22014-1791714943397`，3 个文件，逻辑长度 `84,017,357` Bytes。
- 通过 `scripts/manifest-order-archive-segment.py` 对两份真实 CQ4、metadata.cq4t 和 baseline.properties **完整读取 SHA-256**，两次均通过文件不可变性扫描（检查前后的 inode、size、mtime）；结果写入 `~/.opentradingcore/local-common-protocol-20261011/artifacts/archive-samples/`。
- Order A/B 归档段的哈希值不同，属于**不同节点的不同重基线序号/文件元数据**，不能将字节不同单独解释成业务分歧；同样不能据此声明跨归档追平已经成功。
- 两份 manifest 都明确 `deletionAuthorized=false`、`retentionDecision=HOLD`。归档没有删除。Archive+Active CQ 的源码单元/集成测试之前通过，但**还必须做生产形态的真实跨归档边界重放**、Snapshot 校验、故障恢复后副本及 Projection 水位比较，才能解除保留门禁。

## 后续（真实未完成项）
1. 为 Common `VerifiedTransport` 实现、接入真实 Order/Trade 当前 Primary 签名或认证的 Snapshot + committed delta 网络传输，再把 Common 主协调器灰度接入单业务分区；独立确认恢复 NOT_READY→外部门禁 READY，不能放松已验证旧 HA。
2. 让 Order + Gateway 为 MD 提供源自权威 Order 的**全量市场 inventory + 版本水位 + 老发布者 Fence**；实现 MD Safety 真正独立的来源验证和持续隔离，然后再做单分区灰度、最后真实 SIGKILL。
3. 用隔离副本先通过 **Archive→Active Journal 连续读取** 与跨 Epoch Commit 校验，建立副本追平最小安全序号和保留水位，才能考虑任何日志自动删除。
4. 保持10租户场景业务回归，以上门禁过后才做20/50/100/200租户压测。
