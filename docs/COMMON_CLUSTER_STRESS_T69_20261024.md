# T69｜Common RF2 8核本地异步 ACK 压测与16核可行性（2026-10-24）

## 范围与硬件
Mac 主机为 Apple M4，sysctl hw.physicalcpu=10、hw.logicalcpu=10；Docker Desktop Linux VM 为8 vCPU、约15.58 GiB。隔离3 ZooKeeper+2 Common JVM/A/B WAL，同机独立容器，单分区 P000，真实 Netty。另有24个 dc-saas-* 容器运行；Docker cpus 限制非独占预留。
**16核无法在该宿主机真实压测。** 给容器设置16核 quota也不会变成16个真实处理器；需要另外的真实16vCPU机器，不得推算成实测。

## 模式与开关
- **QUORUM_DURABLE 严格同步确认**：当前主备 WAL fsync、两个 RSA 签名、Common CommitIndex 与两个物理 Custody 均通过后才 ACK。T68 Epoch3 batch32 真实测试为50虚拟客户端3200/3200 ACK、86.94 WAL 条/秒、批次 P95 5.47秒；200虚拟客户端6400条仅5056及时ACK、62.67 条/秒、批次 P95 11.62秒。这是严格模式，不是异步直接确认。
- **LOCAL_DURABLE_ASYNC 本地持久确认**：主节点本地 WAL 强制落盘后直接 ACK，副本通过异步 WAL 追平。客户端字段 quorumDurable=false、possibleDataLossIfPrimaryPermanentlyLost=true、replicationPolicy=ONE_WAY_ASYNC_WAL_STREAM、unreplicatedRecordsAtAck；无法保证RPO=0。
- DEMO_ASYNC_REPLICATION=1 只控制后台复制方式，**不代表客户端ACK策略**。试点严格分支 DEMO_V19_RF2_DYNAMIC_STRICT_ACK=1；试点本地策略 DEMO_V19_LOCAL_ACK_STREAM_PILOT=1、DEMO_V19_SINGLE_FORCE_PILOT=1；只有合法 Epoch grant 才可 ACK。DEMO_V19_RF2_AUTO_DEGRADE=1 只允许已实现的特定 HA 授权降级路径，严格 READY 中直接杀掉备用尚不会安全自动降级。
- 本轮隔离本地实验显式覆盖 DEMO_V19_COMMON_QUORUM_TEST=0、DEMO_V19_RF2_DYNAMIC_STRICT_ACK=0、DEMO_V19_LOCAL_ACK_STREAM_PILOT=1、DEMO_V19_SINGLE_FORCE_PILOT=1。现有**不是生产级统一热切换选择器**，未来应通过 Common 审计的 STRICT_QUORUM / LOCAL_DURABLE_ASYNC ACK policy 与 ZK Epoch CAS 和旧主撤权转换，不能直接修改环境变量绕开证书。

## 真实本地ACK指标（单条 WAL 请求，非订单/租户TPS）
| CPU上限 | 请求量/成功 | 并发请求 | ACK TPS | 单条P50 | 单条P95 | 单条P99 |
|---|---:|---:|---:|---:|---:|---:|
| Docker8核首轮 | 100/100 | 4 | 98.925 | 37.243ms | 66.103ms | 77.232ms |
| Docker8核第一大轮 | 800/800 | 16 | 158.395 | 95.516ms | 158.347ms | 181.160ms |
| 仅隔离A/B限为4核 | 800/800 | 16 | 189.380 | 75.950ms | 140.182ms | 178.808ms |
| 隔离A/B恢复8核复测 | 800/800 | 16 | 227.452 | 67.018ms | 108.265ms | 129.212ms |
| 8核：SIGKILL备用B后主A继续 | 100/100 | 4 | 151.733 | 23.698ms | 41.845ms | 49.026ms |
| 16核 | 未测试 | — | 无实测数据 | — | — | — |

四核某轮比八核首轮快，八核预热后更快，因此结果受fsync、JIT、OS调度与共享负载影响，不能把单轮观测解读为 CPU 可线性扩展，更不能预测16核数字。

## 故障与数据一致性
- 异步 ACK 第一笔直接返回 unreplicatedRecordsAtAck=1，并标记 possibleDataLossIfPrimaryPermanentlyLost=true。
- 前三组压测后A/B均到epoch1 seq2501且 WAL 与 state SHA256 一致。
- SIGKILL 备用B，Primary A在B确实已停止时100/100继续收到 LOCAL_DURABLE_ASYNC ACK；启动B后自动追平，两边epoch1 seq2601、distinctRequests=2601。
- 最终双方WAL SHA256: 05861cd6ce98c87fd57f6284dde79c4071acd811334abc85f2babe9d41af2a5b；State SHA256: 39649c423c7c11ec6441c79e9018d59f04176a16941c5dcda2b623465b3c4e57。
- 这些恢复后的一致性不证明异步 ACK 没有RPO，尤其不证明两节点同时/连续永久损坏时零丢失。T69未进行 Order/Trade 真业务集成。

## 下一步
严格模式下备份故障的安全降级（ZK 新 Epoch授权、证明源端持久水位、旧主隔离）和自动返严格2/2仍待实现；200高并发严格ACK的P95约11.62s、并发超时仍NO-GO。待独立16vCPU主机可用，重新用统一软件、磁盘、单条与32条批次负载测试8/16并分别量化 CPU vs fsync。
