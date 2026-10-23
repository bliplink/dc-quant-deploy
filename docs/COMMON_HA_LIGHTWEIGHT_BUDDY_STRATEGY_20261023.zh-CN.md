# Common HA 轻量选主与分区互备：实施决定

状态：**2026-10-23 用户已确认的目标架构 / 实施中，非生产完成**
范围：Common 共用集群基础设施 + 隔离 Demo；通过后才适配 Order、Trade、MD。
权威验收清单：`docs/COMMON_CLUSTER_REQUIREMENTS.md`；详细历史：`docs/COMMON_HA_SHARD_PLACEMENT_REPLICATION_DESIGN_20261023.zh-CN.md`。

> **2026-10-23 最新产品可用性决定（覆盖本文以下早期 NO-GO/严格 2/2 仅等待备机的历史描述）**：A/B 任一节点故障后，另一节点不仅要自动取得合法新 Epoch，还必须在旧主被隔离、旧已 ACK 前缀可验证、ZooKeeper 多数可用、本地 WAL 正常时，**自动以 `AUTO_DEGRADED_LOCAL_DURABLE` 单节点持久化方式继续下单、撤单与撮合**。它对新写入只承诺本地 fsync，不能承诺两份数据/零 RPO；正常双节点运行仍使用严格复制模式。该自动降级为明确配置并在 ZooKeeper Assignment 与客户端 ACK 标记的合同，不是默默降低原 2/2 的安全承诺。独立 Demo 已验证单分区 P000，尚未进入 Order/Trade/MD。

## 1. 架构决定：统一协议，两两互备只是默认放置策略

- **只实现一套按分区的成员、Epoch、租约、WAL、Snapshot/Diff、恢复协议**；`PartitionBuddyPlacementPlanner` 只是 RF2 的初始放置策略，不能作为第二套复制/选主框架。
- 每个业务分区有唯一可写 Primary 和 RF−1 个指定数据 Replica；默认 RF2，双节点对 A↔B、C↔D，主备**按分区互换**，而非一个节点整体只有一种角色。数据只向本分区指定成员定向复制，不是 N×N。
- Common 负责租约、选主、复制、WAL、恢复，业务仅注入 `apply(byte[])`、`snapshot()`、`restore(byte[])`（可选 `diff(byte[])`）。不得在 Common 耦合资金、订单或行情业务语义。
- ZooKeeper 是**低频控制平面**，维护 `service/partition/configVersion/epoch/primary/replicas`、合法租约及 CAS；客户端请求/Netty IO 热路径禁止每笔同步调用 ZooKeeper。
- RF3 及其它复制因子继续走同一 Common 接口与通用放置规划器；RF3 不能把“2 节点固定 buddy”硬套为 3 数据成员。也支持单节点显式策略，但不能声称 RF2/RF3 严格多数确认。

## 2. 256 分区与双向互备的确定性布局

每分区**仅 1 个主，1 个备**。每个节点在承担自己主分区的同时承担配对节点主分区的备份。该布局用于**全新未激活分区**：

| 数据节点数量 | 分组 | 主分区分配 | 每节点主数 | 每节点备数 | 复制目标数/分区 |
|---|---|---|---:|---:|---:|
| 2 | A↔B | A：P000–P127；B：P128–P255 | 128 | 128 | 1 |
| 4 | A↔B、C↔D | A：P000–P063；B：P064–P127；C：P128–P191；D：P192–P255 | 64 | 64 | 1 |
| 6 | A↔B、C↔D、E↔F | 各节点约 42–43 个主分区（整数均衡） | 42–43 | 42–43 | 1 |
| 8 | A↔B、C↔D、E↔F、G↔H | 每节点 32 个主分区 | 32 | 32 | 1 |

例如 A 主的 64 个分区只复制给 B；B 主的 64 个分区只复制给 A。每组主备应落在不同**物理**故障域，不得把同一宿主机的两个 Docker 容器当作独立物理副本。单机隔离测试必须标明模拟故障域。

**新增纯规划器**：`com.app.common.partition.PartitionBuddyPlacementPlanner.proposeNew(partitionCount, initialEpoch, activeNodes, existing)`。节点按稳定 ID 排序再成对；只返回 `PREPARING` Assignment，不做 ZK 写入、Epoch 授权、READY 或旧分区搬迁。发现奇数节点、非 ACTIVE、同组同物理主机、重复身份、服务名混杂、已有同名分区，均拒绝；新增节点不触发隐式在线分区重排。

## 3. A/B 自动主切：故障时低频小协议，不重复验证全量历史

1. Common 监控 ZooKeeper 成员状态、有效租约、提交水位及本地节点状态。ZooKeeper 多数失联时，现有 Primary 必须在有效授权失效前停止对外确认写入；不能用无限期缓存“假装合法”。
2. A 故障：有资格的协调者在 ZK 上原子取得新的 `epoch/configVersion/primary` 授权，并确保旧 Epoch 不能继续 ACK、发布或回写 WAL。网络隔离下必须防双主，不能只凭“ping 不通 A”升主。
3. B 本地校验自己的 WAL、commit watermark、checksum、恢复状态以及覆盖**所有可能已给客户端 ACK** 的安全提交边界。RF2 严格 2/2 的旧 ACK 已要求 B 对相应 WAL 落盘；故障时不需从已死亡 A 再请求全量签名，但必须有**可信持久提交边界**，不能把 `B.lastApplied` 直接视为 `maxAcked`。
4. ZK 新 Epoch 的 CAS 成功、B 恢复水位证明成立、旧 Epoch Fencing 完成后才能发布 READY。B 旧 Epoch 下提交证书的单节点只读 HEAD 查询**仅是证据收集**，不独立授权接管。
5. A 重启只能先成为 Learner / Replica：隔离旧 WAL 的未提交分叉尾，安装 Snapshot+WAL / Diff，重新追平并校验才可成为有效数据成员。**不自动抢主**。
6. 平时只有“Primary→指定 Replica 的单向批量 WAL 数据”和“Replica→Primary 累计 durable ACK”，无每请求全历史 SHA、重复 RSA 签名或多份单条控制 RPC；故障时 O(RF) 的轻量提交水位比较和 ZK CAS，不能消除必要的认证/防双主条件。

对 RF3，候选 B/C 必须选出确实包含旧多数已 ACK 提交前缀的节点；可复用成熟的一致性日志 Election/Commit 原理或 Common 有界持久水位交叉验证，不允许只选“机器可连、序号最大”却没有证书/任期真实性。**2 节点 buddy 的快速路径不意味着所有 N 节点任意可直接升主。**

## 4. 写入确认模式明确区分，不自动偷偷降级

| 模式 | ACK 前必须满足 | 仅剩 1 个数据节点时 |
|---|---|---|
| `LOCAL_DURABLE_ASYNC` | 合法 Primary Epoch + 本机 WAL fsync | 可继续确认；若永久丢失主盘，先前部分 ACK 可能不在备机，RPO > 0 |
| `QUORUM_DURABLE` RF2 | A+B 都完成 WAL 持久化及可信提交边界维护，严格 2/2 | B 可以经证明与 ZK 授权成为 Primary，**但不能继续返回严格 2/2 ACK**，除非新副本追平完成 |
| `QUORUM_DURABLE` RF3 | 任意合法 2/3 数据成员达到持久化多数，且新 Epoch 仍保持此合同 | 失 1 节点后仍可用剩余 2/3 严格 ACK；失 2 节点必须拒绝 |

需要仅剩 1 节点仍持续交易时，必须配置并显式记录本地异步/受控降级策略、风险与审计信息；严禁把它标记为严格多数零丢失。

## 5. 性能目标与实现优先顺序

性能提升依靠**正常业务热路径**的工程优化，不是单纯减少选主逻辑：
- Group Commit、分区内顺序批处理、Netty TCP 持久连接与批量定向 push、累计 durable ACK、增量 WAL hash/索引、异步 Snapshot 与归档、背压。
- 已持久化提交水位与安全证据必须支持故障后独立查询；在证据可靠前不得从写入路径移除安全保障。RSA/证书可以合并到批次或用经验证的等效持久多数协议取代，不是删除认证。
- 保留 Epoch 本地可撤销短效授权视图；控制面 watch/renew/失联时 fail-closed。控制面不能无限频率 RPC，也不能只凭本地永久 cached lease 阻止不了旧主。
- 目标端到端 P99 ≤30ms，分层采样 WAL append/fsync、Netty 排队、replica durable ACK、commit watermark、lease cache、client ACK；实测未达标须记录 FAIL。原 RF2 隔离 v19 严格托管仅约 11 TPS、组 P99 数秒，不能宣称新规划器已使性能变好。

## 6. 2→4 节点扩容，绝不直接重映射现有 256 分区

初始 A/B 成对拥有 256 分区时，添加 C/D 后，**不允许仅重新执行上面的静态规划器直接把 P128–P255 从 A/B 迁给 C/D**。正确在线迁移按分区分批进行：
1. C/D 以真实成员身份加入、各自产生独立存储目录/凭据；选出待迁移的分区，不一次移动全部分区。
2. 给候选 C/D 添加 Learner，复制 Snapshot+WAL，检查旧配置已 ACK 安全提交水位；迁移期间旧 A/B 仍是权威写入/持久成员。
3. 安全冻结/有界缓冲、旧成员 Fencing、ZK 原子提交新配置与新 Epoch；新成员满足提交条件后 READY。旧成员确认退出后才归档/回收旧 WAL。
4. 每迁移一个分区完成水位对账，再迁移下一个；最终 A/B/C/D 每人 64 主 64 备，并对用户透明。
5. 迁移中失败或重启：保持旧分区可用或 fail-closed，不能同时开放旧新双主；若有模糊安装事务保留证据。

## 7. 分阶段交付与验收关口

- **阶段 A（本轮）**：批准文档与纯初始 Buddy Planner、2/4/6 节点数量与故障域单测、不得自动激活或搬迁。
- **阶段 B**：Common 新增安全的 RF2 单幸存者候选机制，打通真实 ZK 重新授权 + 新 Epoch、旧主隔离 + 本地提交边界、自动 A→B/B→A，无任何脚本改成员或开 READY。
- **阶段 C**：完成严格 2/2 与本地异步两档独立容错、Replica 崩溃追平、脏尾隔离、旧主自动降备；再做 RF3 2/3 候选选主与多数交集验证。
- **阶段 D**：2→4 节点在线分区迁移、Learner/配置变更事务、A/B/C/D 各 64 主 64 备、负载均衡与无全网 WAL 复制。
- **阶段 E**：隔离 Demo 10/50/200 模拟客户端各 ≥5 min、Burst 2–3 倍 5–10 min、写入中 SIGKILL/ZK 失联/断网、P99 ≤30ms 及有审计的 ACK 不丢/不重复/不双主；随后逐步接入 Trade、Order、MD。
- 实验需多 JVM、多 WAL 卷、真实 ZK；同一 Mac 不是独立物理故障域。正式生产可靠性仍需多物理节点故障测试。
- 本地提交/本地构建优先，不触发 GitHub Actions，不擅自清理在用数据或更新正式 Docker。

- 从更新后的 Common 本地 Maven 产物重新运行独立 Demo 全量回归：**35 suites / 132 tests / 0 failures / 0 errors / 1 skipped**（131 项实际通过），Maven 退出码 0；验证规划器的新增代码没有破坏现有 Demo 编译/WAL/Netty 回归，但不能推导 HA/性能已通过。
- 可独立重放的 Common 改动补丁已保存到 `tests/patches/common-rf2-buddy-planner-20261023.patch`；从 `06c650e` 导出，并对当前 Common 树通过反向应用校验，便于后续会话在统一源码上复现。

**放行状态：目前仍 NO-GO。纯初始规划测试 ≠ 真实主切通过；两节点成对放置的性能优化必须单独测量。**


## 8. 第一阶段实际实现与回归记录（2026-10-23）

- Common 本地隔离分支 `feat/common-durable-wal-quorum-20261022` 提交 `06c650e`：新增纯 `PartitionBuddyPlacementPlanner`，只返回不可路由的 `PREPARING` 初始分区建议；不修改现网 ZooKeeper / WAL 或旧分区。
- `PartitionBuddyPlacementPlannerTest` **7/7 PASS**：2 节点 128/128、4 节点 64/64、6 节点 42–43、每分区仅一个配对 Replica、异常配置拒绝、禁止覆盖已有分区、节点/服务身份校验。
- Common 全量 Maven（新增规划器后）**94 suites / 395 tests / 0 failures / 0 errors / 0 skipped**，退出码 0。存在旧 `./control/ATSConfig.ini` 不存在的测试环境堆栈输出，但 XML 统计及退出码均正常。
- 此阶段**没有**完成线上 256 个分区的 ZooKeeper Assignment 发布、业务 WAL 分布、2→4 迁移，也没有证明 B 在 A 故障时 READY。以上必须列入下一阶段独立 Docker 测试，不能将规划器 PASS 说成 HA PASS。
- 方案文档本地提交 `36da560`（`saas-crypto`）；Common 源码本地提交 `06c650e`；本阶段未运行 GitHub Actions。

## 9. RF2 单幸存副本的受控接管准备（2026-10-23）

- Common 本地提交 `0946323`：`PartitionFailoverController` 在明确配置 `minimumLiveSynchronizedReplicas=1` 时，允许原 RF2 仅剩的同步 Replica 在租约有效、旧主失效、`PromotionSafety.requireSafe` 证明可信提交边界通过后，执行新 Epoch / Assignment CAS。原 RF3 只剩一个同步副本仍拒绝提升。
- **结果为 `APPLIED_NOT_READY`，Assignment 状态为 `RECOVERING`，不可路由写入。** 新主的 Replica 列表为空，旧主作为 Learner 保留；不伪造存活的备机，不把严格 RF2 2/2 ACK 降为单节点成功。
- 新增 `PartitionRf2SurvivorFailoverTest` 9/9 PASS，覆盖合法接管、旧主存活、丢租约、未证明提交水位、CAS 冲突、失去备机、RF3 多数不足、严格 ACK 拒绝、恢复中禁止反复升任。Common 全量回归 **95 suites / 404 tests / 0 failed / 0 errors / 0 skipped**。
- **下一阶段尚缺**：从 `RECOVERING` 经过真实 WAL/旧 Epoch 已确认提交水位/旧主 Fencing/持续授权核验的恢复事务，再按明确的 durability 合同安全发布 READY；独立 Demo 真实 A→B→A 自动切换尚未通过。不能把单元测试或控制面 CAS 当作完整 HA 通过。

- 新 Common 本地 Maven Jar 已安装并被独立 Demo 全量回归使用：35 个套件，共 132 项，131 项通过、1 项跳过、0 失败、0 错误，退出码 0。这证明编译和单测兼容，不代表真正自动 HA 已通过。

## 10. RF2 恢复完成门禁（2026-10-23，本地实验）

- Common 本地分支提交 `ca6f1d5`：新增业务无关的 `PartitionRf2StrictReadyController`。先对 `RECOVERING` 旧成员配置执行只读准备，再在业务写入互斥屏障内核对控制面租约、Assignment 版本、旧主作为 Learner 的在线/追平证据和严格提交安全门禁；资源关闭成功后，才尝试 ZooKeeper CAS 将旧主重新作为 Replica、版本递增并发布 `READY`。
- 控制器通过 `RecoveryProof` 接口注入旧 Epoch 已 ACK WAL 证书、候选 WAL 前缀、旧主 Fencing、新 Epoch 授权、备机追平等权威证明；**目前只提供门禁和模拟证明测试，还没有将其与真实 Demo WAL 证明/物理 ZooKeeper 实例接线**。生产适配器禁止无条件通过或返回伪造认证结果。
- 对旧 Epoch/Assignment 版本变化、恢复备机不在线、租约过期、提交证据不充分、CAS 冲突、恢复资源关闭失败等场景 fail-closed；CAS 已成功但随后租约失效的场景返回 `APPLIED_NOT_READY`，不发布本地写入就绪。
- RF2 严格 2/2 下：A 故障后 B 可获得新的非路由 `RECOVERING` Epoch，但只有 A 恢复并持久追平、恢复为有效同步 Replica 后才可按严格 2/2 重新 READY；故障期间如果希望 B 单节点持续交易，须走**显式 LOCAL_DURABLE_ASYNC/降级合同**及其独立认证门禁，不得自动从严格多数降级。
- 测试：`PartitionRf2StrictReadyControllerTest` 14/14 通过；Common 全量 **96 suites / 418 tests / 0 failures / 0 errors / 0 skipped**；重新本地安装 Common 后独立 Demo **35 suites / 132 tests / 0 failures / 0 errors / 1 skipped**（131 项通过）。都不构成真实 A→B 自动交易继续的证明。
- 下一阶段必须接入真实 ZooKeeper 的独立 Controller/Assignment 事务和真实 Common WAL/提交边界验证；然后运行 Docker 多 JVM A SIGKILL→B 无双主接管、A 回归追平、READY、持续业务写入和错误路径故障注入。

## 11. 2026-10-23：v19 真实 Docker 自动 RF2 Epoch 接管准备 PASS

**本轮真实实验**：在原 v19 custody 试验之外另建 `compose.v19-rf2-auto-stage.yaml`（独立 3 ZooKeeper、A/B JVM、WAL 与专用网络），明确配置 `DEMO_V19_RF2_AUTO_STAGE=1`。实验运行在同一 Mac/Docker VM，只证明 JVM、卷与 ZooKeeper 的独立模拟，**不是多物理节点故障域验收**。

- 新增 `DemoV19Rf2AutoStage`：真实数据 JVM 通过自己 ZK Session 注册 EPHEMERAL 成员；Common `ZkPartitionFailoverRuntime` 自动申请控制租约、监听成员消失并运行 `PartitionFailoverController`。每个故障分区先严格核验候选旧 Epoch 的已 fsync WAL 和 `DurableWalCertificateCustody.highestVerified()` 的可信 2-voter 签名证书；独立控制面 CAS 之后只产生 `RECOVERING`，不允许写入。旧 ZK 会话失效后才有资格接管，**不是脚本直接切主**。
- 额外修复 v19 就绪线程：ZooKeeper grant 失效时主动 `PartitionReadinessGuard.revoke()`，不再保留旧 epoch 本地 READY bit。每笔严格 ACK 合同仍不变。
- 在新隔离实例中真实 Netty 请求 `rf2-auto-stage-before-kill-{1..8}` **8/8 成功，appliedCount=1**，A Epoch 1 CommitIndex=8；B 证书验证旧 epoch=1，`certifiedSeq=8`，有 2 个旧 WAL 投票，提交 SHA256=`446b1b495224af34023a4d551ca38a4243a7199b0e8bea19e26027edf401f699`。
- **SIGKILL A 后未运行升主脚本**。等待约 18 秒跨过 ZK 会话检测后，B 日志自动输出 `V19_RF2_AUTO_STAGED partition=P000 old=CommonHaDemoA candidate=CommonHaDemoB newEpoch=2 state=RECOVERING writeAdmission=DENIED`。
- 直接从 ZooKeeper `harness/assignments/P000` 读取真实持久状态：`primary=CommonHaDemoB,epoch=2,assignmentVersion=2,state=RECOVERING,replicas=[],learners=[CommonHaDemoA]`；B 写入 `rf2-no-strict-after-auto-stage` 得到 503，**没有违规确认单份数据为 2/2 成功**。
- 用 Docker 原生启动原 A 容器（保留其原 WAL）后，A/B `committedSeq=8`，已确认 SHA 相同，均 `clean=true`，A/B 都没有 Epoch 1 或 Epoch 2 可写 grant；A 旧 Epoch 写入得到 503。ZK 仍保持 B/Epoch 2/RECOVERING，自动接管事件只发生 1 次，没有旧主自动抢回。
- Demo 全量 Maven：**35 suites / 132 tests / 0 failures / 0 errors / 1 skipped**（131 项通过）；真实验证在新 Compose 上完成，无正式 Order/Trade/MD 容器替换，没有使用 GitHub Actions。
- 本轮 v19 源码及 Compose 变更保存在 `tests/patches/common-v19-rf2-auto-stage-real-zk-20261023.patch`，已通过目标 v19 工作树 `git apply --reverse --check` 校验；Common 控制核心来自本地 `ca6f1d5`。

**放行边界**：本轮实现和验证的是 **自动选主 + 旧主 Fencing + 非路由恢复状态**，不是自动 `RECOVERING → READY` 或双向连续交易。v19 的 `DemoV19DurableRuntime` 仍把签名数据成员固定到 A/Epoch1，尚未有 Epoch2 动态成员与恢复证明安装；A 重启后虽然 WAL 与 B 一致，但不能自动成为 B 的严格 Epoch2 Replica，也不能恢复写入。下一步集中解决这条真实链路：动态持久成员 Epoch、Learner 追平/原始尾部隔离、新配置 2/2 可信提交边界、READY 原子发布、A/B 角色轮换多次故障；然后再做 256 分区和性能压测。当前仍 **NO-GO**。

- 证据保存完成后为避免占用同一台 Demo Mac 的 CPU/RAM，**仅停止** `otc-common-ha-v19-rf2-auto-stage` 隔离测试 Compose 的 A/B/ZK 容器；全部独立 ZooKeeper/WAL 卷及原容器仍在，没有执行 `down -v`。后续保留现有 `B/Epoch2/RECOVERING` 状态重启时使用 `docker compose -f compose.v19-rf2-auto-stage.yaml start`，不要重新运行只接受初始 Epoch1 的 bootstrap；如需全新验收，先有意识地保存证据再只重置该隔离项目。
- 停止实验后的正式 `dc-saas-ordersvr`、`dc-saas-tradesvr` 仍正常运行；原 `otc-common-ha-v19-rf2-custody-pilot` A/B 原实验容器未停止。Mac 磁盘剩余约 22 GiB（95% 使用），不宜无约束启动重复压测容器。


## 12. RF2 自动降级单节点继续交易（产品方向修订与真实验收）

**业务目标**：故障切换后必须继续正常交易，不能因为备机缺失长期 503。此项修正覆盖本文件早期“B 需等 A 追平才可写”的历史实现判断：旧严格 2/2 合同不能单机继续，但要通过**显式改为新的持久化合同**达到高可用目标。

- 正常期：A/B 两副本确认（旧 Epoch1 `QUORUM_DURABLE_SINGLE_HOST_TEST`）；A 被强杀、ZooKeeper 确认旧成员失效后，B 独立核验 `DurableWalCertificateCustody` 已 fsync 的旧 2/2 certificate、WAL 完整历史 SHA 与最大 ACK 序号，拒绝未经认证尾部；Common 通过 ZK CAS 进入 B/Epoch2/RECOVERING。
- **自动继续服务**：明确配置 `DEMO_V19_RF2_AUTO_DEGRADE=1`，隔离旧租约的保护窗口后，再以 ZK Assignment 版本 CAS 原子发布 `state=READY, primary=B, epoch=2, replicas=[], durabilityPolicy=AUTO_DEGRADED_LOCAL_DURABLE, quorumDurable=false, degradedFromCertifiedSeq=8`。数据平面必须再次持有当前 Epoch2 的可撤销短 TTL grant 才能写；每次 ACK 用 Common `DurableWalLocalAckGate.requireLocalDurable()` 校验 B 本地 forced WAL 及当前授权。
- 降级期间客户端 ACK 返回 `durabilityMode=AUTO_DEGRADED_LOCAL_DURABLE`, `quorumDurable=false`, `autoDegradedRf2=true`, `possibleDataLossIfPrimaryPermanentlyLost=true`。业务继续执行，**B 若永久损坏且旧 A 未追上，Epoch2 期间已 ACK 的 WAL 可能丢失**，不可标识为 2/2 零丢失。
- ZooKeeper 多数失联、grant 超时、旧主 fencing 尚未成立、旧可信 WAL 头与当前前缀不一致或存在未经认证脏尾时，必须 503；这是防双主/防丢已确认数据的真正安全边界。ZK 多数恢复后同一 Epoch 被撤权的本地 grant 仍不应直接复活，下一项任务是通过合法新 Epoch 自动重新授权。
- 当 A 返回时，它只能先成为 Learner：先追平 B 降级期间的所有已 ACK WAL、校验快照/原始尾部/请求去重，再将 A 升为 B 的 Replica 并恢复双副本确认。**这一步尚未实现**，因此现在不能承诺第二次 B 故障能无损切给仍落后的 A。

### 2026-10-23 两轮 Docker 真实观测

| 验证 | 结果 |
|---|---|
| 原隔离试验原有 seq 8、B 自动 Epoch2 READY 后本地写入 | seq9 ACK 成功；重复 requestId 仍 seq9，appliedCount=1；后续 seq10；重启 B 从 WAL 恢复 seq10 后继续 ACK seq11 |
| 丢失 3 ZK 中 2 台节点的多数 | B 在 grant 失效后返回 503，PASS（不允许同 Epoch 无仲裁持续写） |
| ZK 恢复多数后的原进程同 Epoch 自动重授 | **FAIL/未实现**，旧 revoked grant 不允许凭网络恢复偷偷续发，需要显式新 Epoch 机制 |
| 新建 `compose.v19-rf2-auto-degrade-e2e.yaml` 独立实例 | A/B+3 ZK 与原试验完全分离，原双节点 8/8 严格 ACK，全部 appliedCount=1 |
| 新实例真实 SIGKILL A，无人工改 ZK | B 自动发布 Epoch2/RECOVERING，再自动发布 Epoch2/READY 单节点本地持久化模式 |
| 新实例故障后首轮 TCP ACK | 在故障检测+安全隔离窗口约 17 秒时曾返回 503；数秒后重试成功，seq9，Epoch2，`quorumDurable=false`。切换中短暂拒绝可以接受，但**不能长期拒绝**；故障恢复耗时尚未达到低延迟目标 |
| 新实例 A 重启后旧主写入 | 503 拒绝，A seq8，B seq9；没有双主，**A 自动追平仍未通过** |
| Demo 全量 Maven | 36 suites / 138 tests：**137 通过，1 跳过，0 失败，0 错误**；包含新的 RF2 降级策略校验单测 |

**代码与配置复现**：之前自动 Epoch staging 基础补丁 `tests/patches/common-v19-rf2-auto-stage-real-zk-20261023.patch`；本轮后续代码和 Compose 增量补丁 `tests/patches/common-v19-rf2-auto-degrade-local-20261023.patch`（经 `git apply --check` 与应用内容逐文件验证）。本轮只更新了独立 Demo，尚未将新的持久化模式正式抽成 Common 的统一可配置策略；正式 RF2/Order/Trade/MD 以及多物理节点验收保持 NO-GO。

**下一关（按顺序）**：A Learner 从 B 的 Epoch2 ACK 尾部自动追平 → ZK 恢复 2/2 的新配置与 READY → A/B 双向多次 SIGKILL 仍能继续交易 → ZooKeeper 仲裁恢复后的合法新 Epoch 自动重授权 → 256 分区 / 4 节点 / 压力测试。性能重点是降低当前十余秒的故障检测和旧授权等待，而不能缩短到双主的风险窗口以下。

## 13. 自动 Learner 追平：B 单节点期间确认的 WAL 自动补到 A（2026-10-23）

- 本轮已通过真实隔离 Docker 验证：使用 compose.v19-rf2-auto-degrade-e2e.yaml 保留的 ZooKeeper Epoch2，B 为唯一可写 Primary；A 曾落后 B 已确认的降级 WAL。新环境参数 DEMO_V19_RF2_AUTO_LEARNER=1 允许原 A 以真实 ZooKeeper Learner 身份启动自动 Netty WAL 镜像拉取；无需人工复制数据或修改 ZooKeeper 主节点身份。
- 复用 DemoV19TcpSnapshotReceiver 的有界分块全镜像 SHA256、Epoch/提交序列/状态摘要校验。独立回放候选 WAL，并检查 A 已确认 requestId/序列/载荷构成 B 新历史的前缀，拒绝孤儿和分叉。新镜像安装前再次核验 B 仍是 Epoch2 READY 主、A 仍是 Learner，fsync 封存 A 原始 WAL、持久审计记录 activated=false，再进行原子文件替换、目录 fsync 和回放。A 始终不会因复制得到写权限。
- 首轮 A 原 seq8，B 已确认 seq10，A 后台自动追到 seq10；两者 epoch2、clean=true，WAL SHA 相同。随后 B 再本地 fsync ACK seq11，A 又自动追平 seq11，双方 SHA=88f63745f691664aefce74f3acca53419c43e5949dd1fbda9d67254417da250e，A 日志两次输出 V19_RF2_LEARNER_CAUGHT_UP。
- A 重启后独立回放 seq11 / epoch2 / clean=true，仍不具备主节点写入授权；测试 A 的旧主写入返回 503，防止双主。
- 新增 DemoV19Rf2LearnerInstallTest 4/4 PASS，覆盖正确追平、旧提交历史分叉、安装前成员证明失效、伪造全镜像哈希。隔离 Demo 全量 Maven：37 suites /142 tests，141 通过、1 跳过、0 失败/错误。
- 本轮源码、全量镜像试验及新配置增量补丁保存为 tests/patches/common-v19-rf2-auto-learner-catchup-20261023.patch，已验证在临时重建树 git apply --check、apply 和逐文件内容一致。
- 性能边界：仅 P000 且每次最多 16MiB WAL 镜像；全量复制、每轮封存原始 WAL 属于阶段性可靠性试验，不可直接推广到 256 分区。生产仍需 Common 的原始 WAL 区间增量续传、差量 Snapshot/Diff、自动归档删除与 CPU/IO 压测。

**剩余 NO-GO**：A 只是 Learner，还未通过 ZK 原子配置变更成为 B 的有效同步 Replica；B 当前 ACK 仍标记 AUTO_DEGRADED_LOCAL_DURABLE，不能声称恢复 RF2 2/2。下一步要建立写入屏障/最高已 ACK 边界/新 Epoch 与配置 CAS 的切换事务，将 A 转为 Replica、恢复定向 WAL 复制与累计持久 ACK，再 SIGKILL B 验证 A 自动接管及继续交易。ZK 仲裁恢复后的自动新 Epoch 重授权、256 分区及真实多物理节点压力测试亦未验收。

- 故障测试结束后核对 A 的持久恢复证据：.rf2-learner-evidence 下实际存在 **2 份旧原始 WAL 归档和 2 份 receipt**，对应 seq10 与 seq11 两轮自动追平，未直接删除/覆盖无法审计的原始尾部。为降低同一 Mac 压力，本轮仅将 otc-common-ha-v19-rf2-degrade-e2e 隔离项目容器 stop，保留原 ZooKeeper/WAL 卷，正式 Order/Trade 容器未动，磁盘剩余约 21GiB。
- **恢复操作注意**：此隔离项目已处于 B/Epoch2 配置，不能再次运行仅接受全新 Epoch1 的 bootstrap；它会因 Assignment 不符安全退出，属于预期行为。继续验证时直接 start 三个 ZooKeeper 与现有 A/B（或以 --no-deps 重建独立节点），不要用普通 up 强制重复 bootstrap，更不要 down -v。上线前应补可重入的“只读校验当前配置”启动路径。

## 14. 2026-10-23：RF2 自动双向切换 Epoch1→2→3→4 验收

**本节为最新隔离实验结论**，覆盖上方早期只完成 Epoch2 的旧状态。仅 Mac/Docker 中 Common v19 的 P000，三 ZooKeeper 和两个独立 JVM/WAL；不等于生产 Order/Trade 或独立物理故障域验证。

| 场景 | 真实结果 | 判定 |
|---|---|---|
| A Epoch1 / B Replica | 原 RF2 严格 2/2 8/8 ACK | PASS |
| SIGKILL A | B 经 ZK 自动切为 Epoch2/READY，并本地持久化 ACK | PASS |
| A 以 Learner 回归 | A/B WAL 一致，B 可继续交易 | PASS |
| SIGKILL B | A 经 ZK 自动切为 Epoch3/READY，本地 WAL 写入 seq13，code=0，appliedCount=1 | PASS |
| B 作为 Learner 回归 | B 自动追到 seq13；A 再写 seq14 后 B 自动追平，A/B SHA 一致 | PASS |
| 再 SIGKILL A | B 经 ZK 自动切为 Epoch4/READY；seq15 写入 code=0，appliedCount=1 | PASS |
| A 重新以 Learner 回归 | A/B 都是 Epoch4、seq15、Clean，SHA256 同为 94172373ceaeae2ada0f183f3e43d2af68629444a413f7a6bf8a4e8f254a3816；A 写入拒绝 503 | PASS |
| Epoch4 关闭 ZooKeeper 3 节点中的 2 节点 | B 停止确认写入，返回 503，没有无仲裁双主 | PASS |

以上真实切换的主节点/Epoch/READY 均由隔离 JVM 内 ZooKeeper 协调器自动 CAS；实验命令只做 SIGKILL、启动容器、业务请求与取证，未人工写入 ZK Assignment。切换存在秒级会话检测与旧授权隔离窗口，不能宣称零停顿。

### 实际修复问题

1. 将隔离 Demo 的本地持久化确认、就绪守卫与双向 Learner 自动复制扩展为 Epoch2–8 的有界模式，严格要求 ZK 控制授权、原主成员失效、候选洁净 WAL 覆盖 Epoch1 经多数证明的已 ACK 前缀；新主先进入 RECOVERING，延迟隔离旧授权后才 READY。每次记录 candidateDurableSeqAtPromotion 和 previousEpochMayHaveUnreplicatedAcks=true。
2. 解决恢复镜像原子替换 WAL 后，旧证书验证回调引用已经关闭的 Journal 对象，导致真实 Epoch3→4 候选拒绝的问题；现在重新读取 Catalog 中当前已打开的 WAL，仍需核验旧签名证书和已确认前缀，并未跳过校验。
3. 双向 Learner 无需脚本直接复制文件：Netty 有界镜像传输、完整 SHA256/提交序列/状态摘要校验、原旧 WAL fsync 归档、独立 WAL 回放、ZK 成员版本复核、原子安装。归档和传输模型还不是生产级增量 WAL/Diff。

### 验收边界及重放源码

- Demo Maven 完整回归：37 suites / 143 tests / 0 failures / 0 errors / 1 skipped（142 通过）。
- 本轮修改后的 9 个 Java 源文件快照：tests/patches/common-v19-rf2-epoch4-rotation-source-20261023.tar.gz；对应逐文件 SHA256：tests/patches/common-v19-rf2-epoch4-rotation-source-20261023.sha256。快照已解压逐文件比对确认一致。**该文件是源文件快照而不是独立增量 patch**；使用时应先确认前面三轮 v19 补丁和工作树差异，不能无审核覆盖其它代码。
- **当前全部 Epoch2/3/4 新写入均为 AUTO_DEGRADED_LOCAL_DURABLE，quorumDurable=false**；还没有把追平的 Learner 正式恢复为 Replica，也没有动态安装 Epoch2+ 的真实双副本签名/提交合同。下一阶段必须修复 Common 正式新配置切换（写屏障、提交水位证明、ZK CAS、复制 ACK 批量和动态成员），不能将两个节点 WAL 一致等同于严格 2/2。
- 本地单副本期间存在 RPO>0 风险；任何被选中新主缺少前任单机期间已 ACK WAL 的情况不得冒充零丢失，已将 possibleDataLossIfPrimaryPermanentlyLost=true 返回客户端。
- 当前仅 P000 单机隔离试验，不代表 256 分区、2→4 节点各 64 主、Order/Trade/MD 资金持仓一致性、真实多物理节点、TPS/p99、ZooKeeper 仲裁恢复后的新 Epoch 自动重新授权都已通过。正式 HA 仍 NO-GO。

## 15. 2026-10-23：RF2 双副本恢复真实预检与新 Epoch 双签名 Genesis

**本节覆盖上一轮 Epoch4 结论之后的增量进度；这次没有开启严格 2/2 ACK。** 新目标是：A/B 自动主切并恢复 Learner 后，必须先真实验证两个物理 WAL 的相同已提交前缀和旧签名证书，再在新 Epoch 通过独立 RSA 双签名构建持久可审计的 Genesis，最后才能发布新配置的严格 ACK。

### 本轮实际交付

1. **独立 Demo read-only 预检**：新增 DemoV19Rf2StrictRejoinPreflight + DemoV19Rf2StrictRejoinProbe，并在 DemoV19Rf2AutoStage 增加低频可选预检开关 DEMO_V19_RF2_STRICT_REJOIN_PREFLIGHT=1。由真实 ZooKeeper 当前 Assignment（Primary/Learner、版本、Epoch、持久化合同）和两个独立 JVM 的 Netty status 构建证据：双方 committedSeq、WAL prefix SHA256、stateDigest、distinctRequests、clean 必须完全一致；TCP 声称物理身份必须与目标匹配。使用 DemoV19TcpClient.custodyHeadEvidence 分别验证两台的旧 RF2 两签名 Certificate（旧 Epoch1 已 ACK frontier）且证书序列/哈希一致。之后重查 ZK 控制多数、成员存活、Assignment version 与 durabilityPolicy。任何错误只拒绝预检，不改变旧 degraded 交易可用性；**读一致性快照不是写入屏障和提交事务**。
2. **实际测试**：原隔离 Docker P000 因 B JVM 重新创建，控制器真实执行了另一轮自动角色转换至 A/Epoch5/B Learner。两份物理 WAL 都处于 seq15 / 最后数据 Epoch4，没有 Epoch5 新 WAL。这种“ZK Epoch 已上升但还没有本 Epoch 新 WAL”不构成丢单，修复预检允许最后数据 Epoch 不大于当前控制 Epoch，仍必须双方 Epoch 相同、历史哈希相同。实测独立只读命令返回 RF2_STRICT_REJOIN_CANDIDATE epoch=5 seq=15。随后向 A 真实写入 seq16 code=0，B 自动追平到 seq16；两台 SHA256=3192d2900d54b46d58cd0205642cea180fdbe335c8ae61cb2937e9c89bdcb0fa，第二次只读命令返回 RF2_STRICT_REJOIN_CANDIDATE epoch=5 seq=16，ZK version=8，Old 2-voter RSA cert 独立验签通过。客户端 ACK 仍标记 AUTO_DEGRADED_LOCAL_DURABLE / quorumDurable=false。
3. **Common 新 Epoch 双签名账本 Genesis 可行性实测**：新增 DurableWalRf2RejoinGenesisTest，证明完全独立的物理 RSA A/B 两份新 Epoch6、配置版本9 签名，可以先在原 WAL seq16 上建立新的 DurableWalCommitIndex fsynced certificate，然后 seq17 可连续持久认证和重启恢复。单节点签名、旧 Epoch5 签名、过期主授权都不能生成或发送 QUORUM_DURABLE 结果。**这是 Common 状态机/签名器的 JVM 单元级验证，尚未接到真实 ZooKeeper CAS 与数据 Netty Epoch6 双签名 RPC。**
4. **回归结果**：Common 97 suites /419 tests /0 failures /0 errors /0 skipped，源码本地提交 2c67699；Demo 38 suites /153 tests /0 failures /0 errors /1 skipped（152 通过）。真实 A/B 的恢复预检另外经过 Docker/ZK + TCP 验证。

### 证据/局限

- 回放型 v19 增量补丁：tests/patches/common-v19-rf2-strict-rejoin-readonly-preflight-20261023.patch；从上一轮 Epoch4 Java 快照和 Compose 差分生成，已在临时重建目录通过 git apply --check / apply / 六文件逐字节内容比对。
- Common 双签名 Genesis 专项源码补丁：tests/patches/common-rf2-rejoin-genesis-certification-test-20261023.patch；已对当前 Common 工作树做 git apply --reverse --check 验证。
- 下一项不可跳过的真正集成：**原 Primary 单机 ACK 业务屏障（锁定最高已 ACK WAL） → 两节点独立确认完整前缀 → 创建下一 Epoch 的新主/备配置与双独立签名器 → 原子 ZK 配置发布及 fencing → 开启新 Epoch 数据 WAL 定向复制 → 首份新 Epoch 2/2 持久 Genesis 和真实每笔 ACK → 旧主/failover/崩溃重启多轮验收**。旧严格签名服务仍固定 Primary A/Epoch1；预检仅意味着“具备进入切换事务的候选条件”，不能把它作为 READY/2of2 证书。
- 预检是低频控制面任务，正常下单不额外读取 ZooKeeper/证书；为避免 256 分区下大量控制调用，规模化时应以分区水位变化和批量控制事件触发，不可简单把 P000 的 12 秒轮询复制 256 份。
- 以上均为隔离 Demo Mac 单物理宿主的独立进程测试，不代表 RF2 多物理 AZ 无损、Order/Trade 资金持仓一致性或 200 租户压测完成。整体严格 2/2 恢复仍 NO-GO。

## 16. 2026-10-23：动态 Epoch WAL RSA 签名 Netty 服务接线（仍未切回严格 2/2）

接续第 15 节的两节点只读 preflight 和 Common 双签名 Genesis 单元回归，本轮实现了新的 **DemoV19Rf2DynamicReceiptService**（独立开关 DEMO_V19_RF2_DYNAMIC_RECEIPT_PILOT=1），在原 v19 独立 Common Netty socket 内增加 V19_RF2_DYNAMIC_DURABLE_RECEIPT_V1。它只签**一个物理节点已 fsync WAL 前缀**，绝不单凭一个响应授权新 Primary、发布 READY 或承诺客户端双副本 ACK。

- 成员/epoch/配置权威只能来自真实 ZooKeeper majority session + 带 stat version 的 P000 Assignment。调用方提供的 28 字节原有 Common Receipt 二进制负载（版本、配置版本、Epoch、序列）只能进行**相等性核验**，不能指定任意 Primary 或 signer。服务端构造带两个不同 RSA 公钥、不同故障域标签（Mac 单宿主模拟）的 Common DurableWalCommitQuorum.Membership，通过 DurableWalReceiptControlHandler 真正签名；签名前后分别核对 ZooKeeper 的 Assignment 版本和成员身份，若变化拒绝。每次从当前 JournalCatalog 获取 WAL，避免 Learner 替换后引用旧已关闭文件。
- 可接受配置只有：① state=RECOVERING，durabilityPolicy=STRICT_REJOIN_GENESIS_PREPARE，strictTransition=GENESIS_PENDING，quorumDurable=false，此时**只能签**冻结的 strictGenesisSeq；② state=READY，durabilityPolicy=QUORUM_DURABLE，strictTransition=GENESIS_CERTIFIED，quorumDurable=true，并拥有单一指定 Replica，此时才可能为本 Epoch 新数据签名。
- 两种情况还必须具备明确 strictConfigurationVersion、严格 Genesis seq/hash、历史已认证 strictOldCertifiedSeq/hash；所有物理 WAL 必须 clean、fsynced、覆盖历史 old ACK 哈希，并和当前 Genesis 匹配。后续普通严格数据必须在新 Epoch 写入。服务端不信任请求中的配置，不承认额外节点/旧主过期凭证/不一致历史。
- 接入代码：DemoV19TcpService、DemoV19ClusterHarness、DemoV19TcpClient；增量补丁保存在 tests/patches/common-v19-rf2-dynamic-epoch-receipt-20261023.patch，已在独立重建目录通过 git apply --check、apply、6 文件逐字节比对。新增 DemoV19Rf2DynamicReceiptServiceTest **7/7 PASS**，涵盖准备态、严格激活态及错版本/别名/缺失/额外成员/伪造哈希/单节点提前认证等拒绝条件。
- **真实 Docker 反向测试**：原隔离项目 ZooKeeper 仍为 A/Epoch5/READY/AUTO_DEGRADED_LOCAL_DURABLE、B Learner，调用新 TCP 动态签名 opcode（提出 Epoch6/config10/seq16）被 B 正确拒绝：missing numeric strictConfigurationVersion。证明新 RPC 不会从单节点降级态擅自发放严格持久证明。恢复当前业务单机 WAL 模式继续真实写入 seq17，code=0/appliedCount=1/quorumDurable=false；B 自动追平 seq17，A/B 完整 WAL SHA=b851cc2a0a7c986fcb2ad1af85f80b97a908045f166b27fd0eedc1aad18c640b。
- 本轮 Demo 全量 Maven **39 suites /160 tests，159 通过、1 跳过、0 失败/错误**。Common 源自上一轮的全量 419 PASS，本轮未修改 Common 工厂主代码。
- **下一关仍未完成**：有界写屏障阻止单节点本地 ACK、冻结最高已确认 Seq、原子 ZooKeeper 进入新 Epoch RECOVERING/strict GENESIS_PREPARE、收齐 2 个独立 Netty Receipt、落盘 Common CommitIndex + 将证书保管到第二节点、原子发布严格 Ready 并切换真实订单写入 ACK/恢复正式复制。每个条件未成立不得报 QUORUM_DURABLE，也不能长期牺牲 A/B 正常单节点可用性。此协议暂不启用自动切换，仅可显式隔离试验；正式 Order/Trade/MD 集成、256 分区、多物理节点故障以及 200 租户压测仍为 NO-GO。

## 17. 2026-10-23：真实 ZK Freeze → Genesis Prepare → 双签名 CommitIndex fsync

本轮在全新隔离 Compose 项目 compose.v19-rf2-strict-cutover.yaml 中验证，3 个独立 ZooKeeper 进程、A/B 独立 JVM 与独立 WAL 卷，均在同一台 Mac Docker VM 内。原有实验与正式 Order/Trade/MD 服务未更改。

真实实验依次执行：Epoch1 A 主/B 备，8 笔请求获得原严格 2/2 ACK（8/8 code=0、appliedCount=1）；SIGKILL A，B 自动取得 Epoch2/READY，B 在单节点本地 fsync 模式确认新 seq9；A 作为 Learner 恢复后自动追平 B 的 WAL。B 的严格恢复自动线程随后调用两次真正的 ZK stat-version CAS：

1. 首次进入 Epoch3 / RECOVERING / STRICT_REJOIN_FREEZE_PENDING / quorumDurable=false，旧 Epoch 的主节点不可继续确认新写入。这个阶段**不能**请求签名或恢复 READY。
2. 等待超过 5 秒旧授权隔离窗口，重新从两台物理 JVM 读取 clean WAL、提交 seq、SHA、业务状态摘要和独立认证的旧 Epoch1 双签名证书；通过 Netty HASH_THROUGH(seq8) 再验证旧 ACK 的实际物理历史前缀。证明一致后第二次 CAS 进入 Epoch3 / RECOVERING / STRICT_REJOIN_GENESIS_PREPARE，严格两个指定节点、strictConfigurationVersion=5、strictGenesisSeq=9、strictOldCertifiedSeq=8，quorumDurable=false。
3. 新动态 WAL Receipt Netty RPC 分别获得 B 与 A 对 Epoch3/config5/seq9 同一 WAL 前缀的独立 RSA 签名。Common DurableWalCommitQuorum 校验 2 个物理签名，Common DurableWalCommitIndex 原子落盘与 fsync。真实 B WAL 卷中生成 /srv/v19/wal/.strict-epoch-3-config-5/commit-00000000000000000009.bin（1035 字节）。B 日志记录 V19_RF2_STRICT_GENESIS_FSYNCED epoch=3 seq=9 twoSignedPhysicalVoters=true clientStrictReady=false certificateCustodyPeer=false。
4. 反向测试：此时 B（新主）与 A（备机）收到新的真实 TCP APPEND 均返回 503，证明仍处于不可写 RECOVERING，未假称正式 2/2 ACK 已恢复。原自动降级 READY 定时线程被新状态守卫阻止，不能错误开放严格恢复中分区。

专项测试 DemoV19Rf2StrictCutoverPlanTest 7/7、DemoV19Rf2StrictFreezeAdmissionTest 4/4、DemoV19Rf2DynamicReceiptServiceTest 7/7 PASS；完整 Demo Maven：41 suites、171 tests、170 pass、1 skipped、0 failures/errors。

源码与隔离 Compose 精确 12 文件快照 tests/patches/common-v19-rf2-real-strict-genesis-20261023.tar.gz，附逐文件 SHA256 清单 tests/patches/common-v19-rf2-real-strict-genesis-20261023.sha256，已解压逐字节核对。快照不是独立增量补丁，须结合先前 v19 实验补丁谨慎合并，不可直接覆盖其它源码。

**仍为 NO-GO**：本轮只证明新 Epoch 两独立签名与 B 主节点本地持久化 CommitIndex Genesis；A 第二节点尚未持久保管新的认证证书、动态正式 WAL 复制及新 Epoch 严格客户端 ACK 未接通，因此没有发布严格 READY。该隔离实验目前停在安全但不可交易的 RECOVERING；切勿将自动严格恢复实验开关直接配置到已有 Demo/正式 Order/Trade，否则违反故障后保持交易可用的目标。后续必须补第二节点证书 fsync Custody、双副本持久 ACK、严谨的新配置 READY 和失败时自动降级恢复，然后做 256 分区和 200 租户压力测试。模拟故障域不代表两物理节点。

## 18. 2026-10-23：新 Epoch Genesis A/B 双独立保管及重启复核通过

继续第17节的独立隔离实验，保留 ZooKeeper Epoch3 / strictConfigurationVersion=5 / strictGenesisSeq=9 / RECOVERING / STRICT_REJOIN_GENESIS_PREPARE、B 主原有 1035 字节 Common CommitIndex 证书与 A/B 原 WAL。无需清空数据或修改 ZK Assignment。

1. 新 DemoV19Rf2DynamicReceiptService.handleCustody 及 Netty opcode V19_RF2_DYNAMIC_CUSTODY_INSTALL_V1 复用 Common 原有 DurableWalCertificateCustodyControlHandler / DurableWalCertificateCustody。凭当前 ZK 配置版本、Epoch3 的两 RSA 公钥和各自独立本地私钥，反复校验 seq8 旧严格 ACK 前缀及 seq9 新 Genesis；通过 Common 证书解析、两 RSA 签名验证、各自本地 WAL 真实 fsync，再执行 head.pending 强制落盘、原子更名 head.bin、目录 fsync。配置漂移、WAL 分叉、证书不一致均安全拒绝。
2. B 的 DemoV19Rf2StrictCutoverCoordinator.custodyGenesis 调用 A/B 两套独立 Netty 节点，收集并验证两份真实 signed custody reply，再用 DurableWalCustodyQuorum.verify 验证两不同物理成员的证书保管多数。Docker 日志：V19_RF2_STRICT_GENESIS_DUAL_CUSTODY_FSYNCED epoch=3 seq=9 custodians=2 clientStrictReady=false certifiedClientAck=false。A/B 各自 WAL 卷存有 /srv/v19/wal/.strict-custody-epoch-3-config-5/head.bin，每份 1018 bytes。
3. 实际重启 A/B 两个 JVM 后，B 从 ZK GENESIS_PREPARE 和持久化 CommitIndex 安全恢复，原子重复 custody 安装幂等。新增只读 Netty V19_RF2_DYNAMIC_CUSTODY_HEAD_READ_V1 使用 Common headQueryRequest/decodeHeadEvidence，各自重新装载和验签两份 head.bin：V19_RF2_STRICT_DUAL_CUSTODY_RESTART_VERIFIED epoch=3 seq=9 twoIndependentHeadFiles=true clientStrictReady=false。完全没有脚本覆盖物理 WAL 或直接修改 ZK 主身份。
4. Genesis 双保管后在 A/B 各测试一笔新业务写入，均返回 503，因为目前仍是 strict PREPARE 的不可写 RECOVERING；这是隔离实验预期，并非可用性上线达标。正式订单/交易服务不受影响。
5. Demo Maven 全量回归 41 suites /171 tests：170 PASS、1 SKIPPED、0 FAIL/ERROR。新 11 文件源码与隔离 Compose 快照保存在 tests/patches/common-v19-rf2-epoch3-dual-custody-restart-20261023.tar.gz，SHA256 清单 tests/patches/common-v19-rf2-epoch3-dual-custody-restart-20261023.sha256，已安全解压逐文件字节验证。此为源码快照而非独立增量补丁，不能直接覆盖其它尚未合并工作树。

**剩余不可省略：** 仍未把新 Epoch 的正式 PrimaryWriter 接到同步 B→A WAL 复制/逐笔双 fsync 收据、Common CommitIndex 与双保管持续更新。必须先证明这些真正交易链路能工作，再通过 ZK CAS 发布 READY/QUORUM_DURABLE，最后实测 A/B 故障自动降级单节点继续交易、恢复后重新严格 2/2。单机 Mac/Docker 进程分离不是多物理机验收；256 分区、200 租户负载及 Order/Trade/MD 一致性未执行。当前仅 Genesis 证书双保管与重启复验 PASS，整体严格双副本自动恢复 NO-GO；不能把自动 FREEZE 实验开关用于正式 Demo。

## 19. 2026-10-23：Epoch 5→6→7 严格双副本/单节点/严格双副本业务闭环实测

本节为第18节后的增量。所有结果只代表 Mac/Docker 单物理宿主、P000、A/B 独立 JVM/WAL、3 个 ZK 容器。未修改正式 Order/Trade/MD 服务，未触发 GitHub Actions。

**Epoch 5 严格交易**：初次新 Epoch3 seq10 写入仅完成 B 本地 fsync，客户端无严格成功 ACK；纠正 Epoch1/2-only 的后台复制重试条件与旧 signed-batch receipt 配置后，A 自动追平。随后 A 故障，B 自动切为 Epoch4 单节点。A 恢复，系统执行 Epoch5/config10 的 FREEZE、双物理 RSA Genesis seq12、Common CommitIndex fsync、A/B 证书双保管和严格 ZK READY。B 收到新业务 rf2-epoch5-real-strict-13，结果 code=0、appliedCount=1、seq13、quorumDurable=true、QUORUM_DURABLE；A/B WAL Epoch5 seq13 SHA256 同为 28939f654ff41a389382959b970d647f566c81ad6ceceb200241f99bc7632654。CommitIndex 证书 commit-00000000000000000013.bin（1092B）落盘，A/B head.bin（各1018B）的 SHA256 同为 6766ee70725e09cb0a8529704214eb258a75f6e68c1d8270406d705108fd6ce4。对相同 requestId+delta 再次调用仍返回同一 seq13、appliedCount=1，不重复应用。

**真实 A 故障后继续交易**：直接 SIGKILL A，B 自动通过 ZK CAS 切换至 Epoch6 / READY / AUTO_DEGRADED_LOCAL_DURABLE / quorumDurable=false，明确保留旧签名最高 ACK seq13。B 在缺少 A 的条件下接收 rf2-epoch6-degraded-solo-14，返回 code0、appliedCount1、seq14，明确 possibleDataLossIfPrimaryPermanentlyLost=true。A 重启后作为 Learner 自动追平 seq14（WAL 数据 Epoch6），A/B SHA256 同为 ac5a08169735ac4e9112bcd305578774ea7aac5fae4383e1b2d1eda26291dcf6。这种本地 ACK 合同在单机永久损坏时仍有非零 RPO 风险，不能称零丢失。

**再恢复 Epoch7 严格复制**：发现原试验控制器完成一次严格升级后停在 strictCutoverPhase=6，不能自动继续下一轮。新增 mayRearmStrictCycle 的版本/身份/状态/唯一 Learner 门禁，旧同 Epoch、旧主、双成员 READY、RECOVERING 等条件必须拒绝；5 项专项单测全部 PASS。本次为了载入修复后的字节码，先停止 A、重建 B 测试 JVM、再恢复 A，原 ZK/WAL 均保留。随后系统自动 Epoch7 FREEZE→GENESIS_PREPARE(seq14)→双签名、CommitIndex与 A/B 独立 Custody→ZK 严格 READY。再次向 B 发送 rf2-epoch7-strict-after-second-rejoin-15：code0、seq15、appliedCount1、QUORUM_DURABLE、quorumDurable=true。A/B WAL seq15、最后数据 Epoch7、SHA256 同为 6fbad707173967a89be802ecd9d0a5130fb9faa49459ab191448d4c2955bd145。Epoch7/config15 CommitIndex commit-00000000000000000015.bin（1092B）落盘；A/B 的独立 head.bin SHA256 均为 2b4fcc5d91486c2d0fb33f0af0f26d10d32da0943083a452f02d9f51b00f30bf。

**严格 ACK 代码**：DemoV19Rf2StrictAckRuntime 在每笔新 Epoch 成功响应前串行检查旧持久证书水位、Primary 本地 WAL fsync、Replica 真实同序列 WAL fsync/hash、两独立 RSA 收据、Common CommitIndex 签名证书 fsync、A/B 各自原子证书保管 fsync 和当前 ZooKeeper Assignment/fencing。任何错误不得返回成功。隔离 Demo 原先 Epoch1/2-only 的复制 retry 已修改，旧 batch hint 在动态签名路径中停用。客户端 ACK 仍含 ackProofMode=SEQUENCE_ONLY_FULL_AUDIT_REQUIRED，不代表生产资金/委托/成交/Projection 权威最终对账完成。

**测试与源码**：本轮 Demo 全量 Maven 为 43 suites / 181 tests，180 PASS、1 SKIPPED、0 failures/errors；新增重复重启恢复准入 5/5 PASS。精确 18 个 Java/Compose 文件源代码阶段快照：tests/patches/common-v19-rf2-dynamic-strict-recovery-epoch7-20261023.tar.gz，配套同前缀 .sha256 清单；已安全解压到临时目录进行逐文件字节核对。源文件快照不是独立增量 patch，不应未经差异审核覆盖其他工作树的修改。

**未完成**：这次 Epoch7 是重建 B JVM 后恢复，不能声称不重启 JVM 的反复自动 rearm 已完成。当前实验仍有 Epoch2-8 上界和固定 P000，未进行本轮严格 READY 下 B 主被杀后 A 接管的独立链路验收、多物理故障域、256 分区/4节点、10/50/200 租户持续及 burst 压测、p99、Order/Trade/MD 金额持仓委托成交及 Projection 权威对账。结论应分级：隔离 P000 严格2/2 ACK→单节点继续交易→再次严格2/2 ACK 业务闭环 PASS；完整生产 Common HA 仍 NO-GO。

## 20. 2026-10-23：反向严格主切 B→A、Epoch9 真实严格 ACK 与高 Epoch 就绪门禁修复

紧接第19节的单机隔离 P000 Epoch7：B 主、A 备、双副本严格 WAL 已认证到 seq15。真实 SIGKILL B，A 的 ZooKeeper 控制线程首先进入 Epoch8 / RECOVERING，等待旧主租约隔离窗口；首次过早发新单正确收到 503。随后自动进入 Epoch8 / READY / AUTO_DEGRADED_LOCAL_DURABLE，A 主节点独立 fsync 新交易 rf2-epoch8-a-primary-solo-after-b-kill-16，响应 code0、appliedCount1、seq16、quorumDurable=false、possibleDataLossIfPrimaryPermanentlyLost=true。重启 B 后，B 自动作为 Learner 追平 A 的 seq16，A/B WAL 最后数据 Epoch8，SHA 都是 913c840e404c5da15a6ebdc7e26cd421810eb5b5ffaf5986e99c0bd3a7006842。

A 控制线程随后自动执行 Epoch9 / FREEZE → GENESIS_PREPARE(seq16) → 两独立 RSA 签名及 CommitIndex fsync → A/B 证书双保管 → ZK 原子严格 READY/QUORUM_DURABLE。初次向 A 发送新交易时发现一个真实回归：v19 harness 就绪线程仅检查 Epoch1-8，不会为 Epoch9 主机授予本地 readiness，因此返回 503。这不是签名证书缺失。修复后统一实验最大 Epoch 为 DemoV19Rf2EpochLimits.MAX_EPOCH=128，并修改一批关联代码（DemoV19DurableRuntime、DemoV19Rf2AutoStage、DemoJournalCatalog Learner 图像验证、DemoV19Rf2StrictRejoinPreflight 等），保证同一个上界，后续不能只增加写入侧而漏掉恢复侧。注意这个数字仍然是隔离实验保护上界，不等于生产 Common 必须限制为128。

**性能机制修复**：原 DemoV19ClusterHarness 在每次 35ms 就绪轮询及每秒一次 async retry 中循环检查 Epoch1..8。若简单把循环提升至128，会浪费 CPU。现在控制线程仅通过已经安装、TTL 控制的 DemoHotpathLeaseCache.view(P000) 读一次当前 Epoch，使用相同缓存验证该 Epoch 的 Primary grant；每个轮询周期 O(1)，不用访问 ZooKeeper 和历史 Epoch。源码已编译，并完成隔离 JVM 实测。

为了加载新字节码，仅重建隔离 A JVM（B 独立 Replica 持续保留原 WAL/ZK）。A 发 rf2-epoch9-a-primary-strict-after-epoch-limit-fix-17 时，首个 TCP 客户端 RPC 超时；服务端同时记录 seq17 的证书、local custody、remote custody 和 finalACK。**不能把超时本身视为成功**，使用**同一 requestId、同一 delta**从独立客户端重试，得到 code0、seq17、appliedCount1、QUORUM_DURABLE，确认无重复应用。随后 A 收到另一笔全新请求 rf2-epoch9-a-primary-strict-fresh-18，立即返回 code0、seq18、appliedCount1、quorumDurable=true、durabilityMode=QUORUM_DURABLE。A/B 物理 WAL 各为 Epoch9、seq18，完整 SHA256 同为 20b7893cd86b61799396018d66f1e87ed344a9f227113018fbca3ca0396cc1ae；两节点独立证书 Custody head.bin 的 SHA256 均为 674c98accf33e824b1968336e4ab9744d1bfbde51a7f1b8ed4c73db9f9501ad4；A 的 seq18 CommitIndex commit-00000000000000000018.bin 为1092字节。

最新 Demo Maven 全量回归：**43 suites / 181 tests / 180 passed / 1 skipped / 0 failures/errors**。20 个指定 Java/Compose 文件快照 tests/patches/common-v19-rf2-epoch9-bidirectional-strict-20261023.tar.gz，配套同前缀 .sha256 清单，经干净临时目录安全解压及逐文件字节相等验证。属于源码阶段快照，不是独立增量补丁；合并到其它仓库前还需差异审查。

本轮完整闭环覆盖两个方向：严格 B主→A备、B 存活单节点→恢复严格；严格 A主→B备、A 单节点继续交易→恢复严格。**没有**证明长期 p99 满足目标或可无限次滚动切换：目前仅单 Mac/Docker P000、有限 Epoch 的故障注入，新 Epoch 每次 RSA+证书双保管路径仍需性能优化；真实 Order/Trade/MD/Projection 权威对账和256分区/4节点/10-50-200租户压测未执行。初次 TCP 超时表明仍需重试策略与 ACK 超时指标验收。对所有 LOCAL_DURABLE 的单机确认必须继续明确 RPO>0 可能性。当前按阶段判定 P000 双向功能试验 PASS；生产级整个 Common HA 尚未最终验收。

## 21. 2026-10-23：256 分区 RF2 buddy 规划与磁盘安全回收

在 Common 本地分支 feat/common-durable-wal-quorum-20261022 提交 **786bdbc**，新增 PartitionBuddyPlacementLoadProbe 和 PartitionBuddyPlacementScaleTest，复用现有 PartitionBuddyPlacementPlanner，不另造选主或复制算法。256 分区下 2 个数据节点各主128/备128；4 节点各主64/备64，采用 A/B 与 C/D 两个独立互备组；8 节点各主32/备32。每个分区只向自己的 buddy 发送一条副本 WAL，不做全互连。新分区初始只标记 PREPARING，不得直接发布 READY；现存分区扩容必须走经过认证的 Learner/Genesis 迁移事务。

本机合成 CPU 规划测试（每种规模 256 分区，预热3次，采样40次）：
- 2节点：每节点128个主分区；规划中位1.815ms、p99 11.371ms；
- 4节点：每节点64个主分区；规划中位1.179ms、p99 4.867ms；
- 8节点：每节点32个主分区；规划中位0.791ms、p99 10.870ms。

以上是**一次生成256个初始分区方案的纯Java本地耗时**，不是订单p99、ZooKeeper延迟或实际TPS；40次样本只建立粗略CPU基线，不允许据此宣称真实4 JVM /256分区 HA验收完成。Common Maven全量测试 **98 suites /423 tests、0 failures/errors/skipped**，含新拓扑分组、每分区唯一备份、PREPARING不提前READY和非法池拒绝。控制台曾有缺失 ATSConfig.ini 的环境警告，最终JUnit/Surefire全部通过，正式集成仍应单独复核该环境差异。

磁盘：先核实容器均停止及Compose卷确属旧试验后，清理了两个早期 RF2 auto-stage 和 degrade-e2e 实验的容器及专属ZK/WAL卷；执行 Docker image prune -a 仅删除没有任何现有容器引用的镜像。严格 v19-rf2-strict-cutover 当前8个ZK/WAL证据卷保留，正式Order/Trade/MD与生产卷不改，未运行GitHub Actions。清理后Mac APFS仍报419/460GiB已使用、剩余12–13GiB（97–98%），表示未释放出足够真实宿主空间，**不能宣布磁盘容量问题已解决**，也不能运行危险的全局 volumes prune。

下一阶段应先为4个独立数据JVM准备各自WAL目录及相互独立数据身份，在隔离ZK下创建P000–P255 PREPARING并验证2组buddy的认证Genesis/READY；随后真实持续下单/撤单/撮合测试256分区、SIGKILL四节点中的任一主/备，以及租户10→50→200每档稳态不少于5分钟、p50/p95/p99、TPS、CPU/RSS/磁盘IO/网络、2–3倍burst；最终做资金/持仓/委托/成交及Projection权威一致性检查。性能上始终只有一个buddy副本目标，严格模式的双签名与保管仍需测量实际CPU和耗时。

**结论：Common RF2 256分区规划层PASS；4物理数据进程、256分区并发交易、200租户和生产级HA均未验收。**

## 22. 2026-10-23：3 ZK + 4 独立 JVM 的 256 分区 PREPARING 和 WAL 初始化验收

接续第21节 Common 初始 RF2 buddy 纯Java规划，本轮独立 Compose 文件为 compose.v19-rf2-256-catalog.yaml（项目 otc-common-ha-v19-256-catalog），真正启动三个独立ZooKeeper容器和A、B、C、D四个独立JVM元数据审计进程，并为四个JVM分别挂载wal-a/b/c/d独立Docker卷；依然全部位于同一台Mac Docker VM，非四物理故障域。

新增 DemoV19FourNodeShardCatalog 直接调用Common PartitionBuddyPlacementPlanner.proposeNew(256,1,...)。在专属ZooKeeper路径 /dc/cluster/commonhademo/v19-four-node-placement-pilot/assignments 真实写入256个P000–P255 assignment，epoch1、assignmentVersion0、全部PREPARING，0个可路由READY。首次bootstrap成功；四个JVM分别独立读取和校验全部256条ZK数据，每节点持有64 primary+64 standby、其余128不属于该节点。ZK的stat.version必须为0，内容必须与初始提案严格相同；缺失/额外成员、主备混淆、READY提前发布和已有数据被修改都会拒绝，绝不覆盖既有分配和证据。

新增 DemoV19FourNodeWalSlots：基于每个节点被规划分配的64主+64备，在该节点专属持久Docker卷打开、FileLock、检查各128个Pddd.wal文件，四节点共512份局部空WAL；未写入任何交易，也未授予Epoch授权。它会拒绝共享外组WAL目录、未认证的数据记录、脏尾部和符号链接，不删除原有数据。新增8项JUnit测试（catalog 5项、WAL slot 3项）全PASS。

为了验证恢复持久性，全部三台ZK进程实际停止并重启；原卷保留，重复运行bootstrap，幂等成功且不篡改旧256条记录；四个JVM再次启动，独立读回256个分区及各自128份局部WAL，四项 audit 结果均PASS、退出码0。隔离项目容器已停止，持久卷仍保存。旧严格Epoch9的8份证据卷未动；正式Order/Trade/MD保持运行，不执行GitHub Actions。

本轮Demo Maven全量回归：45 suites / 189 tests，188 PASS、1 SKIPPED、0 FAIL/ERROR。精确5文件Java/Compose源码阶段快照：tests/patches/common-v19-256-partition-four-node-zk-wal-catalog-20261023.tar.gz，并附同前缀SHA256 manifest，经独立临时目录安全解压逐文件字节验证。源码快照不是独立增量Git补丁，后续应审核差异再合入正式服务。

**当前只验收了真实4个独立JVM的metadata+WAL slot准备，不是4个持续交易数据节点。** v19主交易Harness/HA控制器仍硬编码P000、A/B与部分端点，未来须抽象分区级ZK租约、动态四节点Netty路由、RF2证书、CommitIndex/Custody和WAL复制，再让A/B、C/D两组真实逐分区签名Genesis→CAS READY→同时交易/故障。256并行分区TPS、10/50/200 tenants以及Order/Trade/MD/Projection最终对账均未验收。Mac剩余约12GiB、98%磁盘利用率，尚不适合直接进行200租户高压。

## 23. 2026-10-23：四个持续 Netty JVM 的256分区实测与失联门禁

承接第22节独立3 ZK/4 JVM/256条PREPARING记录和四个独立WAL卷，本轮新增 DemoV19FourNodeLiveRuntime：A/B/C/D四个实际持续运行的Netty监听进程（35411–35414），每个节点拥有64主/64备、128份独占的物理WAL FileLock，并对每个STATUS RPC重新校验所在分区、角色、ZK原始记录与stat.version0、WAL清洁状态。使用现有Common DirectNettyReplicationServer/Transport框架，保留精确节点路由和长连接。原DemoNettyBridge.endpoint/server和DemoJournalCatalog也支持合法节点D，拒绝非法第五节点。

在单台Mac的独立Docker项目中实际运行三个ZK进程、四个常驻数据Netty进程，第五个独立JVM针对256分区向所属主/备发送共512个Netty STATUS RPC，每个节点恰收128次。每个分区的主备WAL都为空、SHA256一致，状态全部PREPARING，ready=false、quorumDurable=false。额外发送真正的二进制WAL ReplicationBatch到四个节点、尝试COMMIT控制消息：所有请求都被拒绝，0个READY、0个订单成功，未错误开放未经认证的空WAL。对应实际输出：
FOUR_NODE_LIVE_NETTY_PROBE_PASS partitions=256 physicalStatusRPCs=512 perNode=128 a_b_c_d_exactRoutes=true crossBuddyHashesEqual=true writeRequestDenied=true allFourWalBatchRequestsDenied=true clientReady=0 realTrades=0。

实际SIGKILL C之后，A/B/D继续运行，但全量512-RPC探测正确在等待C的有界窗口后失败，而不是把缺少双副本的分区冒充READY。重启C并重新独占原128份WAL文件锁，全部512 RPC重新通过。补充Netty节点尚未bind时的有界重试，以避免Docker service_started和实际TCP ready的竞态；缺少节点绝不跳过或算成功。

Demo本地Maven全量回归：46 suites/193 tests，192 PASS、1 SKIPPED、0 FAIL/ERROR。十文件源码+Compose精确阶段快照：tests/patches/common-v19-four-live-netty-256-shard-routing-20261023.tar.gz，配套同前缀SHA256清单；独立临时目录安全解压后逐文件字节相等验证。仅作本地源码阶段记录，非直接可覆盖生产的补丁。实验容器已停止，3 ZK卷/4 WAL卷和先前Epoch9八份证据卷保留；正式Order/Trade/MD容器未改、没有GitHub Actions。Mac剩余约13GiB，磁盘使用率98%。

**判定：四节点持续Netty、256分区真实定向只读RPC、安全拒绝和C失联后恢复PASS；不是四数据节点交易HA通过。** 仍未实现该项目真实分区级签名Genesis、动态认证READY、双持久化WAL、CommitIndex及双保管、连续订单ACK、C→D自动接管交易。下一步应在A/B和C/D分别选一个独立分区，以现有Common状态机完成可信Genesis→READY→真实2/2 ACK→故障注入与恢复后，再安全扩展至256分区和10/50/200租户。PREPARING不可做真实交易。
