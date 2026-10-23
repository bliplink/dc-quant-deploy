# OpenTradingCore Common HA：按分区一主一备、可扩容的数据复制与选主方案（设计评审，2026-10-23）

> **实施决定更新（2026-10-23）：** 已选择“统一多节点 Common 轻量选主 + RF2 双节点成对互备默认放置”，256 分区在 2 节点各 128 主 / 128 备；4 节点各 64 主 / 64 备。此文件下方保留历史设计评审和旧实验状态，当前实施准则、迁移安全条件及阶段验收以 [COMMON_HA_LIGHTWEIGHT_BUDDY_STRATEGY_20261023.zh-CN.md](COMMON_HA_LIGHTWEIGHT_BUDDY_STRATEGY_20261023.zh-CN.md) 为准。静态规划不授权 READY，也不能直接重分配旧分区。


> 设计评审稿，不是已上线机制；本轮不修改 Common/Order/Trade/MD 代码或正式容器。结论：不允许所有节点相互复制全部 WAL。节点规模 N 与**单个分区**的复制成员数 RF 分开，分区按放置策略在 N 个节点中选择 RF=2 或 RF=3 个成员，只有该分区 Primary 主动推送 WAL 给其指定 Follower。ZooKeeper 的 2/3 **控制授权**不是写入数据的 2/3 **持久化副本证明**。

## 2026-10-23 实施与验收状态（持续维护）

Common 实验分支已通过分区RF=2/3数据成员边界和定向放置的11项新增功能测试、Common兼容组合37项与Demo全量132项回归；RF=2已完成真Netty回环+两份物理WAL文件的2/2 RSA认证及重启验证，小规模测试100批×8条、全部成功、约98.58条/s、批次P99=58.62ms。节点4/5/20的分区规划每轮1,000分区均通过、Primary分布均衡且每分区仅向1或2个指定备复制。代码在Common本地实验分支提交`b59ab1d`，**尚未接入实际双Docker JVM动态成员/迁移和自动跨Epoch主切**。详见`docs/COMMON_HA_RF2_RF3_FUNCTIONAL_AND_STRESS_20261023.zh-CN.md`。此处性能属于规划CPU和单JVM Netty TCP回环，不是完整Order/Trade真实压力验收。

**最新现场补充**：RF=2已经在**隔离的双Docker数据JVM（A+B）加三ZooKeeper节点**实现一次真实严格2/2 Netty/WAL签名提交，并在B SIGKILL后正确拒绝只有A的严格ACK。B恢复后重发同requestId成功且不重复应用；并发10/50/200模拟客户端分别80/400/1600条全部成功，最高认证seq2176，A/B物理WAL SHA一致。但这里的RF2数据成员仍由隔离实验开关选择，只演示单分区P000，**并非正式动态成员、多分区扩容或跨Epoch自动主切完成**。性能批次P99仍1.55–2.25秒。完整记录参见本目录RF2/RF3验收文档的第二阶段补充。

## 1. 节点扩容≠每个节点全网复制

- 复制单元是业务隔离的分区 `service + partitionId`；业务可以据`location + security_id`路由到分区，Common只处理`byte[]`状态机命令、WAL、snapshot/diff、durable cursor、fencing，不解释证券产品。
- 比如4个数据节点A/B/C/D：`P1: A主→B备`，`P2: B主→C备`，`P3: C主→D备`，`P4: D主→A备`。每个物理节点可同时承载某些分区的主和另一些分区的备；添加E时分配新的主分区给E，也可通过`learner→追平→切角色`分摊已有热分区，避免全局搬迁。
- RF=2只写1份远端日志、RF=3只写2份远端日志，网络量按总业务WAL字节×(RF−1)估算，**与全集群节点数N的平方无关**；空闲/不相关分区不会主动订阅它们不持有的业务WAL。
- 多路复用节点对间少量常驻Netty连接，不按业务请求/分区建立连接；每分区保持顺序`epoch + seq + prevHash`、并发分区共享连接但保序处理；异步后台累计水位/背压/断线退避；失败后Snapshot+WAL续传。
- 放置策略考虑不同物理主机/故障域、节点CPU/内存/磁盘/网卡、存储IO、承诺故障后一台机器可承接主负载的容量保留，不把同一分区的主备放在一个宿主Docker VM。

## 2. 三个证明/水位不能混淆

- **Control quorum**（通常独立3或5个ZooKeeper投票成员）：以多数租约/CAS授权`epoch,owner,configVersion`，确保同一个分区在任何时刻至多1个被授权可写Primary；可用的选主服务不能自动证明新Primary已包含所有旧主已ACK业务记录。ZooKeeper ensemble **按整个集群共享**，不需要每分区增加1台ZK。
- **Data durability**：严格ACK前必须至少`dataAckCount`个**真实持久化WAL副本**已写到指定前缀；RF=2需A+B（2/2）；RF=3需含Primary的任意2个数据成员（2/3）。轻量见证W仅保存epoch/元数据且不保存WAL时，A+W**不满足**数据2/3。对于RF=2，B故障后A不能以`QUORUM_DURABLE`对新交易继续返回成功；只能停严格ACK、等待其他副本追平，或显式使用`LOCAL_DURABLE_ASYNC`承担潜在RPO>0。
- **Committed/ACKed authoritative boundary**：不能把B/C仅具有相同物理WAL理解为旧Primary已对客户端确认的最高记录。目前v19 A独占`DurableWalCommitIndex`；B/C无权威证书，所以`SIGKILL A`后正确503，尚未自动升主。必须选定一种**一致机制**，不能同时堆叠互相冲突的半套日志多数证明和半套外部选主：(a)成熟Raft式每分区持久日志/任期/多数附加确认与“日志最新”选举规则，在多数交集下确定safe committed prefix；或(b)保留ZK独立租约选主，但实现旧epoch已ACK水位跨数据节点持久化、签名保管与新epoch上岗前覆盖证明。无完整证明绝不能自动提升。

## 3. 推荐面向实际用户的两种持久化档位

| 模式 | 数据成员 | 客户端成功边界 | B故障、A独活 | Primary永久损毁 |
| --- | --- | --- | --- | --- |
| `LOCAL_DURABLE_ASYNC` | 1主+1备（也可2备） | 当前Primary本地fsync+仍有合法Epoch授权 | A继续交易，B恢复按seq续传 | 有未复制记录损失风险，**RPO可能>0** |
| `QUORUM_DURABLE` RF=2 | 1主+1同步备 | 本地+指定备都fsync，证实提交边界 | 严格ACK中止/等待补新备 | B完整保存所有已ACK记录时可以安全恢复；新Primary仍需合法Epoch/fence |
| `QUORUM_DURABLE` RF=3 | 1主+2指定数据备 | 包含Primary的2/3物理数据副本fsync，安全提交边界被足够持久保存 | A+C仍可继续严格交易 | 可容忍指定的单数据节点故障，但仍需可信选主、覆盖校验和反双主 |

建议Demo开放自定义产品/一般流量先以RF=2的轻量配置验证性能，异步模式为明确可选策略；对于**不能承受已确认订单或资金记录损失**的生产Order/Trade严格分区，优先RF=3，让一台数据副本掉线仍能继续严格2/3提交。RF=3也只是每分区主→2个备，不是全部节点互相复制。RF=2加控制见证可实现**控制多数**和一个备机，但不能让单数据节点同时满足零丢失的严格提交。

## 4. 一条热路径应该如何运转

1. 客户端下单只找对应分区Primary；状态机排队，WAL append/group fsync、单分区递增`seq`、本地不重复requestId。`LOCAL_DURABLE_ASYNC`本地刷盘且授权有效后立刻ACK，不因副本故障停业。
2. Primary以**持续TCP push**方式发送`{partition,epoch,seqRange,prevHash,entries[]}`批量WAL给该分区的1或2个指定Follower；Replica做本地group fsync后按批/累积`durableSeq,prefixHash,epoch`回报。**数据单向、控制累计ACK回传**不是每个业务请求都额外发STATUS/HASH/RECEIPT来回RPC。
3. `QUORUM_DURABLE`只在有足够数据副本持久化后使`committedSeq`前进，并确保**选主需要的安全提交边界也获得可靠持久化/多数交集证明**；采用成熟Raft式持久日志与日志新旧选举规则可避免当前“每条一套独立证书+无确认跨epoch恢复”叠加设计的复杂性。若保留ZK独立选主则必须接上Common最新`DurableWalCertificateCustody + DurableWalCustodyQuorum`：副本存证书并force磁盘→返回RSA custody receipt→Primary证明多数custody后才承诺对应strict ACK。每批/累计水位共享一份证书；**单条业务不应重复全前缀SHA256读取**。
4. 异步水位间隔回复、窗口背压、指数退避、复机按seq拉取缺口、超出WAL保留则snapshot+WAL。副本重连不触发所有节点同步其他分区。
5. `Learner`在新节点先落盘/应用到可信水位，`configurationVersion`通过安全配置变更（如Raft joint consensus或ZK受控fencing迁移）切换正式数据成员，确认配置和epoch后才给新成员投票资格，旧成员安全退出/可回收旧WAL。任何阶段故障均可恢复且不双主。

## 5. 从现有源码看，哪些已经可用，哪些必须改

已存在可复用API：
- Common`PartitionAssignment`已包含`primary, replica, replicas[], learners[], epoch, assignmentVersion`，可支撑分区定向复制、负载平衡与Learner。
- `DemoAsyncReplicator.replicate`已`for(String replica: assignment.replicaNodes())`复制，**并非全节点两两复制**。
- Common`ZkPartitionFailoverRuntime/Controller`已有成员监测、Epoch/CAS选主壳，不能直接等同于足够的数据持久化证明。
- 目前严格实验`DemoV19DurableRuntime`强制旧Membership固定A/B/C、`P000`、`epoch=1`并为每次可认证提交轮询B、C签名；只在A卷创建`DurableWalCommitIndex`，B/C没有实际Netty证书custody。新`DurableWalCertificateCustody`虽已做本地文件/fsync/RSA单测，尚未接入真实副本TCP和客户端提交门禁。
- Common`PartitionFailoverController`目前要求最少2个活着且同步的Replica，构造新assignment还要求新Primary之外至少保留一个活着Replica；**RF=2下A死仅B活的提升逻辑未覆盖**。需要根据安全策略显式定义`degraded`/允许重构第三成员，而非假装已有RF=3选主过程通用。
- Demo`DemoDurableJournal.committedPrefixSha256Through(seq)`用`sha256(0,end)`重新扫描历史WAL前缀；长期高TPS不应该每次验证全量WAL。应替换成按WAL帧增量hash链/有界hash checkpoint，跨恢复时验完整链并用已持久`seq→rollingHash`索引。
- 暂时不动正式Order/Trade/MD、网关透传层、原测试数据/容器；优先在Common做 per-shard flexible RF=2/3和签名合批/安全变更，并在新隔离ABC/ABCDE试验环境验证。

## 6. 目标与验收

A/B互备和新节点扩容验收应覆盖：A主B备时B宕机、A继续`LOCAL_DURABLE_ASYNC`；B恢复断点续传；A主故障B可以经**可信安全新epoch授权、已ACK提交边界证明**自动接管；旧A回归成为Learner并追平。RF=3时A宕机B+C继续严格提交；B宕机A+C继续严格提交；大集群A/B/C/D/E节点加入，只迁移指定分区，不诱发所有分区全量复制。记录每分区有效角色、Data RF、WAL Byte/s、CPU、fsync/group大小、Netty RTT、P50/P95/P99、lag、maxAckedSeq与commit watermark。至少跨物理主机验证，200真实租户及真实订单/成交/资金持仓对账。**任何不具备严格多数持久化条件的情况，不准自动将严格ACK降成异步ACK或自称零丢单。**

推荐结论：**“按分区选择数据副本成员 + 共享ZooKeeper控制 + WAL流式定向复制 + 本地异步/严格多数两种明示Durability Policy”，扩容靠新增Primary分区负载，不靠复制所有数据到所有节点。** 关键交易严格零丢单并允许任一数据节点故障后继续写入，应选择每分区RF=3；追求低复制开销的一主一备则选择RF=2并承认严格模式故障时降级为不可确认或明确改成本地RPO>0。
