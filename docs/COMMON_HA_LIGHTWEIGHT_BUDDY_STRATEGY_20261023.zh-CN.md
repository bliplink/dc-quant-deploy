# Common HA 轻量选主与分区互备：实施决定

状态：**2026-10-23 用户已确认的目标架构 / 实施中，非生产完成**
范围：Common 共用集群基础设施 + 隔离 Demo；通过后才适配 Order、Trade、MD。
权威验收清单：`docs/COMMON_CLUSTER_REQUIREMENTS.md`；详细历史：`docs/COMMON_HA_SHARD_PLACEMENT_REPLICATION_DESIGN_20261023.zh-CN.md`。

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
