# 2026-10-16 Mac Demo 集群真实角色切换验收证据

> 本文遵循 [集群最终统一验收任务书](CLUSTER_HA_FINAL_ACCEPTANCE_MISSION_20261015.zh-CN.md)；只记录真实已执行的操作。日期采用 Mac 所在时区 Asia/Shanghai。全程未新增产品功能，也未依赖 GitHub Actions。

## 2026-10-16 08:31–09:05 Order 真实持久化签名源端与公共版本依赖（最新进展）

**直接核查最新 GitHub `saas-crypto`，避免误将较早 Mac 浅工作树中的缺陷重新提交。** 本轮**没有**更换运行中的 Order/Trade/MD 容器、没有清数据或故障 SIGKILL；GitHub Actions 账单额度已尽，全部验证均使用 Mac 本地 Java 8/Maven。

### 1. Order 实时 ZK ACK 校验与完整空市场 Inventory 边界已合并

- 并行开发已经将 `DurableReplicaAckGuard` 及 Chronicle `syncJournalThrough` 加入远程 Order `saas-crypto`，因此**没有再次提交旧工作树的重复实现**。
- 真正新增的缺口是 Order 现有生产 `OrderReplicationManager` 的副本 ACK 再确认只检查缓存角色/Epoch，却可能在 ZK 会话已断开后仍返回 OK/DUPLICATE。添加 `OrderPartitionRuntime.requireControlPlaneConnected()`，使生产 `OrderReplicaReplicationHandler` 的 `assignmentLookup` 在 Common durable ACK 守卫 msync **前后**两次检查 ZK 会话在线，不增加每条订单的 ZK 网络读取。模拟 WAL 已追加、会话断线和重投也不能成功 ACK。
- 全量最新源码回归首次 382 项有 1 项失败：`OrderMdCommittedPrefixBoundaryTest` 仍要求空 `books=[]` 拒绝。进一步核查发现真正漏洞：Fastjson 反序列化省略 `books` 的旧 Snapshot 时，会自动初始化为 `[]`，错误地混淆**缺少来源库存**与**完整签名空市场清单**。源端已增加原始 JSON `books` 必须显式存在且为数组的 fail-closed 检验：合法 `books=[]` 通过、完全缺失/null 必须拒绝。
- 通过上述修复，实际 Mac 最新 `saas-crypto` 完整 Java 8 回归 **85 suites / 383 tests / 0 failures / 0 errors / 3 skipped**。代码已合并 [Order PR #18](https://github.com/bliplink/com.app.dc.ordersvr/pull/18)，merge SHA `4f4efdc78628a315088d8ee507af7fa3a51dda7c`。
- 注意：两项是必要安全边界，但**不能**代替真实 ZK 投票 Quorum 签名、旧主发布隔离与 Receiver Ledger。仅 GitHub 源码已更新，运行中的旧 Order 镜像**未替换**。

### 2. Order 真实 WAL + SourceHead + Quorum 回执接线已开发并送审，尚未合并

- [Order PR #19（Draft）](https://github.com/bliplink/com.app.dc.ordersvr/pull/19)：新增 `OrderDurableCommitWitnessSource`，接入现有内部 Netty `OrderMdRecoveryControlRouter` 的 `DURABLE_COMMIT_WITNESS_V1`，**只收原始 challenge**；读取真正的 ZooKeeper 分区 znode + `Stat.version`（不依赖只读缓存）、必须当前同步 Replica、磁盘原始 Snapshot 字节及其 SHA-256、连续 Chronicle WAL 和实际解析的 `OrderCommitWatermark` 提交 Marker；签名前后再次读取并核对 HEAD/Epoch/版本、将 WAL 尾部 `msync` 后才能签名。默认 `order.cluster.quorumWitness.enabled=false`，每台物理节点必须单独提供 256-bit 本机 key；任一依赖不满足返回 UNSAFE。Gateway/下单撮合热路径不变。
- **非伪造 Commit Marker 的单测**：使用实际本地 Chronicle WAL 写入 `STATE_UPSERT` + 按 `OrderStateCommit.from` 序列化的有效 `STATE_COMMIT`，真实 `OrderCommitWatermark.scan` 从 WAL 推导水位（不预填测试假标记）；快照字节 SHA 与签名 HEAD 一致。模拟不同的 ZK Stat version 和第二物理节点 signer 验证拒绝改版；Snapshot 缺失 `books` 也拒绝。额外覆盖关闭开关/缺失密钥/错误节点/非 256-bit key。**模拟的第二物理节点仅限密码学单测，不是 Mac 上的真实第二台机器**；`Verification.isPromotionAuthorized()==false`。
- 本地仅安装 Common 开发版 `3.0.22-devphysical-20261016-SNAPSHOT` 和单独编辑的 Order Maven POM 依赖进行编译测试；这**不是正式 Maven Central 发布**。隔离源码最新 HEAD `4f4efdc`，完整 Order 回归 **87 suites / 387 tests / 0 failures / 0 errors / 3 skipped**。
- **为何保留 Draft：** 现在正式 Common 新 Quorum classes 尚未作为消费者可获取的 Maven GAV 发布；`com.app.dc` 尚未指向正式新版本。如果直接合并 Order PR19，会造成中央仓库尚无依赖的默认构建失败。先完成 Common 正式发布及 `com.app.dc` 统一依赖，再合并/统一镜像。这并不表示生产 Order 已开始响应 Quorum 控制操作。

### 3. Common 新版本准备与 JDBC 8 回退问题

- 已合并 [Common PR #29](https://github.com/bliplink/com.app.common/pull/29)，merge SHA `e6f088034a8fe137bae9ae199eba276d331a5e90`，`pom.xml` 准备将版本升级为 `3.0.22-SNAPSHOT`，移除旧 `mysql:mysql-connector-java:5.1.24`，改为 `com.mysql:mysql-connector-j:8.0.33`，明确针对用户发现的 JDBC 8 依赖回退。
- 按**实际 JDBC8 Maven POM**本地离线 Common 全量回归：**66 suites / 286 tests / 0 failures / 0 errors**。当前 Mac 无可用的 Maven Central `~/.m2/settings.xml` 发布设置（已检查，未输出密钥），**3.0.22 并未发布中央仓库**，`com.app.dc`/运行镜像亦未切换。
- 下一步必须先给新的 Common 正式 GAV 准备发布凭据/发布通道，然后 `com.app.dc` 唯一引用新 Common，Order/Trade/MD 依赖同一 `com.app.dc`/Common Jar，禁止服务端各自暗中覆盖不同 Common 版本。GitHub Actions 暂不使用。

### 4. 本轮结束时 Mac Demo 实际运行验收（09:04 CST）

- ZooKeeper **Order / Trade / MD 各 256/256 READY**；各两 Primary 节点 A/B 分别 128/128；实际 Order-C 是所有 256 分区的**同步 Replica**而非 Learner，故本轮**未滚动/重启任何 Order**。
- Order-A/B/C、Trade-A/B、MD-A/B/C 容器均 `running=true, OOM=false, restartCount=0`；运行镜像分别仍为 `dc-saas/ordersvr:merged-market-identity-image-20261015`、`dc-saas/tradesvr:merged-wal-fence-20261015`、`dc-saas/mdsvr:pr13-empty-image-20261016`。
- Robot **8/8 RUNNING、320 挂单、8/8 有效租约**。Mac 磁盘约 **83% 使用率、74 GiB 剩余**，需后续验证归档保留及清理，但不能以未验收的 WAL 删除替代保留安全检查。
- **阻断仍未通过：** Order/Trade 真实不同物理机独立密钥 signed Quorum、接入 MD `Safety` 的旧主隔离+候选已应用 Image/Diff 证明、Order/Trade/MD Primary SIGKILL 自动接管、资金持仓委托成交 Projection 权威一致性、50/200 租户长期压测。**代码回归 PASS ≠ 故障接管 PASS**。当前单 Mac 的三个 Order 容器没有跨物理机隔离；Trade 目前只有 A/B、每分区一个同步副本，也不满足 Common 当前要求的**两个幸存独立同步 Replica**证据，需补拓扑或持久化既有 Quorum 回执机制。

## 2026-10-16 08:16 Common 独立物理节点的提交证明与 Netty 控制接口（最新进展）

**本轮真实代码已合并、离线全量测试通过；仅新增可复用的 Common 组件，没有改变现网容器或自动主切配置。**

- [Common PR #27](https://github.com/bliplink/com.app.common/pull/27)，merge SHA `220d74eb2f3fdc27fa4f01be0ff60288289e20e0`：新增 `DurableCommitQuorumAttestation`。用途是让 Order/Trade/其他基于 Common 的业务服务，在恢复冷路径收集**不同物理主机**用**不同256-bit HMAC密钥**产生的、针对同一个已提交 Snapshot + WAL HEAD 的投票回执；绑定独立原始随机 Challenge、分区、Primary、Epoch、ZK version、Snapshot SHA、state/commit marker 和 committed HEAD。接收方采用外部可信的真实物理主机/密钥映射，拒绝重复节点、未分配同步副本、同物理主机、共享密钥、错节点、错 HEAD/epoch、伪造/过期 Challenge。证明签发要求业务注入 `LocalDurableAuthority` 并**前后两次**查询真正的本地 WAL 耐久提交状态。**本类只做签名与验证，`Verification.isPromotionAuthorized()=false`**，不提供假的实际 durable reader。
- [Common PR #28](https://github.com/bliplink/com.app.common/pull/28)，merge SHA `2e38c95019e6c03451e9e91d57e9b646fbe15192`：新增 `DurableCommitQuorumControlHandler`，复用现有 exact-node Netty `ReplicationControlHandler`，操作 `DURABLE_COMMIT_WITNESS_V1`。请求端**仅可提交挑战**，不得把自己编造的 HEAD/投票成员/版本交给源端签。源端必须分别从注入的真实在线 ZK 状态+Stat version、自己的磁盘 WAL/提交 Marker 读取可信 Source HEAD，生成带签名回执，并在返回之前**重新读同一 ZK 版本、角色、HEAD**；变动即拒绝。过期或未来挑战在任何 ZooKeeper、磁盘访问之前 fail-closed。没有自动 Spring 注册/公共 HTTP/API Key 路径，不改 Gateway。
- **实际测试：** 本地 ARM64 Mac，Java 8 / Maven 3.9.11 离线全量 Common `66 suites / 286 tests / 0 failures / 0 errors / 0 skipped`；其中针对性 15 项：两个不同 trusted physical host+独立密钥可验签但不能 promotion，重复节点/同机两容器/共享密钥/伪造 MAC/新旧 Challenge/HEAD 替换/错误 ZK 版本/不稳定 durable reader 全部拒绝；新增真实 Netty TCP 端到端回执交换测试。Common 原 `RecoverySourceAttestation.java` / `RecoverySourceHeadControlHandler.java` 两源文件 Git blob SHA 均与当前 GitHub `saas-crypto` 一致（分别 `4992edb83796087b85f9ecceeda17ba9aa2a1fe7`、`b124b907d1278e067a7970783c0c59c654a539b6`）。
- **实际未完成的业务端接线：**
  1. Order/Trade 必须从**各自真实 Replica 的本地 WAL、fsync/commit marker、ZK Stat version**实现 `LocalDurableAuthority` 和 `LiveAssignmentAuthority`，在现有服务 Netty 控制器中**显式注册**新的可选 operation；不能只把旧复制 ACK JSON 包装成签名。
  2. 必须将受信任的**每台真实物理主机唯一身份及不同密钥**下发到独立节点，接收端从实时 ZK 原始投票成员判定已分配同步 Replica。**当前 Mac mini 是一个物理主机**，即使运行 Order A/B/C 三容器，也不能声称得到两份独立物理节点证明；生产物理 Quorum 审批须在不同机器上验证，Demo 可以保持逻辑故障注入但不能将其与物理证明混淆。
  3. MD `MdImageRecoveryFailoverController.Safety` 尚须真实验证 Order 已提交 HEAD 多节点证明、旧 Epoch 发行者被隔离、候选实际应用完整 Image + Diff 的持久证明以及 RECOVERING→READY 事务；前述 Common 验签成功本身不放行 READY。
- **发布状态：** Common 新代码已合并 `saas-crypto`，但**未发布新中央仓库版本/未更新现网 Common Jar**。当前 Demo Order A/B/C 全部仍运行 `dc-saas/ordersvr:merged-market-identity-image-20261015`，MD A/B/C 仍为 `pr13-empty-image-20261016`。本轮没有重启、清库、SIGKILL 或修改 Gateway；没有调用 GitHub Actions（账单余额不足）。
- **当前真实结论：** 通用签名和传输的可测试机制已落地；**从真实磁盘 committed ACK → 物理独立 Quorum → MD Safety 的生产接线还没通过，因此 Order/Trade/MD Primary 自动故障接管和最终持仓权威对账仍 BLOCKED**。不要用 Common 286/286 单测替代实际故障注入验收。

## 2026-10-16 07:38–07:53 Order 自动晋升 Quorum 身份安全修复（最新进度）

### 生产安全逻辑修复并合并：Order [PR #17](https://github.com/bliplink/com.app.dc.ordersvr/pull/17)

直接审查并真实红/绿测试 `OrderFailoverPromotionSafety` 的两项 HA 故障晋升漏洞，不是增加验收脚本：

1. **同 Snapshot 基线序号、不同 Image 身份被误当同一持久化前缀。** 原代码只比同步副本的 `committedStateSeq / commitMarkerSeq / journalLastSeq / baselineEpoch` 等，没比具有相同 `baselineSeq>0` 的 `baselineSnapshotId`。因此具有相同或不同提交 Marker 的两份同步副本 proof 均可能在持有不同 Image 身份时被接受。已在所有同步副本参与比较前独立验证“**相同基线 offset ⇒ 相同 Snapshot ID**”；确实不同的合法压缩点继续允许，不能因为此项阻止正常继续从 WAL 追平。声称已有 `baselineSeq>0` 却缺少 Snapshot ID 的证明被拒绝。
2. **重复节点可以伪造第二票逻辑 quorum。** 原 `liveSynchronizedReplicas.size()>=2` 没去重；同一个 `OrderSvrB` 重复两次，`queryFailoverProof` 两次返回相同本地证据，竟可以晋升。现对经过 `PartitionConfig.normalizeServerName` 的节点集合去重，并逐一要求 `current.isReplica(node)`，确保至少两个**不同的、当前实际分配的同步 Replica**。这不等于不同物理主机或独立密钥的密码学证明，后者仍需单独实现。
3. 真实 TDD：旧代码两次出现 `Expected exception: java.lang.IllegalStateException`，分别覆盖同 offset 不同 Image ID、及重复节点伪 quorum；修复后这些用例通过，且不同压缩点/提交 Marker 中断的现有正向测试不回退。完整 Mac Java8/Maven **Order 80 suites / 342 tests / 0 failures / 0 errors / 1 skipped**。
4. GitHub [Order PR #17](https://github.com/bliplink/com.app.dc.ordersvr/pull/17) **已合并**，merge SHA `ee677414e9e60e78f528da1f8f217f9b02fdcafe`。本地两份实际编译源码 Git blob SHA 与 PR 分别为 `2c294839dfa213ffc852c4c4da1baf632103b578`（`OrderFailoverPromotionSafety.java`）和 `c94843270389f9d40afce20c42ec7cddd577d46b`（PR16 已合并的 `OrderMdMarketManifest.java`）。
5. **准确对齐运行镜像基线：** 现网 `dc-saas/ordersvr:merged-market-identity-image-20261015` 源 commit `c9aba21273072ec2615a88488abef1717223bf62` 确实可由 GitHub API 验证，且为 `saas-crypto` 的祖先。补丁涉及的两个 Java 类在该源 commit 的 Git Blob 均与测试前原始类完全相同。不能仅因为浅克隆 `git show` 找不到历史 commit 就认定镜像基线不明。
6. **仅构建未部署的本地安全补丁镜像**：以运行镜像 `sha256:035525d7f24ce96942285e58889fb0b0e917986be81dbf9eec17c434a5fdf8b6` 为基础层，`COPY` **严格两个类文件**，其他业务/复制/WAL classes、所有基础 JAR 不变：
   - Tag：`dc-saas/ordersvr:pr16-pr17-two-class-safety-20261016`
   - 新 Image ID：`sha256:ca76b17dea1b461ecac3ab186b63f24fc2f69902e5a40b619ed1465393a25de1`
   - `OrderFailoverPromotionSafety.class` SHA-256 = `9abafb8fe384c7821d7b40972d7c5ab07d8d3182722e53d87091eab3a0a6a929`
   - `OrderMdMarketManifest.class` SHA-256 = `c0e70b465efe4a2b1d72029a20d032e31ffafa518a246d9e3e418c3534a30029`
   - Common JAR `8898812068751cc3ab3916bb7b55fe535c10a413ffef7e9be20436d6ac8ff154`，`com.app.dc` `ca9017749ed1a2a218a300ca92f7f1b2b16c273d0adbbc58a37d59f639c625ae`，JDBC `mysql-connector-j 8.0.33`。
   - 镜像标记 `dc.release.authorized=false`；**构建并不等于正式运行验收**。
7. **实查生产分区拓扑阻止不安全滚动：** Order C **并不是 Learner**！实时 ZooKeeper 为 Order A/B 各 Primary128；A/B 各承担对方 Primary 的 sync Replica128；**Order C 是全部256分区的同步 Replica**，Order 没有 Learner 分配。先前“Order-C 可像 MD-C 一样安全替换”的假设被准确拓扑证伪，故本轮**没有重启或替换任何 Order A/B/C**；Demo 的三个运行 Order 仍是旧镜像。MD-C 则确实是 256 Learner，二者拓扑不同。
8. Demo 最后校验：Order/Trade/MD 皆 256/256 READY；Order/Trade 五业务节点运行正常；8 个 Robot RUNNING、320 挂单、8/8 有效租约；本轮没有清除数据、SIGKILL 或故障注入。
9. **仍 BLOCKED 的主线：** 不同 Order Replica 的逻辑节点证明尚非真实独立物理节点密钥/HMAC 签名；Common 已有 `RecoverySourceHeadControlHandler` 提供主节点挑战+MAC 接口，但 Order 当前未接源端真实耐久 HEAD authority，MD 尚无真实 `MdImageRecoveryFailoverController.Safety` 实现，故不得启动 MD Primary SIGKILL。下一步必须完成物理密钥 Quorum / MD Receiver 已应用 Image+Diff / Epoch 旧主隔离，并设计受控 Order 2 主+1 同步副本镜像灰度切换，不能直接停 C。

## 2026-10-16 07:22–07:30 Order→MD 空市场提交快照跨服务协议修复（最新代码进展）

**本轮已修两端并合并源码，但没有更换现网 Order/MD 镜像或执行危险 Primary SIGKILL。** 不应与前一轮 MD PR13 的已部署状态混淆。

- **真实缺陷：** MD 的 PR13 接受通过独立签名、HEAD 和哈希验证的零市场 `books=[]`，但 Order 源端 `OrderMdMarketManifest.fromCommittedSnapshot` 仍对 `snapshot.getBooks().isEmpty()` 抛错；旧 MD `MdOrderSnapshotCheckpointContract.parseCheckpoint` 又拒绝空 `marketVersions`。这使大多数合法空分区在 Order→MD 的另一种 checkpoint 数据格式下无法被校验。
- Order 源端最小修复：`books==null` 仍拒绝，但完整且已提交的零市场清单可以编码；commitMarker、source epoch、seq、快照 ID、重复市场检查未放宽，`promotionAuthorized=false` 不变。新增合法空清单与被反射注入真正 null 库存的损坏快照测试。
- MD 消费端最小修复：允许**明确存在的**空 `marketVersions`，仍严格校验 canonical SHA、元数据与 `promotionAuthorized=false`；缺失库存、额外候选市场仍拒绝。两个模块以独立 fixture 交叉核对空快照摘要：`f408607be32606a8aa32404c2a52c3f5e2c0e27ab1c2a679c65732c33c25b81e`。
- 先 TDD 红灯：Order 原代码 `MD manifest refuses missing/empty partition market inventory`；改动后源端+接收端目标测试均 PASS，离线 Maven Java 8 全量回归 **Order 80 suites / 338 tests / 0 failure / 0 error / 1 skipped；MD 33 suites / 146 tests / 0 failure / 0 error**。
- 代码均已合并：**[Order PR #16](https://github.com/bliplink/com.app.dc.ordersvr/pull/16)**（`c8f93814785d8d45cbc36e378a8d10c5264e5794`）；**[MD PR #14](https://github.com/bliplink/com.app.dc.mdsvr/pull/14)**（`455aa2da39b684cccff9260e3aaf8fc96a0ed1ea`）。两端仅处理 checkpoint 兼容，不是增强主切自动化。
- **部署审慎保留：** Order 当前运行镜像 `dc-saas/ordersvr:merged-market-identity-image-20261015` 带有 `dc.source.revision=c9aba212...` 标签，但该修订在本地测试源仓库无法解析；测试来源 `239f765` 与现网 Docker classes 数量有差异（测试代码 227 vs 现网 225），无法证明“整套编译类”直接覆盖不会回退正在运行的复制/WAL 逻辑。为避免影响业务，没有做无证明的整镜像替换。需要统一现网精确源码基线/仅经验证的单类补丁后再替换。
- **关键主切仍未完成：** 源端仍只有 `OrderMdCheckpointHeadGate` 的本地 checkpoint 观察，不是 Order 独立物理节点签名的多副本 HEAD commit ACK；MD `MdImageRecoveryFailoverController.Safety` 没有完整真实旧主隔离+接收侧已应用 Image/Diff+Epoch 凭据。新格式并不为任何 Primary 颁发授权，故 MD 自动选主、Order/Trade SIGKILL、资金权威一致性、200 租户稳态仍记 **BLOCKED/未验收**。

## 2026-10-16 07:10–07:19 MD PR13 签名空市场分区恢复修复与三节点替换（最新状态）

**仅解决现有 256 分区 HA 恢复校验的缺陷；未启用自动 MD Primary 主切。**

- **实际发现：** `MdAuthenticatedOrderImageReview.inspect` 直接拒绝 `books=[]`；`MdPartitionMarketCoverage.inspect` 又拒绝任何空 source census。MD 256 个分区中大量无交易市场，即使拥有新挑战、Order Primary 身份及 ZooKeeper version、签名 HEAD、逐字节 Snapshot SHA-256 和完整提交边界，也不能进行合法空市场 Image 校验。这会阻断无活跃市场分区的恢复核验。
- **先失败复现再修复：** 新增 `signedEmptyMarketPartitionIsValidOnlyWithNoLocalCandidateMarkets` 测试，旧实现真实失败 `signed Order market image missing full inventory`。最小改动仅允许**非 null、确实从签名快照提取的空市场清单**；如果候选本地 Witness 有任何该分区中未声明的市场，仍产生 `UNDECLARED_CANDIDATE_MARKET` 阻断。缺失/null 清单仍拒绝，签名挑战、来源身份、Image SHA、HEAD commit marker 等旧严格校验不变。`Review.isPromotionAuthorized()` 始终为 **false**，没有绕过 MD `Safety` / Quorum / 发布者隔离。
- 本机离线 Java 8 / Maven 完整 **33 suites / 145 tests / 0 failures / 0 errors**，新增缺失 census 拒绝测试也通过；修改已经合并 MD [PR #13](https://github.com/bliplink/com.app.dc.mdsvr/pull/13)，merge commit `3382331782c90c1afe48012507b604444a58670b`。编译用三个源文件 Git blob SHA 与合并 PR 一致。
- 离线构建镜像 `dc-saas/mdsvr:pr13-empty-image-20261016`，Docker **完整 image ID `sha256:61dfa45f4001478479a6bca134efab4db8382b115c42d273cd74759652d990a1`**。以已通过回归的 PR12 本地镜像作为基础，覆盖这次通过测试的 classes，不拉 Docker Hub；Common/`com.app.dc` 依赖保持前一轮统一锁定版本。
- Mac Demo 使用实际 `DEPLOY_ROOT`，严格 **MD-C → MD-B → MD-A** 单节点滚动替换，每一步必须等到该节点原有活跃市场 `MD_MARKET_READY` 才继续：C **8/8 Learner**、B **3/3 Primary**、A **5/5 Primary** 均 PASS。
- 上线后实时校验：MD A/B/C **相同 image ID**、running=true、OOM=false、restartCount=0；**MD/Order/Trade 各 256/256 READY**，Primary A/B 均 128/128，未修改 Order/Trade/Gateway 容器；公开 API 八个 Robot 租户均 **10 bids/10 asks**，Robot **8/8 RUNNING、320 挂单、8/8 租约有效**；`tests/run-saas-acceptance.sh --quick --running` 完整 **PASS**。
- **仍然 BLOCKED：** 上述签名快照校验只是只读核验，不等同于独立完整 durable Quorum ACK、候选落地 Image+Diff 证明和旧 Epoch MD 发行者隔离证明。真实 `MdImageRecoveryFailoverController.Safety` 尚无生产提供者，`md.cluster.failover.enabled` 默认关闭，**不能记作 MD Primary SIGKILL 自动主切通过**。Order/Trade Primary SIGKILL 和持仓权威对账亦未通过。
- **本轮没有重复执行**以前 PASS 的 GTC 人工双向主切、1,486,020 条 Projection Mutation 全范围在线扫描；必要时后续故障验收须重新建立各账本真实权威断点，不得用旧审计报告代表新故障注入的对账。

## 2026-10-16 06:49–06:58 MD PR12 旧主隔离重新校验与三节点部署（最新状态）

**任务边界：仅修复 Common/MD 主切现有状态机的 fail-closed 安全缺口，不新增功能、不引入虚假的可信证明提供者、不打开自动主切开关。**

- 源码检查发现 `MdImageRecoveryFailoverController.finishRecovering()` 在候选节点已取得 Order Image、已应用 Image+Diff、恢复 Epoch 出版隔离成立后，仅在原 READY→RECOVERING 转换阶段确认过**旧发布者隔离**，却未在最终 RECOVERING→READY CAS 前再次核验。旧发布者在重建期间重新出现、旧 Epoch 隔离证明丧失时可能被错误放行。
- 在 **真实正在部署的 PR10 源码**中先加回归测试 `recoveringReadyMustRevalidateOldPublisherFenceAfterImageArrives`：模拟 A 已被隔离、B 进入 RECOVERING、完整 Image 已应用、恢复 Epoch 发布屏障为真，但**旧发布者独立隔离证明在恢复期间被撤销**。原代码测试明确 **FAIL：`expected FENCING_UNPROVEN but was READY`**。
- 最小修复：在 READY CAS 前再次调用真实注入的 `Safety.requireOldPublisherFenced(current)`，没有有效旧主隔离证明则 **`FENCING_UNPROVEN`、保持 RECOVERING、不写 READY**；复位证明后才能继续。修复后本地 Java 8 + Maven 全量 **33 个套件、143 项，0 failure、0 error**。
- 已合并 MD 仓库 [PR #12](https://github.com/bliplink/com.app.dc.mdsvr/pull/12)，提交 `180de47c2a994f5a0e7a6fbaf6e9ad5f4b4b16c8`。本地关键源码 Git blob SHA 与提交后一致，MD `com.app.dc` 依赖按 [PR #11](https://github.com/bliplink/com.app.dc.mdsvr/pull/11) 显式锁定到 Demo 的 `0.0.5-devcombined-20261015-SNAPSHOT`，Common 仍为全服务统一 SHA。
- Docker Hub DNS 不通，故以本机已经验证的 PR10 镜像为基础，离线 COPY 已通过测试的全部 MD `target/classes`，构建新镜像：
  - **tag**：`dc-saas/mdsvr:pr12-old-publisher-fence-20261016`
  - **完整 image ID**：`sha256:047445e87edd302d57769dd06852873d1dfab695ea34ae977c01f9d815c50c3b`
- 按 **MD-C→MD-B→MD-A** 顺序滚动 `docker compose up -d --no-deps`，每次使用 Mac 的 `DEPLOY_ROOT="$HOME/.opentradingcore/dc-saas-runtime-ordered-20261015"`，保留源 `.env.prod`、全部数据、Order/Trade/Gateway 不变；必须等前一节点本分区 `MD_MARKET_READY` 才进入下一节点。
- **真实部署与恢复验收 PASS**：C 的 8/8 `LEARNER` 市场、B 的 3/3 `PRIMARY` 市场、A 的 5/5 `PRIMARY` 市场全部 Image READY；MD ZooKeeper **256/256 READY**。三台 MD 容器 Image ID 完全一致、running=true、OOM=false、restartCount=0。Order/Trade 五节点全部运行，Robot **8/8 RUNNING、320 单、8/8 有效租约**；本次未执行危险 SIGKILL。
- **未完成项：** 已部署的 `MdAutomaticFailoverService` 仍默认关闭，**生产缺少独立可信的 `MdImageRecoveryFailoverController.Safety` 证明提供者**，尤其旧主独立隔离、Order 当前完整 Image 签名/水位、候选 Image+Diff 应用、Epoch 发刊闭锁，以及 Robot 故障后对账。新 PR #12 只是修复已有门禁的 TOCTOU 缺口，**不能把新版镜像+READY 当成真正的 MD 自动 Primary SIGKILL 主切通过**。下一轮应直攻这些尚缺的授权证据，避免重复运行已 PASS 的 Learner 冷启动、普通盘口和旧角色切换。

## 2026-10-16 06:17–06:39 Mac MD PR10 真实滚动部署验收（最新状态）

> **真实实施完成，不是计划。** 本次仅修复现有集群恢复相关代码、验收脚本与 Maven 构建依赖；不新增产品或 Broker API 功能。Mac 的 DNS 无法访问 Docker Hub，且 `git fetch` 连接 GitHub 失败，因此所有 Java 编译、Docker 镜像均在 Mac 本地完成；代码通过 GitHub 连接器提交 PR。

### 1. MD 已合并修复的构建与镜像

- MD 的 PR [#10](https://github.com/bliplink/com.app.dc.mdsvr/pull/10) 包含 **Order Image 必须实际应用到当前 MD Epoch 后才可 READY** 修复。Mac 采用本地干净 worktree `f68eeee`（从现网基线 `6cfb994` cherry-pick 同一修复），并核对 `MdPartitionRuntime.java`、`MDFacade.java`、`DepthBookFacade.java` 的 **Git blob SHA 均与 GitHub `saas-crypto` 完全一致**。
- Java 8 / 离线 Maven 3.9.11：**33 套测试、142 项，0 failure、0 error、0 skipped**。本地依赖指向 `com.app.dc 0.0.5-devcombined-20261015-SNAPSHOT` 和 `Common 3.0.21-devcombined-20261015-SNAPSHOT`。新镜像 Common JAR SHA=`8898812068751cc3ab3916bb7b55fe535c10a413ffef7e9be20436d6ac8ff154`，`com.app.dc` JAR SHA=`ca9017749ed1a2a218a300ca92f7f1b2b16c273d0adbbc58a37d59f639c625ae`，均与当前 Order/Trade/MD 的运行 JAR 一致；MySQL 驱动为 **8.0.33**。
- Maven POM 上游默认仍为 `com.app.dc 0.0.4-SNAPSHOT`；现已通过 MD PR [#11](https://github.com/bliplink/com.app.dc.mdsvr/pull/11) 添加可覆写 `-Dcom.app.dc.version=...`，不改变默认线上依赖，也不使临时版本硬编码进仓库。
- `eclipse-temurin:8-jre` 在 Mac Docker 里未缓存，Docker Hub DNS 不可用；使用**运行中 MD 镜像作为缓存的 Java8 基础层**，用已通过测试的 `target/classes` 和 `target/dependency` 全量替换相同目录后生成新镜像。这不是业务逻辑替换之外的新增代码：
  - 新镜像 tag：`dc-saas/mdsvr:pr10-applied-epoch-20261016`
  - **完整 Docker image ID：`sha256:20d655e57548f8f5315d172e6476c28268ed377bddf4cf17c55d89ff1726a7e1`**
  - 原 MD 全部三个节点为 `dc-saas/mdsvr:epoch-refresh-after-subscribe-20261015`、源修订 `6cfb994`；现 A/B/C 全部使用相同新镜像 ID。

### 2. 真实 Demo 三节点替换与业务验收

- 滚动顺序：**MD-C（256 Learner、0 Primary）→ MD-B（128 Primary）→ MD-A（128 Primary）**，每次只重建一个节点，Order/Trade 未替换，也未人为改动 ZK 分区。
- 第一次重建 MD-C 遇到部署配置缺陷：旧 `.env.prod` 的 `DEPLOY_ROOT=/data/dc-saas-runtime` 是 Linux 路径，Mac 上 bind mount 不存在，因此容器创建后启动失败。**已立即修复并恢复节点**：只为 Mac 这次 Compose 命令覆写 `DEPLOY_ROOT="$HOME/.opentradingcore/dc-saas-runtime-ordered-20261015"`；不覆盖含密钥的源 env 文件、不清除数据。以后 Mac 重新部署必须显式带上此路径。MD-C 后续完整启动，先前的安装失败不能被伪记为零故障。
- MD-C 重订阅 Order 后 8 个活跃 Robot 市场 Image **8/8 `MD_MARKET_READY role:LEARNER`**；MD-B 负责的 3 个活跃市场 **3/3 `role:PRIMARY`**；MD-A 负责的 5 个活跃市场 **5/5 `role:PRIMARY`**。
- 三个 MD 容器均运行、OOM=false、restartCount=0；ZooKeeper MD **256/256 READY**，Primary A=128 / B=128，C 仍为 Learner。
- 用真实 `MDSvr.queryPublicMarket` 查询 **8/8** 活跃 Robot 租户，全部买盘/卖盘分别 **10/10 档**。Robot **8/8 RUNNING，320 挂单，8/8 有效租约**；其他服务仍然正常运行。
- SaaS Quick Smoke 最初检测到历史 READY 双重计数：Trade P000/P020 曾 A→B→A，旧脚本只按分区收集全历史日志，虚报 A=128/B=130 overlap=2。已修复为**当前 ZooKeeper 分区 Primary+Epoch 与实际 READY 日志配对**，同 Epoch 双主仍阻断；修复已合并到 deploy PR [#68](https://github.com/bliplink/dc-quant-deploy/pull/68)。真实全量 `--quick --running` **PASS**，包括 23 个容器、256/256 Trade READY A/B 各 128、全部配置和服务健康。
- MD 只读 failover 门禁的旧 GHCR 镜像标签误报已修复，新增当前容器镜像完整 SHA-256 锁定并测试，deploy PR [#67](https://github.com/bliplink/dc-quant-deploy/pull/67) 已合并。

### 3. Projection 全范围一致性核对

本机执行 `tests/check-projection-consistency-host.sh`。最初使用 75 秒上限只扫描 800,000 条并返回 `PARTIAL_NOT_ATTESTED`，**未将此错误伪称 PASS**。之后维护窗口内以 `PROJECTION_ORPHAN_MAX_SECONDS=360`、`PROJECTION_ORPHAN_CHUNK_SIZE=20000` 完成固定上界全范围扫描：

- `scanned=1486020` Mutation，`pages=75`，`elapsedSeconds=206.667`
- `orphanMutations=0`、`decision=PASS_LIVE_RANGE_OBSERVATION_ONLY`
- Order watermark **9/9**、Trade watermark **9/9**，tail mismatch 0；跨分区 event_id 冲突未发现。
- 本机报告：`$HOME/.opentradingcore/cluster-evidence/projection-orphan-post-mdpr10-20261016.json`。**注意：`consistentTransaction=false`、`authoritativeAttestation=false`，此 PASS 是固定上界在线范围扫描，不等同于故障后的完整强一致快照。**

### 4. 仍未完成，下一轮必须接续的真实阻断

1. **MD Primary 自动 SIGKILL：BLOCKED。** 在新版镜像实际 Image ID 上再次运行 `scripts/check-md-failover-preflight.py --expected-image-id sha256:20d655e5...`，没有任何“未审查镜像”误报；但以下五项仍为真正 blocker：`ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING`、`MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED`、`MD_RECOVERING_TO_READY_EPOCH_PUBLICATION_FENCE_UNATTESTED`、`MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED`、`ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED`。**新 Image-READY 修复已部署，但自动主切机制尚未完成**；不要绕过安全门禁停止 Primary。
2. **Trade 带真实持仓的自动故障接管：BLOCKED。** 已合并 deploy PR [#66](https://github.com/bliplink/dc-quant-deploy/pull/66) 的受控 A→B→A 合法交易员资金/持仓查询验收候选脚本，已同步到 Mac 独立测试文件并通过语法编译；本轮发起真实持仓业务运行请求被执行环境安全检查拦截，**没有实际新建测试租户、入金或切换 Trade Primary**，不能把源码合并当作测试通过。
3. **Order Primary SIGKILL 自动接管仍未做，**前序执行请求曾被环境安全检查拦截；已通过的仅是三副本在线受控主备切换/真实 GTC 订单存续。
4. **WAL 自动归档、安全删除、10→50→200 租户稳态与 burst 未验收通过。** 磁盘此时约 82% 使用率（约 81 GiB 可用），未删除 WAL/旧 Demo 数据。不要重复已通过的 Image 与挂单切换检查；修复上述 Primary 安全授权后继续故障注入、资金/持仓/委托/成交与 Projection 权威对账。


## 本轮真实执行且 PASS 的项目

| 项目 | 动作和证据 | 结论 |
| --- | --- | --- |
| **Trade P000：空分区** | 当前 Demo 上 Trade A→B→A，ZK CAS epoch 1→2→3；两次新主均完成 READY；Projection 前后 14 条水位不回退。 | **PASS：人工受控角色切换** |
| **Trade P020：活跃分区（H4676T）** | 有业务持仓；Trade A→B→A epoch 1→2→3；B 恢复 `committedStateSeq=27061`、`riskAccounts=2`；A 恢复 `committedStateSeq=27093`、`riskAccounts=2`；两次新主均 READY，14 条 Projection 水位不回退。 | **PASS：人工受控角色切换与恢复门禁**，不等于“故障自动主切 + 客户持仓逐项校验” |
| **Order P000：三副本空分区** | A/B/C 同一快照，A→B→A CAS epoch 1→2→3；两次 `ORDER_PARTITION_PROMOTION_READY`；最终 A/B/C 快照 byte hash 一致。 | **PASS：人工受控角色切换** |
| **Order P228：活跃市场 H4676T** | A/B/C 三份已提交市场 Snapshot 完全一致，A→B→A CAS epoch 1→2→3；两次新主均 READY；实际 `MDSvr.queryPublicMarket` 双侧 **10/10 档**；最终三副本快照哈希重新一致。 | **PASS：活跃业务分区角色切换及行情服务** |
| **Projection / Robot 后验** | 全部切换后孤儿 Mutation=0，Order+Trade watermark mismatch=0，各 7/7；Robot 6/6 RUNNING、240 单，租约有效 6/6；八个 Order/Trade/MD 容器 0 重启/OOM。 | **PASS：所测项目** |
| **ZK 最终角色** | Order 256/256 READY，其中 P000/P228 epoch=3，另 254 分区 epoch=1；Trade 同样 256/256 READY，其中 P000/P020 epoch=3；MD 256/256 READY，仍 epoch=1。A/B Primary 各 128。 | **PASS：当前静态分配** |
| **MD-C Learner 真实 SIGKILL** | 上一轮实际终止并重启 MD-C，六个市场重新读取 Order Image，分区/Primary 未变化，原重启策略恢复。 | **PASS：Learner 故障恢复，不是 MD 主切** |

### Mac 上的原始证据

- Trade 空分区：`/Users/kong/.opentradingcore/cluster-evidence/20261016-001050-trade-role-reversal/summary.json`
- Trade 活跃持仓分区：`/Users/kong/.opentradingcore/cluster-evidence/20261016-001140-trade-role-reversal/summary.json`
- Order 三副本空分区：`/Users/kong/.opentradingcore/cluster-evidence/order-p000-role-reversal-20261015T161723Z.json`
- Order 活跃盘口：`/Users/kong/.opentradingcore/cluster-evidence/order-active-P228-A-B-A-20261015T161926Z.json`
- 最终 Projection：`tests/check-projection-consistency-host.sh` 在 2026-10-16 00:20 CST PASS；孤儿与双源 watermark 均无异常。

证据为本机受保护 Demo 文件，不是已上传公开仓库的日志/密钥副本。**角色切换操作采用在线版本 CAS；没有中断整个容器、触发自动选主或模拟物理节点故障。**

## 2026-10-16 00:26–00:28 Mac 新增真实业务回归：PASS

在以上 Order P000/P228、Trade P000/P020 在线角色切换全部完成后，执行：

```bash
set -a; . /Users/kong/dc-quant-deploy/.env.prod; set +a
python3 tests/run-auto-tenant-trading-e2e.py
```

- 新租户 **T1MPT1** 公开申请自动批准，流动性初始化完成，Robot `NOTIONAL_ZONES / RUNNING / 40`，公开盘口买/卖各 10 档。
- 新交易员正常注册登录、`Demo=1` 入金 1,000；真实 IOC 成交 0.0001 BTC，MySQL 订单/成交/Long 持仓吻合。
- Reduce-Only IOC 平仓完成；**测试交易员**最终持仓=0、活动订单=0，业务测试退出码 0。租户内的 Robot 做市账户仍可能有正常持仓，不能把“测试交易员归零”误写成“全租户全部头寸归零”。
- T1MPT1 测试后留在 `TRIAL`，Robot `RUNNING/40`；全 Demo 此时七个 Robot 运行，总目标挂单 **280**，七个租约仍有效。没有擅自删除测试租户。
- 后验 `tests/check-projection-consistency-host.sh` **PASS**：Order+Trade 水位分别 **8/8**，orphan mutation=0，watermark tail mismatch=0，cross-partition duplicated event ID=0。

**另外发现一个必须修复的验收工具问题：** `tests/run-order-live-role-reversal-e2e.py` 硬编码早期 `EX2ENF/P110` 隔离租户（当前 Demo 已不存在），并在 A↔B 变更时只更新 `replica` 单值、未正确更新同步副本列表 `replicas=[另一节点,OrderSvrC]`。因此**不能直接用于当前三副本集群**。现已用新脚本 `tests/run-order-three-replica-real-order-e2e.py` 替代该旧脚本并完成真实挂单穿越 A→B→A、正常撤单验收（详见新增 PASS 证据），旧脚本仍只适用其历史隔离拓扑，不应在三副本执行。

## 2026-10-16 00:34 Mac Order 真实 GTC 挂单存续验收：PASS

旧 `run-order-live-role-reversal-e2e.py` 仍绑定已经删除的 EX2ENF，并漏维护 Order-C，不能直接在三副本中用。**已编写、真实执行并通过的替代工具：** `tests/run-order-three-replica-real-order-e2e.py`（本 PR 同步提交源码）。

执行命令（需要 Mac Demo 合法的本地 env；不在日志显示任何密码）：

```bash
set -a; . /Users/kong/dc-quant-deploy/.env.prod; set +a
python3 tests/run-order-three-replica-real-order-e2e.py
```

- 通过 Manager 公开租户申请注册 **QE0L6W**，其 `BTCUSDT/4` Order 分区为 **P112**；等待自动审批、Robot RUNNING/40、三副本已提交市场快照 SHA 一致。
- 注册正常交易员、登录并 Demo 入金，真实提交一笔 **GTC 限价挂单**，`OrderSvr.queryOpenOrder` 可查。
- ZK 对 **单分区** 做带版本 CAS：**OrderSvrA→OrderSvrB，Epoch 1→2**，保留 A/C 两同步副本；B 经过 `ORDER_PARTITION_PROMOTION_READY` 后，以实际交易员 Token 再次查到同一个已确认订单。
- 再做 **OrderSvrB→OrderSvrA，Epoch 2→3**，保留 B/C 两同步副本；A 新 Epoch READY 后仍可查到同一订单。
- 真实 `cancelAllOrder` 后，该 GTC 不再在活动订单中；脚本退出码 0，输出 **PASS**，ZK 最终 **P112 READY / Primary A / Replica B,C / Epoch 3**。
- 实际本机证据：`/Users/kong/.opentradingcore/cluster-evidence/order-3rep-live-gtc-20261015T163433Zc30a.json`。测试租户留在 Demo TRIAL 持续 Robot 报价，为后续多租户压测提供样本；没有执行容器 SIGKILL。

**验收语义：PASS 是客户订单在双向主备角色切换中的存续与正常撤单，尚不是节点 SIGKILL 自动接管或带 Trade 持仓的资金权威对账。** 不要因本项通过误把全部 HA 目标完成。

## 尚未通过的关键项目与明确下一动作

1. **Order Primary SIGKILL 自动接管：BLOCKED。** 本轮尝试发起真实 Order-A SIGKILL 验收，但外部执行环境安全检查拦截了命令，**未终止节点、未修改 ZK**。不要谎称已做。后续通过合规可执行的故障注入途径，保留旧主隔离与已提交 WAL 验证，再做全链路自动接管和恢复节点追平。
2. **Trade Primary SIGKILL + 持仓账本：BLOCKED。** P020 人工主备切换已成功，现有 MySQL 持仓记录中有 2 个非零头寸；但接管到 Trade-B 的窗口内尚未以客户合法会话读取并比对实际资金、持仓及成交。平台 Manager 会话调用 `TradeSvr.queryTradePosition` 按权限返回 `1003`，不能以跨租户管理员请求绕过。需创建合法隔离测试交易员，持仓穿越故障、对账再平仓。
3. **Trade 恢复统计核查：仍须注意。** Trade-B 在流式 WAL 恢复时日志显示 `locations:0, riskAccounts:2`；`TradeRecoveryPlan.streamed()` 的 `getLocations()` 只来自零基线快照，而 `TradeRecoveryApplier.validateStreamed()` 会扫描 WAL 收集并恢复租户，因此 **`locations:0` 是计划统计不足，不能直接视为资金丢失，亦不能用 riskAccounts:2 代替精确账本对比**。最小修复只应解决验收证据或真实状态问题，不扩大功能。
4. **MD Primary SIGKILL 自动选主：BLOCKED。** 必须验证旧发布者 Epoch 隔离、接收端已应用的 Order 完整 Image + Diff、ZK CAS，不能用 MD-C Learner 恢复冒充主切。
5. **WAL 自动归档与安全清理、200 租户稳态及 2–3 倍 burst：未验收。** 要在故障接管/一致性先过门禁后继续；无证明不得删除正在被读取的 WAL。

## 接续顺序（切忌重复）

- **下一项：Trade 合法测试交易员持仓状态穿越接管的业务级核对，然后真实故障场景。** 确保复制 ACK 的已提交 HEAD、候选接收已应用内容，以及 READY 后 API 资金/持仓相等。
- 再执行 **Order-A 容器故障自动 promotion + 节点回归为 Replica**，核对 Order/Projection/Trade 全部资金订单成交，业务不中断或恢复窗口可量化。
- **MD Primary 自动故障接管**，再做归档与 10→50→200 租户压力。修复明确失败项 → 本地编译 → 替换 Demo → 只重跑必要的相关验收。
- 按用户授权，无法快速回退时可受控清理隔离 Demo 数据、重新部署并重新注册租户；不要绕过可信 WAL/旧主隔离门禁。

以上是本轮**验收记录**，不是全量 HA 已发布通过的声明。
