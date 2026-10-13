# MD 自动主切：Order 权威恢复源阶段验收（2026-10-14）

## 已完成

- 公共包 com.app.common 3.0.19 提供内部 HEAD、DATA、Manifest、挑战签名和 HMAC 协议。不修改 Gateway。
- Order 97a0627：私有复制控制端口兼容分发三种恢复协议，默认关闭；保留旧 FAILOVER_PROOF 与 LEARNER_PROOF。Snapshot 分块绑定原始持久化字节的 SHA-256。
- Order 8f5e363：按认证 HEAD 的提交区间 (snapshotSeq, committedHeadSeq] 提供最多 8 条的连续 Chronicle WAL Batch，一次有界读取，严格校验分区/序号/Epoch/字节上限/Primary 身份。缺口、倒退、越界均拒绝。
- Order f434e35：本地 HEAD 审计在读取前后通过 ZooKeeper 直接读取 Primary 与 Stat.version，检查同一 Epoch 下的 CAS 变化、原主退位和 assignmentVersion 等业务字段。禁止以 PartitionRegistry 缓存视图代替真实 ZooKeeper Stat.version。
- 本地 Order 364 项全量测试通过，0 失败、0 错误、3 跳过；真实 Chronicle 追加和批量读取测试通过。
- 当前运行中的 Order A/B/C 依然是旧镜像，MD-C 使用 GHCR sha-026306b 作为 Learner；无主节点故障注入，无数据清理。

## 尚未闭环的安全证明

重要：新 HEAD/Data/Manifest 操作尚无完整的生产授权组件实例，因此默认拒绝。Order 本地 HEAD + ZK 版本检查不能自动证明跨节点持久提交，更不能授权 MD 晋升。

1. 源端 DurablePrimaryAuthority 必须独立验证同步 Replica 的持久 ACK、Order Commit Marker、最新 Snapshot 与 ZooKeeper Owner/Stat.version，不把异步未提交 WAL 纳入 HEAD。
2. 每物理 Order 节点配置仅用于内部恢复的 256 bit+ 密钥，HEAD 只能由被验证的物理 Primary 签名，禁止由客户端传入任意 HEAD 代签。
3. 同一私有复制控制端口提供签名 HEAD、完整市场 Manifest、Snapshot Chunk、连续 Delta WAL，MD 逐项验证来源、哈希、分区市场覆盖和 WAL 连续性。
4. MD 新 Primary 发布前必须独立通过旧主 fencing、ZooKeeper CAS 和 RECOVERING 到 READY Epoch 隔离。
5. 经 256 分区预检、宿主机磁盘余量、MD-C Learner 灰度后，才允许独立 QA 租户执行 MD Primary SIGKILL 与行情连续性、无双主、角色反转验收。

现有自动晋升预检仍必须维持 BLOCKED；不得把源码测试、Colima 恢复或镜像准备解释为自动故障切换通过。

## 性能原则

新的 Order 读取仅发生在显式、限流的恢复控制请求，不对撮合/下单热路径增加全量 Snapshot/WAL 扫描。Common 负责复制状态机协议、认证与传输；业务服务仍负责自己的 byte[] Snapshot/WAL 恢复。暂不执行 200 租户压测或重建 Gateway。
