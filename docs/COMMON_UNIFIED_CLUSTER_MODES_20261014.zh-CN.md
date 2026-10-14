# OpenTradingCore 集群统一：Common 一套内核，两类业务数据模式（2026-10-14）

## Common 唯一 HA 内核

所有服务复用 Common 的分区/角色生命周期、Epoch、ZooKeeper CAS、fencing、同步复制、提交 WAL、Snapshot、归档、恢复事务和 READY 门禁。Order/Trade/MD 只解释各自的业务 byte[]，不在服务里再建立并行的选主或复制控制平面。Gateway 继续只负责透传。

### 模式 A：Order / Trade 命令状态机

使用已有 ReplicatedStateMachine 接口：apply(byte[])、snapshot(ChunkSink)、restore(ChunkSource)。Common 保证提交顺序、独占恢复屏障、已认证 Snapshot 和最终 READY 校验；业务实现订单或资金/持仓的变更和恢复。

现状是 Order/Trade 已复用 Common 的部分组件，仍保留各自的 ReplicationManager 和恢复逻辑；尚未完成把全部运行时角色/复制控制收敛到 Common，不能说它们已经完全一样。

### 模式 B：MD Snapshot + Diff 业务模式

Common saas-crypto 提交 89ad54d 新增 SnapshotDiffStateMachine：

- byte[] captureSnapshot()：在 Common 一致性屏障中形成某个分区的完整业务快照。
- void snapshot(byte[] fullImage)：安装已经经过 Common 来源证明和完整性校验的快照，业务须原子完成或失败。
- void diff(byte[] committedDiff)：应用由 Common 证明来源、提交序号、Epoch、连续性的变化。

SnapshotDiffStateMachineAdapter 只负责把上述三种字节回调接至现有 ReplicatedStateMachine/StateMachineRecoveryCoordinator，**没有新增日志、选主器、传输协议、恢复控制器或归档器**。

为了限制内存峰值，byte[] 模式适用于有明确大小上限的分区（适配层最大 128 MiB）；超出限制的分区直接使用已有流式 Snapshot 接口。不要对撮合/报价热路径重复复制 byte[]。

### MD 具体业务边界

MD 的完整分区 Snapshot 必须包含恢复及对外行情所需的所有状态：盘口、最近成交、K 线和所需派生状态，而不是只含深度市场数据。业务 Diff 可采用完整事件字节模型，但必须经 Common 的提交/连续性校验后 Apply。MD 在恢复中不得对外发布，恢复完成还须经过市场覆盖、真实源端已提交 HEAD、旧发布者 fencing、Epoch 与 READY 门禁。

现有 MD 的 MdPartitionRuntime、DepthBookFacade、MDFacade、TradeFacade、OhlcRockDBStore 等仍是具体业务逻辑。新增公共接口尚未等于全分区状态机已经完成生产注入，也不能据此直接放开 MD 自动主切。

## 当前验收与后续

- Common 本地全量 262/262 测试 PASS；包含复用原恢复协调器的 Snapshot/Diff 验证、SHA 篡改拒绝、超大快照拒绝、恢复后保持 NOT_READY。
- 接口已提交到 Common saas-crypto，但尚未更换 Common Maven Central 发布版本或现网容器；运行中 Order/Trade/MD 仍保持原版本。
- 下一步只在 MD 的一个独立 Learner 分区实现并验证真正的业务完整状态 Snapshot/Diff，然后接入现有 Common 恢复门禁，以本地编译和 MD-C Learner 灰度验证。真实安全证明全部满足后才能执行 Primary 故障注入。
- Order/Trade 之后逐项收敛其重复的集群控制代码到 Common，避免全量重写和性能退化。

不得放宽现有五项主切安全阻断，或用此新增接口冒充已认证的 Order HEAD 与完整市场恢复证明。
