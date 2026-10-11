# OpenTradingCore：Raft 风格的公共状态机契约（2026-10-11）

## 架构决策

采用“**Common 管 HA 机制，业务层通过状态机接口注入**”的架构。借鉴 Raft 中 committed log 和 snapshot state machine 的分层思想，但**不新增一套 Raft 选举协议**；继续使用现有 ZooKeeper 分区 assignment、epoch、fencing 和 DirectNetty 复制链路。

Common 中已经增加以下独立于业务的 Java 类型：

- ReplicatedStateMachine：apply(byte[] command)、snapshot(ChunkSink sink)、restore(ChunkSource source)。
- ReplicatedStateMachineFactory：为指定 partitionId 构造业务实例。
- PartitionStateMachineRegistry：显式注册/移除分区实例；没有注册的分区禁止被默认创建并拒绝读写。
- StateMachineSnapshotStreams：按字节块做快照写入、SHA-256 验证、大小限制与已暂存的整份文件校验后恢复。验签通过前不能调用业务 restore。
- 原有 SnapshotRecoveryBoundary、SnapshotTransferIntegrity、SnapshotRetentionFence 继续负责 epoch/sequence/完整性/删除资格的公共规则。

业务各自实现状态机：
- OrderSvr：提交命令解码和订单簿、委托、撤单、执行等业务镜像。
- TradeSvr：余额、持仓、风控、挂单、执行去重等完整业务镜像。
- MDSvr：派生行情仍从 Order 权威全市场镜像+连续变化恢复，无需增加 MD 对 MD 复制日志。

**注意：接口已写好，但目前尚未让运行中的 Order/Trade 的所有业务恢复路径接入新接口，不能把接口测试说成生产 HA 已验收。**

## 通用恢复顺序（待完成运行时接线）

1. Common 证明快照来自当前合法 Primary，验证 epoch、已提交 HEAD、旧主失权、分区 assignment。封闭目标分区 READY 和业务写入。
2. Common 调用业务 snapshot，通过 ChunkSink 生成一致的二进制全镜像；快照不会强制构造一整块内存数组。
3. 接收节点分块下载到临时文件，校验完整 SHA-256、大小、分区和 committedSeq；没有权威来源及校验凭证一律不得恢复。
4. Common 获取分区独占恢复屏障，再用二进制 ChunkSource 调用业务 restore。业务必须保证所有状态原子恢复，失败则保持 NOT_READY。
5. Common rebase 持久化合法 checkpoint，从 snapshotSeq+1 严格连续重放已提交增量；验证业务对账，通过后才能 READY。
6. Common 的 SnapshotRetentionFence 判定日志归档：同时满足超过 2 天、快照覆盖、复制副本可恢复、Projection/消费者 durable watermark、回滚历史与文件句柄已释放，才允许删。仅按天数不能授权业务 WAL 删除。

## 性能边界

- apply(byte[]) 在热路径：Common 只做必要的已提交序号/epoch 约束；业务决定二进制命令含义，不额外增加同步 ZK 请求、全局锁或热路径文件扫描。
- snapshot/restore 属于受控维护路径；采用分块字节接口和常量大小约 64KiB 验证缓冲，避免 Trade 执行去重快照大于 50MB 时造成内存峰值。
- verify+restore 要求调用者保证暂存文件在整个操作中不可变，并保持分区处于专属恢复屏障下；SHA-256 不能代替 Primary 的身份认证或服务级恢复事务。
- 每分区一状态机实例；不能把所有租户数据用同一个 Java 全局锁保护。

## 发布路径

开发期采用 Mac mini 本地 Common -dev-SNAPSHOT -> com.app.dc -> Order/Trade/MD 构建和隔离测试，稳定后再统一发中央仓库与 GHCR。新 Common 接口不会自动打开业务 WAL 两日清理或 MD 主备自动切换。
