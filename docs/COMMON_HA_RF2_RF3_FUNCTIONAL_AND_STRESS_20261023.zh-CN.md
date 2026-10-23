# Common HA 按分区 RF=2/3：功能验收→压测实施记录（2026-10-23）

## 第三阶段：已 ACK 证书双节点保管 + A/B 故障验证（2026-10-23，新一轮）

- 此阶段建立**另一个完全隔离**实验 `compose.v19-rf2-custody-pilot.yaml`，新3个ZooKeeper容器、A/B两个独立数据JVM及各自独立WAL卷；只共享只读实验测试身份，不复用上一阶段WAL/证书，也不修改正式Trade/Order/MD或默认Docker。Common候选jar另外构建在`common-upstream-review-20261022/target-rebuilt-20261023/common-3.0.22-v19-custody-source-built.jar`（Java8 SHA256 `20878d2bd9031a4b923f2857edb80de0a2df27a29ee7dbaa98e7549736916bf9`）；旧试验Jar独立保留。
- **Common新增本地提交 `2dc42d3`**：`DurableWalCertificateCustodyControlHandler`为固定旧membership/Epoch发送经2/2或2/3 RSA验证的精确WAL提交证书；B校验本地WAL已fsync且同前缀Hash，将证书temp force→atomic rename→目录force，再以独立节点私钥签署**证书保管回执**。`DurableWalCertificateCustodyAckGate`校验旧Epoch主授权、源节点真实WAL刷盘、Primary自己的证书持久保管、足够不同物理Host的保管RSA回执后才能返回严格ACK。`DurableWalCommitIndex.verifiedHighestCertificate()`支持从完整磁盘链重启验证后恢复最高签名证书。对每份源WAL证书只做一次批级RSA验真以降低多签名的重复CPU。
- Demo试验开关`DEMO_V19_CUSTODY_ACK_PILOT=1`时，`DemoV19DurableRuntime`真实发送该Common TCP control帧，并在`certify/certifyBatch/certifyCovered`客户端严格成功前执行证书保管门禁；没开开关时RF3/旧实验保持原路径。本段仅实验固定A/B/Epoch1，不应把代码描述为已可跨Epoch自动提升。
- Common相关JUnit **34/34 PASS**，Demo完整Java8 JUnit **132/132 PASS**；新增网络保管协议+ACK门禁特定测试**13/13 PASS**（真实Netty TCP、身份验证、伪造签名、跨Epoch、WAL未追平、旧授权撤销、严格缺多数拒ACK、重启验签）。
- **首批8笔**双Docker成功，返回`QUORUM_DURABLE_SINGLE_HOST_TEST`，A/B各自`/srv/v19/wal/.cert-custody/head.bin`物理存在且SHA256完全一致，严格证书序号8。是真实独立JVM+磁盘卷，但它们在同一Mac主机上，`physicalHost`仅实验模拟身份，不具备两个硬件故障域。
- **SIGKILL B**（真实退出137）后，A独活8条新请求严格ACK被拒绝，不能伪造2/2签名，原已ACK证书只到seq8；B恢复后第1次同请求ID重试安全503，追平到seq16后**相同8个requestId**重试8/8成功且`appliedCount=1`，双方`head.bin`再次完全同SHA（seq16）。无数据清零、无人工复制证书。
- **SIGKILL Primary A** 后B的WAL和证书文件依然完整；B自行重启时证书文件被启动代码验证并加载，**但B尝试交易仍503，因为没有跨Epoch选主授权与候选权威CommitIndex**。这是预期的安全拒绝，**自动主切仍是NO-GO**。A原容器不清数据启动后新8条seq17..24成功，A/B证书SHA又一致。
- **双重证书保管短压测**：10模拟客户端/2并发组×8条=80/80成功，最高证书seq104、A/B文件SHA相同，真实吞吐**10.84条/s**，组P50 **280.28ms**、P99 **3566.95ms**。功能PASS，**性能FAIL**，相较上一阶段没有证书独立保管时更慢；原因待详细Profile（串行WAL签名→证书fsync→Netty证书install→B证书fsync与RSA回执→客户端ACK，还有热路径全历史Prefix SHA）。下一步必须设计累计水位的**异步流水线、批量合并fsync及重复PrefixHash增量索引**，不允许绕过已确认的物理证书保管条件。
- **距离结束Demo/开始Trade的准确门槛**：
  1. Common完成`RF2/3`动态PartitionAssignment/成员切换、Learner追平的实际Netty运行时接线（目前独立实验仍固定P000/A/B/Epoch1）。
  2. 完成已向客户端ACK水位的可信跨Epoch发现/证明、新Primary合法ZK租约和旧Primary强Fencing；真实SIGKILL A后**无需脚本**自动B升主READY、已ACK完全一致、旧A恢复降为Replica再追平，A/B互相交换主角色；无丢单/无重复应用/无双主。
  3. 优化到约定的性能目标（历史讨论P99<=30ms、10/50/200真实租户稳态5分钟和2–3倍Burst5–10分钟、故障期间正常业务或有界暂停、最终权威订单/成交/持仓/资金/Projection一致）。
  4. Common经此验收后固定版本/接口，开始Trade真实A/B HA部署；**Trade接口调查可以现在启动**，因为Trade既有`TradeClusterAdapter`、`TradeReplicationManager`、`TradeSnapshotManager`、`TradeRecoveryApplier`等适配组件；**Trade生产或Demo正式新镜像替换此刻仍不允许称GO**。具体完成日期依赖自动主切及性能验收，不能凭小范围单测指定。
- Mac宿主盘仍约**96%**、余**19GiB**；不得在继续长压时无界增长WAL；归档回收前先确认无Docker引用，不删除正在使用的CommitIndex/custody/WAL。

## 第二阶段补充：RF=2 真正双独立 Docker JVM 功能→故障→并发压测（2026-10-23）

**这是本报告第一阶段单JVM回环测试之后完成的新增验收；以下数据优先作为RF2真实Docker阶段依据。仍然只在同一Mac的一个Colima VM内，不具有两独立物理故障域。**

- 独立新项目 `compose.v19-rf2-shard-pilot.yaml`，仅启动A与B两个**独立JVM/独立Docker WAL卷**和**三个ZooKeeper控制投票容器**（没有第三个数据副本C，也未触碰旧RF3/asyncstream或正式服务）；隔离开关`DEMO_V19_RF2_SHARD_PILOT=1`、`DEMO_V19_THREE_DATA_NODES=0`、`DEMO_V19_COMMON_QUORUM_TEST=1`、`DEMO_V19_SINGLE_HOST_QUORUM_TEST=1`、`DEMO_V19_GROUP_FORCE_PILOT=1`、`DEMO_V19_SIGNED_BATCH_ACK_PILOT=1`。新启动的ZooKeeper首次Bootstrap写入的P000成员恰为A Primary/B Replica/Epoch1。
- Demo实验适配 `src/main/java/com/opentradingcore/demo/DemoV19DurableRuntime.java` 根据**隔离开关**只选择A+B真实数据身份并在签名/复制循环中只询问本分区指定的B。注意这**尚不是任意分区任意成员的正式动态运行时接线**，仍是实验P000固定Epoch1与A/B的最小双Docker验证。压力客户端名称已改为`isolated_v19_single_partition_multi_client_strict_quorum`并显式带`dataReplicaCount=2`，避免旧脚本错误显示“3JVM”。
- **正常真实功能**：A首组8条Netty TCP订单模拟请求，B真实WAL group fsync并返回独立RSA签名前缀证明，Common在A持久化严格2/2证书后，8条均`code=0/appliedCount=1`，证书seq8；没有C副本参与。
- **真实SIGKILL B**（exit137）后A单独尝试下一组8条严格ACK：收到`503 DEMO_GROUP_NOT_DURABLE`，本地WAL有待认证seq9–16，但磁盘严格证书**只到seq8**，没有错误地降低为本地异步成功。恢复B后其WAL**自动追平seq16且Sha与A相同**；第一时间重试时B的签名授权暂不可用，仍安全503，稍后**复用完全相同8个requestId**再次重试成功、全部`appliedCount=1`，A+B证书seq16落盘，零重复应用。该初次签名恢复延迟需继续优化，不能称故障瞬间无中断。
- **实际严格2/2并发（每Netty RPC预组装8条；与单笔API不同口径）**：

| 模拟客户端 | 同时进行的组 | 成功业务记录 | 实际记录TPS | 组P99 |
|---|---:|---:|---:|---:|
| 10 | 2 | 80/80 | 24.77 | 1554.72ms |
| 50 | 8 | 400/400 | 93.36 | 2249.28ms |
| 200 | 16 | 1600/1600 | 187.72 | 2044.00ms |
| 额外10人回归 | 2 | 80/80 | 27.36 | 1715.55ms |

三档总计**2080/2080成功**，额外回归80/80成功；最末A/B WAL均**231072 bytes**、SHA256=`ec1adebe4fa2dd090447e21eb84473d4b133bb1e2afb5bb4f3296234a3a4d621`，Common严格证书最高**seq2176**，证书文件共272份（每8条一份）。**真实性能P99仍1.5–2.25秒，远超30ms目标，不可称性能GO。**

- 本次功能与短压验收都在**单分区P000、同一Mac虚拟故障域、模拟客户端**完成。**没有**10/50/200个真实注册租户、多分区动态重新分配/自动Learner迁移、主A SIGKILL后B自动跨Epoch接管、双独立物理主机、正式Order/Trade/MD交易/持仓/余额/成交的权威对账。RF2的普通Backup故障会阻断严格2/2 ACK；如希望A独活仍可交易，必须明确切换`LOCAL_DURABLE_ASYNC`并承认未复制的ACK有丢失风险，不能自动降低持久化合同。
- 当前源码Common本地commit`b59ab1d`、文档历史提交`9d31c0b`；本段作为新追加进度。Common统一Jar仍SHA256 `57ff996c5ba0f6ed2509c27abab154d53f596ded80c2cbbe67dbed73df7eb546`，正式Maven/Common版本/OrderTradeMD容器未替换，GitHub Actions未启动。Mac磁盘约96%使用、余21GiB，长压前必须审计归档，不得误删在用WAL/证书及生产卷。
- **下一步顺序**：正式`PartitionAssignment`/ZooKeeper成员动态配置接线（替代实验ENV固定A/B与P000）→ RF2双JVM断线恢复与Learner新增节点的真实安装/授权功能验收 → RF3对照 → 10/50/200真实分区/租户稳定5分钟与突发 → 自动安全新Primary跨Epoch和全业务权威一致性。未通过的步骤不可声明完成。

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


## 2026-10-23 追加现场：RF2 实验重启、A/B 故障与严格证书性能定位

- 验收基线仍以 `docs/COMMON_CLUSTER_REQUIREMENTS.md` C01–C44 / T01–T15 为准。此轮仅实验 `compose.v19-rf2-custody-pilot.yaml`，独立三 ZK + A/B 两份 WAL，物理故障域都在同一 Mac，不属于物理多机证明。
- 清理确认零容器挂载/未发现打开文件的历史恢复备份 `~/.opentradingcore/order-clean-reset-20261019-1757`（约 13 GiB），Mac 可用空间由约 13 GiB 上升到 26 GiB；`docker image prune -a -f` 报告 Docker 回收约 3.458 GB，未删除容器数据卷或正式运行目录。Docker 镜像空间回收不等于 Mac 的 df 同步增加。
- 实验首次发起 8 条真实 TCP 批次，8/8 `code=0, appliedCount=1`，A/B WAL、状态摘要、已确认 SHA 一致。真实 SIGKILL B 时 A 新写请求得到 `503 DEMO_GROUP_NOT_DURABLE`，未把本地未认证尾部误报成功；恢复 B、复用原 8 个 requestId 后 8/8 成功且只应用一次，B 自动追平。最终 A/B 各 seq=16、`clean=true`、同一 SHA。
- 真实 SIGKILL A 后 B 的写请求返回 `503 DEMO_UNCERTIFIED_BACKLOG: missing trusted Common CommitIndex`；恢复 A 后双方 seq=16，SHA 一致，`epoch=1`。**安全拒绝 PASS，自动跨 Epoch 主切 FAIL**。当前固定 `P000/A/B/Epoch1` 的实验运行时不能声称实现合法自动提升。
- 严格证书托管 10 个模拟客户端 ×1 组 ×8 条，2 组并发：80/80 成功、11.07 ACK records/s、组 P99 3970.99 ms（FAIL）。这是单分区 P000 的模拟客户端，并非十个真实注册租户。
- 本地独立 Demo 增加*只观测、不参与 ACK/选主*的 `custodyLocalFsyncAndSign` 与 `custodyRemoteReceipt` 指标后，Maven 编译及 `DemoV19SignedBatchAckTcpTest` 返回 PASS，实验 A/B 保留 WAL 重启，再测 80/80 成功、11.60 records/s、组 P99 3629.28 ms（FAIL）；结果是新采样，不能视为性能优化成功。
- 第二次样本：主节点 local custody install/fsync/sign 平均约 32.9ms（10 次）；远端证书托管回执平均约 46.1ms（10 次）；复制 batch RPC 平均约 61.1ms（10 次）；status RPC 平均约 505ms（仅 3 次）。客户端组 P99 同时包含前置排队等待，和单次 Netty handler 局部耗时不能混用。
- **后续硬关口**：Common 实现旧 Epoch 已 ACK 证书可信水位发现及多数保管证明、新 Epoch ZK 授权与旧主 fencing、独立 Demo 无脚本自动 A→B/B→A 接管，并在安全约束不降低的前提下消除高延迟队列/状态 RPC 等待；最后完成 10/50/200 各 >=5 分钟、2–3x Burst 5–10 分钟和故障中压力验收。此刻仍 NO-GO for Trade/Order/MD。
