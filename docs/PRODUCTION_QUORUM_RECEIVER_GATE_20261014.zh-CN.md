# 2026-10-14 生产接收端可信 Quorum / 恢复事务上线门禁

> 状态：**NO-GO / 只读审计**。本文不是发布授权，也不启用 Common recovery binding、MD 自动主切或 WAL 自动删除。

## 已核查的实现边界

- Common `ZkReplicaRecoveryAuthority` 从 ZooKeeper 读取当前 Assignment、`Stat.version`、Primary、Epoch，并要求传输源认证；它**没有验证独立投票节点形成的加密 Quorum 证明**。
- Common `DurableRecoveryTransactionControl` 有 Snapshot Seal、`INSTALLING`、业务 Journal 安装与 attest、`BASELINE_DURABLE`、`REPLAY_COMPLETE`；只有注入实际业务权限、独占屏障、持久化基线和 receipt 验证后才有意义。其完成不等于 READY。
- Common `VerifiedRecoveryStagingClient` 验证 Snapshot SHA 与连续 Committed WAL 帧；单源的 HMAC 与完整 WAL 区间的加密封存，不证明多数派或旧发布者已隔离。
- Mac Demo Compose `compose.yaml` 配置 ZooKeeper `server.1=localhost:32888:33888`；隔离 `compose.order-cluster-dev.yaml` 显式 `ZOO_STANDALONE_ENABLED=true`，不能据此宣称**真实跨物理节点 ZooKeeper Ensemble**。
- 当前运行中的 10 租户 Demo 不在本阶段热升级、清除、主切或强制故障注入范围内。

## 两层多数派必须区分

1. **ZooKeeper 控制面多数派**：从实时 ZooKeeper ensemble 配置与连接状态证明投票成员 ID、独立故障域、Leader/Follower 同步、quorum 可用；不可把容器副本/同一 Mac VM 误认为跨物理宿主机 HA。`isConnected()` 或读到 `READY` **不是**多数派凭证。
2. **业务恢复耐久证明**：Order/Trade 各自参与该分区持久化承诺的真实物理服务节点，以不同、可轮换且受保护的节点密钥签署**同一个**已提交范围；必须核对 ZK 中业务 Primary/Replica/Learner 身份、有效投票集合与门限。ZooKeeper ensemble 的票不能替代订单/账户业务节点的 WAL 持久化 ACK。

## 待接通的授权契约（全部满足才可能继续）

- 由生产接收端读取（而非调用方 JSON 提供）当前有效 ZK 投票成员与业务分区 Assignment，并冻结 `clusterId/service/partition/epoch/zkVersion/primary/target`；对过期 Session、非最新版本和跨物理故障域的伪多副本 fail-closed。
- 每个业务节点使用独立 key-id / 非共享密钥及可信轮换记录；验证每份证明的签名、角色、签名时刻、挑战随机数、过期时间、完整 Snapshot digest/长度/提交水位、已 fsync WAL 的连续 `from..to` 区间与根摘要。重复 node-id、重复 key-id、非投票成员、错分区、错 Epoch、范围不覆盖、重放全部拒绝。
- 业务多数派的计数以**当前分区承诺配置**为准，而非固定按 2/3 或 2/2 猜测；投票语义和 Joint Consensus / 重配置边界须与生产恢复协议一致，避免两个相交但不一致的授权集合。
- 接收端签名验证不能依赖源端自己提供的成员列表或待验公钥；成员与密钥必须来自独立可信配置/控制面。
- 在隔离 staging 中校验 Snapshot + 完整 WAL 区间与全部签名；进入业务排他恢复屏障前、安装 Journal 前、replay 后与 READY 前再次读实时 ZK 并复核 Quorum/fence。
- 接收端只允许 `NOT_READY -> INSTALLING -> BASELINE_DURABLE -> REPLAY_COMPLETE` 的持久化状态推进；文件与目录 fsync、原子提交、重启可重验。任何宕机、旧主仍可写、重复/缺口 WAL、错 HEAD 或新 Epoch 都保持 `NOT_READY`，不执行自动晋升。
- `READY` 是**独立外部门禁**：Order/Trade 原始 WAL/副本提交区间、MySQL Order/Trade Projection 水位与事件尾部、余额、资金流水、持仓、委托、成交、Open Orders、Execution 去重、Robot/MD 观察水位全量一致才允许对外服务。Projection 数据库水位相等只是必要条件，不能替代业务源端权威对账。
- MD 的 `snapshot(byte[])/diff(byte[])` 由 Common 管恢复机制，业务负责从 Order 权威**全市场**镜像与连续增量恢复；未取得旧发布者 fence、Order Head 与完整市场覆盖证明，不开放自动主切。

## 最小验收顺序（全部独立证据）

1. 独立物理机上的 ZK 多投票成员、节点身份和业务 quorum voter 集合配置；审计键管理与轮换，不复制私钥进 Git/镜像或任务日志。
2. Common 可信成员解析、Quorum Proof 校验及接收端独占恢复事务，先用全部负例测试：假节点、重复签名、缺票、旧 Epoch/Version、失效密钥、重放、截断 WAL、离散范围、部分 fsync、ZK 断联。
3. Order/Trade 各做一个隔离分区端到端 Staging/Seal/Journal install/Replay，SIGKILL 覆盖 INSTALLING、BASELINE_DURABLE、REPLAY_COMPLETE 三个持久化窗口，复位仍保持 NOT_READY。
4. 资金/持仓/委托/成交/Projection/MD 的权威一致性报告必须给出分区、Epoch、Seq、hash、差异数、查询证据及退出码；任何缺项为 NO-GO。
5. 全链路通过后再将 Common -> com.app.dc -> 业务镜像发布为不可变 tag/digest；按单节点小范围部署与真实 failover/role reversal 验收，并在此后测试 50、200 租户的 TPS/P99/IO/恢复耗时。

## 本阶段有意未做

不变更当前 Docker 容器、ZK 角色、数据库或日志保留；不宣称可信 Quorum 恢复已接通，不因单元测试 PASS 就开启 `commonBinding.enabled`、MD 自动主切或过期日志删除。

部署仓库中的 `tests/projection_watermark_tail_gate.py` 是**只读必要检查**，使用一个 MySQL REPEATABLE READ 一致性快照与固定分区索引查找；异常时返回 NO-GO，不自动放行发布。