# Common HA 按分区 RF=2/3：功能验收→压测实施记录（2026-10-23）

## 一、固定目标及本轮边界

正式规划文档：`docs/COMMON_HA_SHARD_PLACEMENT_REPLICATION_DESIGN_20261023.zh-CN.md`。按每个业务分区只向指定的 RF-1 个数据副本复制 WAL；4、5、20 个集群节点只是分担不同 Partition Primary，不参与其他分区的复制。Common 不识别证券、交易资金的业务结构，业务层实现 byte[] 状态机、Snapshot/Diff、恢复接口。ZooKeeper 2/3 控制投票与真正 WAL 数据的 2/2、2/3 持久化投票不能混淆。

本轮只实施 Common 实验分支、独立的 JVM/真实 Netty 测试与静态分区规划。**不修改正式 Order/Trade/MD、原有测试 Docker 容器或 ZooKeeper 分区角色，不启动 GitHub Actions；不宣称正式上线。** Mac 宿主磁盘仍约95%使用，仅剩22GiB，暂不执行会持续扩张 WAL 的长时间实租户压测。

## 二、已经交付的 Common 源码

Common `common-upstream-review-20261022` 本地实验分支 `feat/common-durable-wal-quorum-20261022` 新提交：

`b59ab1d feat(common): scope RF2/RF3 WAL voters and shard placement to partition`

涉及：
1. `com.app.common.partition.PartitionReplicaGroup`：要求原 `PartitionAssignment` 已经完成可信初始化并可路由；严格限定每分区数据成员 RF=2/3，列出唯一 Primary 与1或2个被授权的远端复制对象；验证不同物理宿主，不把Learner或非成员当数据票；明确`LOCAL_DURABLE_ASYNC`需要本地1份、`QUORUM_DURABLE` RF2需要两份、RF3需要两份**实际持久化**数据。此处只描述人数，不自行签发客户端ACK。
2. `PartitionReplicaPlacementPlanner`：**只建议全新Partition的放置**，按既有Primary负载与Replica负载优先选择Primary/备用，验证物理Host不重复。新分区必须是`PREPARING`，绝不由规划器直接标为`READY`；必须在另一个受ZooKeeper授权的初始化事务中完成可信WAL Genesis、成员版本/旧主隔离与CAS后才能交易。新增节点E不会强迫所有老分区重新分配。已有热分区迁移需独立的Learner追平与受控成员变更，尚未实现。
3. `com.app.common.replication.DurableWalShardMembership`：从**具体PartitionReplicaGroup**和受信任节点PublicKey/PhysicalHost中生成固定RSA数据成员名单，其他集群节点及Learner不参与这一分区的真实数据投票。
4. `DurableWalCommitQuorum.Membership`：原代码强制至少3名数据成员；现在允许最少2个，**严格RF2必须A+B两个有签名且分别fsync的独立数据副本**，RF3仍须Primary+另一个独立物理Replica的2/3签名；绝不把ZooKeeper见证充作WAL副本。Existing Common签名、Epoch、Hash、证书fsync校验完全保留。

本地统一Java8候选Common Jar：
`common-upstream-review-20261022/target-rebuilt-20261022/common-3.0.22-v19-source-built.jar`
SHA256=`57ff996c5ba0f6ed2509c27abab154d53f596ded80c2cbbe67dbed73df7eb546`。未发布Maven仓库、未push/触发GitHub Actions。独立Demo测试代码`src/test/java/com/opentradingcore/demo/DemoV19SignedBatchAckTcpTest.java`新添RF2 Netty WAL用例及`DemoV19Rf2TcpBatchLoadProbe.java`显式基准入口（原Demo测试目录当前不是Common Git仓库）。

## 三、先功能后压力：已执行测试

### 功能 / 回归

- Common新增测试 `PartitionReplicaGroupTest`、`PartitionReplicaPlacementPlannerTest`、`DurableWalShardMembershipTest` **11/11 PASS**：RF2严格2/2、RF3严格2/3、RSA实际公钥验签/错误Epoch与配置版本拒绝、见证节点不计数据票、Learner与无关节点不复制、分区4→5节点新增工作落E但旧分区不搬、20节点依然只选1或2个Backup、同一物理Host重复拒绝、PREPARING不路由。
- 加上旧`DurableWalCommitQuorumTest`、`DurableWalCertificateCustodyTest`、`PartitionFailoverControllerTest`及旧分区配置单测，**Common组合37/37 PASS**，Java8全Common源码重新编译PASS。
- 完整Demo单元/回环回归：**132/132 PASS**，包括新RF2真实Netty TCP B端刷盘后携RSA已持久WAL签名ACK，Primary A本地刷盘+ B签名2/2后Common创建累计不可变磁盘证书，8条命令逐条可靠验签，A/B WAL与证书重启后仍能验证。只有A签名则严格拒绝。注意该Netty连接是**一个JVM内的真实TCP回环**，不是A/B不同Docker进程，更不是不同物理服务器。

### 压测（必须分两种口径）

**A. Common纯分区规划CPU负载：1,000个模拟分区、不同全局节点总数**

| 数据节点总数 | 每分区RF | 每节点Primary数 | 每分区远程WAL目标数 | 规划吞吐（分区/秒） | 规划P99 |
|---|---:|---:|---:|---:|---:|
| 4 | 2 | 250 | 1 | 2730.6 | 1.443ms |
| 5 | 2 | 200 | 1 | 1965.1 | 1.281ms |
| 5 | 3 | 200 | 2 | 1763.5 | 1.705ms |
| 20 | 2 | 50 | 1 | 2244.5 | 2.033ms |
| 20 | 3 | 50 | 2 | 2324.5 | 1.339ms |

程序`PartitionReplicaPlacementLoadProbe`。以上是**CPU规划吞吐，不是交易WAL TPS、网络带宽、200个真实租户、HA数据验证**。从目标数计算的“远端逻辑字节”只是上界模型，没有实际网络数据。新增第五节点会承接新主分区，不会令所有分区互相复制。

**B. 真 Netty TCP/文件WAL 的 RF2严格2/2批量压力（单个JVM TCP回环，A/B两个独立磁盘文件）**

| 批次数（8条/批） | 已确认WAL记录 | 实际记录/秒 | 批次P50 | P95 | P99 |
|---|---:|---:|---:|---:|---:|
| 20 | 160 | 22.93 | 11.01ms | 29.99ms | 125.35ms |
| 100 | 800 | 98.58 | 13.42ms | 26.33ms | 58.62ms |

程序`DemoV19Rf2TcpBatchLoadProbe`，每批A/B实际Group fsync、B独立RSA已刷盘ACK、A+B确切hash验证、证书落盘；每组只发送一份远端WAL，不向非成员节点广播。全部成功，关闭重开A/B WAL及CommitIndex后最终提交水位一致。**不能作为两物理节点生产性能**，P99仍未稳定<30ms。这里的吞吐受证书写盘、热路径全历史SHA及同JVM Netty测试影响。

## 四、明确尚未完成（先完成这些功能，才能做真正分区集群压力）

1. **真实分区运行时接线**：现有严格v19 `DemoV19DurableRuntime`仍把`P000/Primary A/成员ABC/Epoch1`硬编码；`DemoAsyncReplicator`虽只读`PartitionAssignment.replicaNodes()`，但新Common规划和成员版本尚未注入ZooKeeper授权的实际A/B/Docker双JVM运行链路。下阶段需要新的RF2独立Compose三ZK+A+B数据节点，实际2/2刷盘签名、B重启后WAL追平、B故障时严格模式拒ACK而localASYNC继续（若明确配置）、A故障时可信安全升主验收。
2. **成员变更/扩容**：添加E先成为新分区指定成员；已有热P分区若要从A/B迁往E，需`learner→snapshot+WAL追平→新配置CAS/epoch fencing→受证书保护READY→旧节点退出`。目前只是PREPARING放置建议，绝不由规划器自行修改现网分区角色或拷贝业务状态。
3. **真正主切无损证明**：RF2单备用B持有完整已确认水位后才能在A被fenced且ZooKeeper新epoch合法的前提下升主。既有`PartitionFailoverController`强制至少2名活着且同步的Replica，不能支持“只有B在线”的降级接管；需要显式新策略和可信旧ACK证书多数保管，不能把无副本新主立即标记严格可交易。RF3旧Primary失败后2/3生存时也需跨Epoch签名证书保管+发布隔离。
4. **真实多租户和长期吞吐**：4/5/20节点分区规划功能通过，不等于真实200租户/Robot Order/Trade/MD、多节点独立WAL吞吐、网络/CPU P99通过。真实10→50→200租户，持续>=300秒、2–3倍5–10分钟burst、SIGKILL/恢复及资金/持仓/成交/委托/Projection水位权威对账仍是上线必要条件。
5. **资源**：Mac宿主盘约95%使用、余22GiB。不要触碰正式Demo卷/正在运行的实验WAL/证书；下一次长压前先核对旧无引用工件并做安全回收。

**本轮判定：Common RF2/3分区规划、实际签名证据和单JVM双WAL回环功能PASS；规划层压力和小规模RF2 TCP/WAL基准PASS；真实多JVM动态成员配置、自动故障主切、正式性能及业务一致性总体验收仍NO-GO。**
