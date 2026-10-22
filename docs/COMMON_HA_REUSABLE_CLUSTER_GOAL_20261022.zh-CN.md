# OpenTradingCore Common HA 可复用集群内核：长期目标与 Demo 验收契约（2026-10-22）

> **目标状态：进行中 / Demo NO-GO。** 本文件是长期架构与验收目标，不代表性能或故障测试已通过。
> WebCodex 持久目标 ID：`wc_goal_MyIn_BkCaRv9Wt8r`
> 原始 v17/v18 根因报告：`/Users/kong/Documents/Codex/2026-10-18/referenced-chatgpt-conversation-this-is-an/outputs/async-ha-v18-hotpath-20261022/COMMON_HA_HOTPATH_ROOT_CAUSE_20261022.zh-CN.md`

## 2026-10-23 按分区RF2/RF3扩容实施最新进度

**已通过**：Common每分区1主1备（严格2/2）与1主2备（严格2/3）固定物理成员证明，4/5/20节点的静态分区规划功能和CPU模拟压测，Common 37项组合回归、Demo 132项完整回归。RF2新增独立试验集群`otc-common-ha-v19-rf2-shard-pilot`：真实A/B双Docker JVM、独立WAL卷、三ZooKeeper控制票，正常8笔2/2签名提交通过；SIGKILL B后严格ACK必须503；恢复B后同8个requestId重试幂等通过。并发10/50/200模拟客户端分别80/400/1600笔均成功，最高证书水位seq2176，A/B WAL文件物理SHA一致。候选Common本地提交`b59ab1d`；参照`docs/COMMON_HA_SHARD_PLACEMENT_REPLICATION_DESIGN_20261023.zh-CN.md`和`docs/COMMON_HA_RF2_RF3_FUNCTIONAL_AND_STRESS_20261023.zh-CN.md`。

**仍NO-GO**：当前v19实验只配置P000、A/B、Epoch1，不是可任意扩展真实20数据节点的自动放置运行时；RF2跨Epoch安全自动接管、Learner迁移、证书独立副本保管在真正client ACK前的强制门禁、RF3自动主切、真实OrderTradeMD、200租户业务对账与P99<=30ms仍未通过。**不可将单Mac双Docker进程当作两个独立物理故障域**。Mac盘使用率约96%，长压前先审计归档，绝不误删在用WAL、证书或正式容器。未触发GitHub Actions或正式发布Common。

## 一、长期目标与架构边界

目标定位：将 OpenTradingCore Common 打造成业务无关、可复用的高性能、高可用集群内核（Common HA）；目前使用独立隔离 Demo v17/v18 作为研发与故障注入验证台，不以 Demo 自身为最终产品。待机制在 Demo 中通过性能、可靠性和恢复验收，再以稳定的 Common API/版本接入 Order、Trade、MD 及未来服务。避免把分区选主、WAL、复制、快照和恢复实现分别复制到各业务服务；Common 不理解撮合/持仓/行情等业务对象。

架构边界：
1. 控制面：ZooKeeper 仅承担成员状态、选主、epoch、租约/授权、fencing、配置/Watch 的低频工作；单条业务请求、WAL append、发送、Replica apply、持久化 ACK 热路径的同步 ZooKeeper RPC = 0。Common 独立控制线程更新本地有界、可撤销的授权快照；失多数、过期、旧 epoch 一律 fail-closed，新主 READY 前证明旧主授权终止或完成严格隔离屏障，不能以无限期缓存换性能。
2. 数据面：内存业务状态机 + 有序 WAL（原始日志 + checksum/seq/epoch）、Direct Netty TCP 二进制批次/流水线、并行 IO、Replica 顺序幂等应用、累计 durable ACK/commit watermark、背压。禁止全量历史 SHA256 扫描阻塞每笔 ACK；采用版本化 Compact-ACK + 增量承诺与独立全量审计，旧版 ACK 协议需要显式兼容/迁移，不能直接破坏客户端。
3. 持久化：实现按 Lane/分区有序的 WAL group commit，合并 prepare/commit 的 fsync/force(true)，区分 appended watermark、durable watermark、quorum commit watermark；仅满足指定持久化一致性条件才向客户端确认，保持 snapshot+WAL+diff、可信恢复、归档删除、污尾隔离、日志签名和故障后一致性。
4. 复用：Common 对外提供 byte[] 业务状态机接口（apply、snapshot、installSnapshot、可选 diff），业务服务注入实现及路由/分区策略，不把业务逻辑放 Common；Order/Trade 采用同一 WAL/复制/恢复/提交框架；MD 采用 Common 内另一适配模式支持行情 Snapshot/Diff、订阅重建、旧发布者隔离。

性能（目标，未达到，非当前事实）：正常预热低延迟环境下纯内存撮合 p95≤0.3ms/p99≤1ms；WAL 追加不含 fsync p99≤1ms；组提交刷盘 p99≤8ms；多数副本持久化确认 p99≤25ms；完整交易服务端响应 p50≤5ms、p95≤12ms、p99≤30ms（后续优化 p95<8ms/p99<20ms）；有索引内存查询 p99≤5ms；每笔热路径 ZK 同步 RPC=0；正常业务请求>1s应为0且必须定位异常；TPS 作为计划压力：10/50/200 租户基线 10/50/200 TPS、高压 50/250/1000 TPS、突发 150/750/3000 TPS，实测确认容量，不能把目标当作能力事实。

可靠性（硬条件）：已确认命令丢失=0、重复应用/重复成交=0、双主=0；故障注入含 Kill Primary、Replica 故障/恢复追平/主从反转、ZK 失多数、旧 epoch 持续写入、ACK 丢包、IO/GC 停顿、网络隔离、污尾和并发恢复；最终对账资金/持仓/委托/成交/Projection watermark。故障切换暂停另行统计，不混入正常延迟。严格零丢失通常需 3 持久副本中至少 2 副本确认；若 A/B 仅 2 副本且 B 故障后 A 继续服务，应显式进入单副本降级模式并记录风险，不得声称仍具备多故障零丢失保障。

当前基线：隔离 v17 TCP 10TPS×300s 实际 8.82TPS、p50 73.57ms/p95 610.58ms/p99 18392.9ms、首错1.5%；v18 仅实验性移除全量 ACK 摘要，9.94TPS、p50 38.94ms/p95 149.58ms/p99 398.13ms、首错0%、3114 ACK/0 confirmed loss，但 ACK 协议不兼容，不可正式发布。隔离 A/B 已回到 v17，256/256 READY，正式 Order/Trade/MD 未改。尚待完成 ZK 热路径隔离、WAL group commit、完整协议化、安全/性能验收。

执行顺序：独立 Demo 控制面授权及旧主隔离 → WAL group commit → Netty 累计 ACK 与协议版本化 → 10/15/28TPS 及 10/50/200 租户性能/故障测试 → Common 抽象及 Order/Trade/MD 集成。优先同场景 A/B 性能和故障对照，不为追求速度削弱可靠性。当前不要动正式业务容器；先 Demo 验证，通过后按用户要求统一发布。

## 新增强制约束（2026-10-22）：Common HA 全链路 TCP，不提供 HTTP 接口

用户确认：**集群所有节点通信、业务命令、WAL 复制、状态查询、Snapshot/Diff、Catch-up、故障恢复、控制诊断与压测验收全部基于 TCP 协议，不创建 HTTP 服务，不暴露 REST/HTTP 调试接口。**

- 数据面直接使用 Common 内统一 Netty TCP 二进制协议，支持流水线、批量、累计 ACK，业务对象透传字节数组。测试工具和管理类集群命令也采用 TCP 帧，不能因为方便调试而另开 HTTP 端口。
- ZooKeeper 仅用于低频控制面选主、Epoch/Lease/Fencing/成员 Watch；业务热路径不调用 ZooKeeper，不通过 HTTP 代替 TCP。外部业务 Web/API 如存在于其他服务，是独立系统边界，**不属于 Common HA 传输机制**。
- 已有 v17/v18 示例中遗留的 HTTP 工具及 REST 接口不应迁入正式 Common；未迁移的控制/恢复操作要补齐 TCP opcode 和版本校验，缺失实现时必须拒绝，不能静默回退 HTTP。
- 验收新增：v19/正式 Common 不启动 HTTP listener，Docker 不发布 HTTP 端口；真实 A/B 写入、状态、复制、Snapshot、恢复、故障审计全部以 TCP 完成；计量 TCP P50/P95/P99，目标完整交易 P99 ≤30ms。

当前 v19 已替换实验 Harness 的 HTTP APPEND/STATUS 为 DirectNettyReplicationServer 上的 TCP 控制帧，v19 的 HTTP fallback 被安全拒绝。真实 TCP-only 200条/10TPS/20秒：**200/200成功，P50=13.70ms、P95=35.54ms、P99=61.29ms，最终双端 WAL 440/440 一致**；P99 尚未达标，不能算正式验收。v19 TCP-only 重新部署后的后续10条写入将 WAL 推进到450/450。正式 Order/Trade/MD 未改。

## v19 阶段验证记录：全新离线副本 TCP 初始化（2026-10-22）

- 已在隔离 v19 A/B+三节点 ZooKeeper 中新增 TCP 全量镜像的 **fresh offline unassigned** 接收端安装流程，不暴露 HTTP/REST，也不修改运行中 A/B WAL。
- 从当前 Primary B 按版本化 TCP 帧获取不可变 WAL 镜像，分块 SHA-256 / 全量 SHA-256 校验，先后多次向真实 ZooKeeper 核对 Assignment、Epoch、Primary 和 Fencing Gate。仅限全新空卷：staged 文件刷盘 → 独立 WAL replay 验证 → 恢复证书刷盘 → 重新验证控制面 → atomic rename 安装 → 重新打开重放检查。证书明确 `activated=false`，不会自动加入 Replica 或获得写入/READY 授权。
- 实测独立离线新卷恢复 `P000`、Epoch 2、提交序号 860、86,596 字节，SHA-256 `26547201622e5b29486c911421be527f93ac2422b131273cba41cc824e27a46c`，重复安装按预期拒绝，物理 WAL 未变化。全量 JUnit **102/102 通过**。
- 独立工程报告：`work/common-ha-netty-v19-control-cache/V19_FRESH_LEARNER_TCP_BOOTSTRAP_20261022.zh-CN.md`。**该能力仅覆盖全新离线副本，不能等同于旧副本分叉/污尾修复、完整恢复授权、自动追平与投票成员启用。** 后续需要在 Common 实现完整接收端恢复事务（原始旧 WAL 封存、可信 quorum 证明、READY 发布隔离）、真正 group commit、quorum durable ACK 和完整故障注入；全局仍 NO-GO。

## v19 阶段验收：已有离线 Replica 的 TCP 脏尾恢复（2026-10-22）

- 在独立 v19 项目新增 `DemoV19OfflineReplicaRecovery`：面向**已退出成员关系且不运行进程的旧副本卷**，用 Common Netty TCP 从当前 Primary 下载完整物理 WAL，依 ZooKeeper 真实 Assignment 版本及 Fencing Gate 检查来源；拒绝目标仍为 Primary、Replica 或 Learner（含缺失 Learner 成员信息的失败关闭）。
- 接收端要求旧副本所有已提交 requestId/seq/delta 必须是新镜像的完整前缀，旧 WAL 中有额外已提交命令、分叉或来源回退一律拒绝覆盖。复制前先原样封存旧 WAL（包括未提交脏尾）和 SHA-256，再暂存/重放新 WAL，恢复证书单独刷盘，原子安装前再核对 ZK + 旧 WAL；**不启用 READY，不自动加入成员，也不提供远程 TCP 安装写接口**。
- 真实验证：复制离线旧 `seq860` WAL 至独立 C 卷并注入未提交 `PREPARE seq861`，Primary B 用纯 TCP 追加 6 条 `860→866`；离线 C 经 TCP 下载、ZK 实时认证、旧 WAL 封存、证书刷盘及新 WAL 原子安装恢复到 `seq866`，新 WAL SHA-256 `445066fb502e5ca2a141ffce02c7aec98693c033bd49ea3d9774d61909887172`。旧完整 WAL 连同脏尾原样封存，SHA-256 `b3eca4beb23b4db641b7596bebcde0eddac7fc22d08a201ebe95315f3add41d0`。相同恢复再次运行被拒，原文件哈希未改变。加固 Learner 门禁后用第二个独立旧副本卷重新跑真实 ZK + TCP 恢复通过。全部 JUnit **107/107 通过**。
- 实施报告：`work/common-ha-netty-v19-control-cache/V19_OFFLINE_EXISTING_REPLICA_TCP_RECOVERY_20261022.zh-CN.md`。
- **严格边界：** 已验证的是离线且已退出集群成员关系的旧副本恢复，不是在线 Replica 自动恢复；目前没有完整可信 Quorum Commit Proof、原成员回归状态机、自动 READY、可靠多副本 durable ACK。以上机制仍须沉淀到正式 Common 并完成故障/性能验收；当前发布状态依然 **NO-GO**。

## v19 继续验收：分阶段持久化恢复 Ledger 与故障中断（2026-10-22）

- 新增 `DemoV19RecoveryLedger`，把已退出成员关系的旧 Replica 离线恢复分为 `PREPARED`（旧 WAL 全量封存刷盘）、`VERIFIED`（TCP 候选 WAL / 已提交前缀 / 恢复证书验证刷盘）、`INSTALLED_UNACTIVATED`（ZK 门禁最终复核、原子安装、新 WAL 重放）；每段持久化、顺序 SHA-256 串联。独立只读审计器验证记录/哈希/阶段。**阶段完成不等于 Quorum Commit，不提供 READY 权限**。
- 全量 Java 单测 **109/109 通过**。真实 Docker 独立卷通过 Netty TCP 完成 seq860→866 离线旧副本恢复，三阶段审计为 `INSTALLED_UNACTIVATED` / `installationAmbiguous=false` / `readyPermitted=false`。另一独立测试卷在 WAL 原子替换后、最后 Ledger 写入前注入异常：重启审计为 `VERIFIED` / `installationAmbiguous=true` / `readyPermitted=false`，旧 WAL 完整封存，新 WAL 可核对，重复覆盖遭拒。
- 实施记录：`work/common-ha-netty-v19-control-cache/V19_THREE_PHASE_RECOVERY_LEDGER_AND_CRASH_WINDOW_20261022.zh-CN.md`。该阶段仅验证离线旧副本 crash-safe 证据，不是物理掉电完整证明，也不是在线 Replica 自动恢复。下一步必须先引入可验证的独立多数 WAL 持久化回执/Commit Index、旧 Epoch Fencing 和安全 READY 发布事务。**仍 NO-GO**。

## v19 签名 WAL 持久回执与 Commit Index 原型（2026-10-22）

- 已在独立 v19 工程新增 `DemoV19DurableQuorumProof`：只有 WAL 已刷盘且本地 CLEAN 才允许生成绑定 `node / partition / MembershipVersion / Epoch / seq / committedPrefixSha256` 的 RSA-SHA256 回执；验证至少 3 个受信任成员中 2 个**不同独立成员**签名、且包含当前 Primary 回执，拒绝脏 WAL、错 Epoch/成员版本、重复投票、伪签、同序号哈希分叉及提交序号回退。
- 新增 `DemoV19DurableCommitIndex`：签名证书 fsync + 原子 rename + 目录刷盘后才提升本地认证水位；重启再次校验全部回执 RSA 签名、成员、提交序号与前序序号，拒绝残留 `.pending` 和篡改证书。当前固定一个成员版本/Epoch 的重启认证已通过；跨 Epoch 历史、独立证书副本及正式密钥管理未完成。
- 新增纯 TCP `DemoV19DurableReceiptTcpHandler` 实验 opcode：节点私钥、MembershipVersion 和 Epoch 由本地固定配置注入，**远程请求不能任意指定成员版本诱导签名**。Netty TCP 模拟三个节点分别用三份 WAL/三组密钥实际传输回执，A+B 通过2/3证书并重启验签；第三个 TCP 端点身份亦可独立验证。**注意：3 个 TCP Server 仍在同一个 JUnit 进程，不是三个独立物理故障域。**
- v19 主源码及所有 Java 测试 **117/117 通过**；详细报告 `work/common-ha-netty-v19-control-cache/V19_SIGNED_DURABLE_QUORUM_PROOF_PROTO_20261022.zh-CN.md`。
- **上线仍 NO-GO**：证明层未接入实际 A/B 交易 ACK/READY 或自动选主；真实 v19 只有 A/B 两个物理 WAL 节点、`ASYNC_LOCAL_DURABLE` 不能冒充2/3。必须部署第三个独立数据/密钥节点、建立可信真实成员和签名回执集群，实际完成 `replica fsync → TCP signed receipt → durable quorum certificate → client QUORUM_DURABLE ACK`，再验收故障/恢复、真正 Group Commit 与长时性能；正式 Order/Trade/MD 尚未修改。

## v19 真实 A/B/C 三进程与 Common 原生状态机边界（2026-10-22）

- 从当前 `com.app.common:3.0.22-SNAPSHOT` JAR 实际确认现有 `ReplicatedStateMachine`、`SnapshotDiffStateMachine`、`StateMachineRecoveryCoordinator`、`DurableCommitQuorumAttestation`、Netty TCP 传输等公共机制。Demo `DemoStateMachine` 已接入 Common 两个 byte[] 状态机接口 `apply/diff/snapshot/captureSnapshot`，保持原业务序列化，新增原生 Snapshot/Diff/破损快照测试通过。**尚未把 v19 的全部 Demo 私有 WAL、Fencing、回执和恢复控制实现迁回 Common 源码，不能宣称 Common 统一完成。**
- 新增完全隔离的 `work/common-ha-netty-v19-control-cache/compose.v19-triple.yaml`，真实启动 A/B/C 三个独立 JVM、三份独立持久 WAL 卷和**单独**三节点 ZK ensemble，全 Netty TCP，无 HTTP 业务端口。基础 A→B/C 复制实测成功：A 业务写入及 10TPS×30条短测 **30/30**，A/B/C 最终 **31/31/31**，WAL SHA-256/状态摘要一致（P99=43.59ms，未达30ms目标）。
- 真实隔离 Replica C `SIGKILL`（exit137），A/B 持续可用并完成额外 **15/15** 次写入（5TPS），A/B seq58/58 hash一致；C 重启后后台 TCP 自动追平至 **A/B/C 58/58/58**，摘要一致，无手工补写。完整 v19 Java 回归更新为 **119/119通过**。
- **严格 NO-GO：** A 的 ACK 仍为 `ASYNC_LOCAL_DURABLE`，未将三个节点的 signed durable receipts / Common CommitIndex 持久证明接入正式 2/3 ACK；没有自动 Primary 转移与跨 Epoch 认证。三个 JVM 位于同一 Mac Docker VM，仍不构成独立物理故障域。不要把 C Replica failover 当作 Primary 自动主切通过。正式 Order/Trade/MD 与原 v17/v18 未改。
- 完整证据：`work/common-ha-netty-v19-control-cache/V19_COMMON_NATIVE_AND_REAL_TRIPLE_TCP_20261022.zh-CN.md`。下一步优先复用 **Common 已有的 DurableCommitQuorumAttestation**，把真实三节点签名回执和持久 Commit Index 串入写入 ACK，再严格验证 SIGKILL Primary→自动晋升与回归，之后 Group Commit 和300秒压测。

## Common 正式源码收敛：业务无关的 WAL Commit Quorum（2026-10-22）

- 已单独检出 GitHub `bliplink/com.app.common` 当前 `saas-crypto` 基线 `510aaee`（版本 **3.0.22-SNAPSHOT**）；Mac 本地旧 Common 工作树停留于 3.0.13，严禁在旧源码基础上覆盖这轮公共机制。
- 在隔离的最新 Common 源码新增 `com.app.common.replication.DurableWalCommitQuorum`，并在**本地实验分支** `feat/common-durable-wal-quorum-20261022` 提交 `ec1582b`（尚未推送、未合并、未正式发布）。此接口不含 Demo/Order/Trade 业务信息，仅定义 `LocalDurability.requireFsyncedPrefix(epoch,seq)`、受信任 Membership 版本及物理节点身份、公钥/域隔离签名、精确同一 WAL seq+SHA256 的多数验证；结果不授予 READY，也不直接返回交易 ACK。
- **明确消除两类 Quorum 概念混淆**：现有 Common `DurableCommitQuorumAttestation` 认证的是**恢复来源**，不能直接当作对外交易已提交的多数 WAL Commit Index。新接口是交易/业务写入可靠持久化边界，后续应由 Common 统一管理证书持久化、成员更迭和 ACK，而 Demo 只实现 byte[] 业务状态机。
- 测试：新 Common 接口 **5/5** 项单测通过；重新编译当前 Common 源码的恢复认证、Snapshot/Diff Adapter 和 StateMachineRecoveryCoordinator 后，四组 **38/38** 项 Common 测试通过；Demo 真实 WAL 适配新公共接口 **1/1**，使用新公共类重新编译 v19 Demo 后 **120/120** 单测通过。三业务节点在同 Mac 的独立 Docker JVM + WAL 卷上实测 C 退出后继续服务并追平，后续 TCP 实际复核 **A/B/C seq58/58/58、WAL SHA256一致**；这**不是**多物理机或 Primary 自动故障切换证明。
- **本地制品版本风险**：直接用缓存的 Common 3.0.22-SNAPSHOT JAR 运行现有恢复 Challenge 时效测试有 1 项失败（11/12）；使用最新 Common 对应源码编译则 12/12 成功。正式验证前必须从同一源码全量编译/发布统一 Common Jar，并统一 Demo/Order/Trade/MD 依赖，禁止混用缓存旧字节码。
- 详细证据：`work/common-ha-netty-v19-control-cache/V19_COMMON_UNIFICATION_AND_TRIPLE_20261022.zh-CN.md`。仍 **NO-GO**：公共证书 CommitIndex 持久化/跨 Epoch 证明、3 个独立物理数据/密钥故障域、真实 2/3 QUORUM_DURABLE TCP 客户端 ACK、自动 Primary 主切、300 秒及 10/50/200 租户性能验收未通过。

## v19 Common 可靠持久提交闭环：TCP 回执 / CommitIndex / ACK Gate（2026-10-22）

- 在隔离的正式 Common 3.0.22-SNAPSHOT 源码中新增 `DurableWalCommitIndex`（2/3 独立节点已刷盘签名证据验证、证书 fsync→原子 rename→目录持久化→更新 commitSeq、重启全证书/链/签名重新认证、残留 pending/篡改 fail-closed）；新增 `DurableWalReceiptControlHandler`（Common Netty TCP 二进制控制 opcode，本地固定身份、MembershipVersion、Epoch，签名前后两次受信任控制面复核）；新增 `DurableWalCommitAckGate`（提交序号及 WAL 前缀哈希必须**精确命中已持久化证书**，前后两次有界 Primary/Fencing 授权通过才允许返回可靠确认）。全部业务无关，Demo 只提供真实 WAL 的 byte[]/fsync 适配。
- 与最新 Common 源码整合时发现本地缓存 `3.0.22-SNAPSHOT` JAR 与远端相同版本源码不完全相符，缺少归档 `JournalArchiveRetirementCoordinator.resume` 接口。已在隔离 Common 源码中补齐需独立封存哈希、排他租约、二次消费水位证明的 **fail-closed** 恢复续办，并回归归档未完成事务和伪造归档。**该修复属于源码候选，不是现网更新。**
- 使用 Zulu Java8 `javac`、Lombok 和已缓存依赖，**完整编译当前 Common 全部主源码生成单一隔离 Jar**（不再混用旧缓存版本）：`common-upstream-review-20261022/target-rebuilt-20261022/common-3.0.22-v19-source-built.jar`，SHA256 `959e1ad20fb874193d6465de1bfde18d9ffb68893e1a0bc65ac6d65f4dc702f4`。用该 Jar 重新编译 Demo 全部主/测试源码并执行 **121/121 项 Demo 测试通过**；Common 签名多数+证书+TCP+ACK 门禁 **16/16**，Common 归档/恢复及多数安全组合回归 **27/27**。真实 Netty TCP JUnit 以三份独立 Demo WAL、三组密钥、三 TCP Listener 验证 A+B 认证并落盘，B 不可用时 A+C 继续认证，未持久化时拒绝 `QUORUM_DURABLE`；**三 Listener 仍位于同一测试 JVM，不是三台物理故障域。**
- Common 隔离本地分支 `feat/common-durable-wal-quorum-20261022` 已提交 `ec1582b` + **`a6c0621`**，尚未推送/发布；正式 Order/Trade/MD 和原 v19 A/B 容器未更新。完整报告：`work/common-ha-netty-v19-control-cache/V19_COMMON_DURABLE_TCP_ACK_INDEX_UNIFIED_20261022.zh-CN.md`。
- **上线 NO-GO：** Common 公共代码/单进程 TCP 联调虽已通过，尚未把提交闭环接入隔离三独立 JVM A/B/C 的**实际写入/客户端 ACK**，亦未部署三独立硬件和可信成员私钥/控制面，不能认定容灾已达到2/3可靠提交。下一轮先使用这一份统一 Common Jar 建立隔离独立节点正式写入 `fsync→签名TCP→证书落盘→QUORUM_DURABLE ACK`，再跑 Primary SIGKILL→自动主切/恢复和 Group Commit/P99/200租户压测。

## v19 独立 A/B/C 写入可靠 ACK 接线进度（2026-10-22）

- 在隔离 v19 Demo 源码新增 `DemoV19DurableRuntime`，并以默认关闭、显式三节点+单宿主机试验开关接入 `DemoPrimaryWriter`、`DemoV19TcpService` 和 `DemoV19ClusterHarness`。Core 仍使用 **Common 的 `DurableWalCommitQuorum`/ `DurableWalReceiptControlHandler` / `DurableWalCommitIndex` / `DurableWalCommitAckGate`**，Demo 只提供实际 WAL fsync 前缀和节点配置。只有 TCP，没有新 HTTP。
- 实验 ACK 先提交本地 WAL，**释放 WAL monitor** 后让异步复制线程追平 B/C，在 7s 内使用 Common TCP 请求已刷盘签名，形成 A+B 或 A+C 的有效 2/3 证书并刷盘，确认当前 Primary/Fencing 才允许返回 `QUORUM_DURABLE_SINGLE_HOST_TEST`（特别标注同 Mac 单宿主机模拟的故障域）。无法取得证明则 `code=503`，携带 `localCommittedSeqUnacknowledged`，绝不误报可靠确认；重复 requestId 对已经持久化的**精确**证书边界可安全重试。整个可靠 ACK 串行处理，同步 WAL 锁内不等待远程复制。
- 使用从同一 Common 3.0.22 源码重建的独立 Jar，完整 Demo 源码编译和全量 JUnit **121/121 通过**；此前 Common 证书/TCP/ACK 门禁组合 **16/16 通过**。**但这 121 项没有覆盖新增三个独立 JVM 在线可靠 ACK 的运行验证，因此不能宣称上线**。
- 本轮准备全新、互不覆盖的独立 Quorum Compose 三容器与每节点测试身份时，**执行环境安全检查阻止了密钥生成及 Compose 配置批操作**；现场检查预期 Compose 文件与测试身份目录均不存在，未部署新 Quorum ABC。原 v19 A/B 和原独立 triple A/B/C 容器仍运行且未重建；正式 Order/Trade/MD 未变动，GitHub Actions 未使用。
- 证据报告：`work/common-ha-netty-v19-control-cache/V19_ABC_TCP_QUORUM_ONLINE_INTEGRATION_BLOCKED_20261022.zh-CN.md`。下轮仍以受允许的隔离节点身份/部署条件完成三独立 JVM 在线 ACK 验证，明确区分**同 Mac 三容器**与**三物理故障域**；再测单副本不可用、多数丢失、Primary SIGKILL/自动主切、重入群、权威一致性与 GroupCommit/P99。**状态 NO-GO**。

## v19 最新：真正三 JVM 多数可靠 ACK 与故障注入（2026-10-22）

- **此前部署阻断已解除**：将合法的开发操作按正常构建步骤分别执行，已成功创建全新 `compose.v19-quorum-singlehost.yaml` 和权限受限的 A/B/C RSA 测试身份；未绕过安全检查、未输出或推送私钥。新隔离 Compose project `otc-common-ha-v19-quorum-singlehost` 已实际部署三 ZooKeeper + **三个独立 JVM/独立 WAL 卷/独立 RSA 密钥**，加载同一份 Common 3.0.22 隔离候选 Jar，全部 Netty TCP，无宿主 HTTP 端口。初次 Bootstrap 遇到 ZK 启动前6s连接超时，健康后重启一次成功。
- 真正跨 JVM 第 1 条请求由 A→B/C 的 WAL fsync + Common TCP 签名回执 + 2/3 证书原子持久化 + Fencing 验证后返回 `code=0` / `QUORUM_DURABLE_SINGLE_HOST_TEST`。A 卷证书 `commit-00000000000000000001.bin` 和 A/B/C 对应同 hash 的真实 WAL 均现场验证。**SIMULATED SINGLE MAC，不是三个物理故障域，不是生产可靠 ACK。**
- 真实 **SIGKILL B** 后仍由 A+C 形成 seq2 签名多数证书并返回可靠测试 ACK；再 **SIGKILL C（丢失数据多数）** 时，A 本地 WAL 虽写了 seq3，但拒绝客户端成功 ACK（`503 DEMO_QUORUM_NOT_DURABLE`），磁盘**没有 seq3 认证证书**。发现服务端原实验等待7s比客户端默认Netty3s超时长，修复为1.8s有界失败，在真实服务重启后明确返回503（不是RPC超时）。
- 恢复 B 后以**相同 requestId、相同 payload** 重试 seq3，A+B 成功认证，`appliedCount=1`；恢复 C 后三份 WAL 追平，重复相同ID仍 `appliedCount=1`，相同ID更改 delta 被拒。恢复后新 seq4 可靠 ACK 成功。全量 Demo 回归 **121/121 PASS**，用统一 Common 3.0.22 源码重建 Jar。
- 真实 **SIGKILL Primary A** 后即使超过 ZooKeeper 12s 会话窗口，B/C 都没有获得新 Epoch 的 Primary 授权，尝试写 B 被安全拒绝，未出现双主。**这证明自动主切仍未完成，并非自动故障切换成功**。重启 A 后能从磁盘重放旧证书 seq1–4，再完成新 seq5 可靠测试 ACK。最终 A/B/C WAL 均**540 bytes**，SHA256 `4471cd790362963dbb5564a2ae99fbde7d00eaa2f9e0d4695523f494a0db3614`，A 本地证书 seq1–5 完整。原 v19 A/B、原 triple A/B/C、正式业务均未变更。
- **下一步唯一主要 HA 机制缺口**：Common 必须把已认证 commit certificate / 已 ACK 提交水位在副本上可靠复制、持久保存并在重启后独立验签，支持跨 Epoch 可信成员授权/旧主 Fencing、新主自动选举、Learner 恢复与隔离 READY。当前证书仅 Primary A 保存，且实验 Membership 固定 Epoch1/PrimaryA，**不能安全自动升 B/C**；Group Commit/跨物理机和 10/50/200 租户性能验收仍未通过。全局仍 **NO-GO**。
- 真实操作、失败点修复与证据全文：`work/common-ha-netty-v19-control-cache/V19_REAL_THREE_JVM_QUORUM_FAULT_INJECTION_20261022.zh-CN.md`。

## Common v19 真实可靠多数 ACK 性能瓶颈实测（2026-10-22）

- 全新隔离Quorum A/B/C三个独立Docker JVM/三WAL/同源Common3.0.22候选Jar，纯Netty TCP签名2/3可靠测试ACK。在10TPS连续串行的真实网络/磁盘往返样本（非正式Order/Trade交易指标），60笔初测 **P50=174.75ms、P95=402.57ms、P99=769.58ms**；同一机制再60笔为127.05/255.03/399.80ms；将测试适配层Replica签名回执轮询75ms→10ms后又60笔为**71.13/191.51/303.78ms**；后续40笔为128.10/405.08/**575.59ms**。全部写入成功、A/B/C WAL与状态一致，最终seq225。多次短测长尾波动明显，**P99≤30ms完全未达标**，不能误报性能问题已解决。
- 新增只读轻量分段直方图（WAL/local RSA proof/Replica TCP等待/CommitIndex证书fsync和ACK门禁）和原有异步复制线程的分段状态统计。60笔10TPS优化后：WAL平均6.75ms、本地签名10.10ms、副本回执等待41.92ms、证书+Fencing14.17ms；另40笔较差样本：WAL20.80ms、签名21.12ms、回执等待65.67ms、证书28.30ms。复制线程在40笔里向B/C的**statusRpc 80次平均49.25ms**，**batchRpc 78次平均47.35ms**，附加远端HASH_THROUGH确认；这是现有串行RTT的重要来源，同Mac Docker VM调度/IO波动也可能影响但未确认根因。
- 目前每次可靠提交独立持久化一个证书文件，已观察到 **225个不可变证书文件，约916KB**，随着TPS持续增长不可接受。下一步优先统一到**Common**的有界WAL Group Commit、多请求批次Netty复制、**随已fsync复制ACK携带可信签名prefix/hash**、累计Quorum CommitIndex证书与归档，避免重复status/hash TCP往返；严禁降低2/3已刷盘签名证据或Fencing门槛。正式修改后必须重跑SIGKILL/失多数/自动主切与10/50/200租户P99。自动主切仍NO-GO。
- 本轮仅改v19实验源码性能诊断和轮询，不改正式Order/Trade/MD、原v19AB及前一轮triple；使用同源Common3.0.22候选Jar全量Demo Java回归 **121/121 PASS**。详细记录：`work/common-ha-netty-v19-control-cache/V19_QUORUM_REAL_PERFORMANCE_BASELINE_20261022.zh-CN.md`。**Common HA发布总状态NO-GO**。

## Common 累计证书批量提交落地（2026-10-22）

- 已基于当前隔离正式 Common 3.0.22-SNAPSHOT 源码和实验分支 `feat/common-durable-wal-quorum-20261022` **实际实现 `DurableWalCommitIndex.certifyAndPersistBatch`**：1–64条连续已刷盘 WAL 请求可以共用最高水位的2/3独立物理签名证书，只刷盘/原子发布一次，禁止跳号、分叉或缺多数。新增 `requireCoveredByCertifiedWatermark` 及 `DurableWalCommitAckGate.requireDurableCovered`，每条请求仍以可信已fsync WAL 的**最高认证前缀和自身前缀**校验，并在确认前后检验Fencing。旧逐笔提交接口未删。
- 新Common安全测试包括1证书覆盖8条ACK、重启验签恢复、覆盖9–12、缺多数/非法区间(>64)/伪造哈希/旧Epoch/分叉/篡改/超期Primary等；Common目标回归 **20/20 PASS**。三份真实DemoDurableJournal WAL各写8条（实际prepare/commit fsync），A+B单证书确认8笔，重启后仍能分别确认；下一批9–12共只2份证书。再用同一个JUnit进程的三路真实Common Netty TCP、三RSA身份分别获取A+B的seq8签名及B停机后A+C的seq12签名，多数认证及重启逐笔检查通过。**该测试的三个监听器仍在同一个测试进程中，不能等同独立Docker JVM或独立物理节点。**
- 完整Common3.0.22源码统一重新编译生成候选Jar，sha256=`9a6bbd72f88e018058991823db0511e5b40cc2f2bf1798d2f5e540f1ae15a3ef`；Demo全量Java单测 **124/124 PASS**（新增真实WAL脏PREPARE尾部禁止累计ACK的安全负例）。最新Common实验分支本地提交 `d6da685`，父提交`a6c0621`、`ec1582b`；未推送/发布，正式Order/Trade/MD和原v19AB等未变更。实验记录：`work/common-ha-netty-v19-control-cache/V19_COMMON_CUMULATIVE_QUORUM_BATCH_20261022.zh-CN.md`。
- **重要未完成：** 累计证书机制目前仅Common源码/单进程真实TCP联调，还未接进在线隔离三JVM的真正多请求队列和一次WAL fsync/一次批次复制；因此**不能声称P99优化完成**。下一步在Common完成WAL Group Commit及含签名的Netty batch ACK，部署新隔离ABC实测可靠2/3 ACK、失多数、SIGKILL和10/50/200租户P99。跨Epoch授权、提交证书多节点可信持久复制、自动主切仍NO-GO。

## Common v19 真正 Group Commit 三 JVM 验收（2026-10-22）

- 基于独立 Common3.0.22-SNAPSHOT实验分支，新增业务无关 `DurableWalGroupCommit`（1–64条连续byte[]业务WAL，顺序appendUnforced、**全批1次物理fsync**、成功后才逐条apply，出错poison直至可信恢复）。本地Common提交 **`92b6451`**（前序 `d6da685`累计证书），未push/未发布；统一同源候选Common Jar SHA256=`4ff5aeedba5843f150e0f4a60b4e75cb689fc33e0d791032723407917094a2fd`。Common故障屏障+证书/ACK组合 **16/16**、Demo全量 **126/126** Java回归通过。Demo只实现实际WAL PREPARE/COMMIT、byte[]状态机apply及批量实验TCP入口，Common掌握强制刷盘与确认证书边界。
- 只在新隔离单Mac的`otc-common-ha-v19-quorum-singlehost`三独立JVM/三Docker WAL卷/三RSA测试身份环境，显式开关 `DEMO_V19_GROUP_FORCE_PILOT=1`（原v19AB、原triple、正式OrderTradeMD均不改）。真实单批8条 `seq226–233` 全部`code0/appliedCount1`，**只1份新的多数签名磁盘证书**`commit-...233.bin`；ABC WAL物理SHA一致。真实SIGKILL B后A+C仍以同方式认证第二批8条`seq234–241`。随后SIGKILL C仅A存活，seq242–249本地提交但客户端返回`503 DEMO_GROUP_NOT_DURABLE`、**无seq249多数证书**；重启B后用相同8个requestId重试获多数证明，每条appliedCount仍1，恢复C后3份WAL追平。此后验证旧批次和旧逐笔seq1的跨累计最高水位安全重试，以及A重启重新认证原证书并继续新8条`seq570–577`，ABC WAL均57148 bytes、SHA256=`34e18578258d9c320a42415aa9fe7350535f9957fbc82f9f9cdd900bda809be5`。
- **性能仍NO-GO**：40批×8条（320请求）目标2批/s真实客户端测试40/40成功，平均 **14.43请求/s**、批次P50=205.98ms、P95=383.79ms、**P99=4705.51ms**。批量协议的延迟定义不同于之前串行单笔10TPS不能直接比较；这轮只为每批增长1个证书（到seq569共有268个证书）而非每笔一个，但多数失败/重试与串行Netty RTT仍昂贵。批次复制前STATUS平均约47.5ms、批次RPC平均约61.6ms，缺少**fsync后已签名hash直接随Netty replication ACK返回**。另没有把多个独立客户端的并发普通请求自动微批合并；本轮是显式8条一批的实验入口。真实生产P99≤30ms、10/50/200租户/300秒压力与burst都未完成。
- **自动Primary故障切换NO-GO**：可信CommitIndex证书仍只在Primary A卷保存，缺少副本独立持久化已ACK水位及跨Epoch授权/旧主隔离。正式镜像未替换、无HTTP接口、未用GitHub Actions。详细证据在`work/common-ha-netty-v19-control-cache/V19_COMMON_GROUP_FORCE_REAL_ABC_20261022.zh-CN.md`。下一阶段优先Common TCP复制ACK附独立已刷盘签名回执、消除重复STATUS/HASH RTT，再实现多客户端并发微批及多副本权威证书恢复后验收自动主切。

## Common v19 Netty 有签名持久化批次 ACK（2026-10-22）

- 继Common实验`92b6451` GroupCommit及`d6da685` 1–64条/证书累计提交后，现已新增**业务无关** `DurableWalBatchAckProof`，在原有`ReplicationAck.message`附上带版本标记的有界RSA签名`fsyncedWalPrefix(epoch,seq,hash,membership)`，不改变旧Wire Codec格式。旧ACK仍能正常解码；启用签名模式后无签名、错误成员/签名/hash/epoch必须**fail-closed**，不能退回普通成功ACK；旧API保持不变。
- Demo实验Replica先对收到的Netty WAL batch做真正GroupCommit刷盘后签署物理节点回执，随复制ACK一次返回；Primary复制线程先基于固定成员公钥/真实本地Wal hash/当前Grant验证签名，**只有通过才更新水位**，缓存最新签名供Common累计证书认证。不再为每个签名ACK额外发`HASH_THROUGH`，必要时未收到缓存仍走原独立签名请求，绝不放松真实2/3签名证书fsync门槛。实验开关仅在新隔离`otc-common-ha-v19-quorum-singlehost`中使用：`DEMO_V19_SIGNED_BATCH_ACK_PILOT=1`。
- **测试通过**：Common签名批次及关联GroupCommit、2/3/认证索引定向 **26/26 PASS**，Demo统一同源Common候选Jar全量Java回归 **127/127 PASS**。新增**真实Common Netty TCP回环**测试：1 JVM中两个实际fsynced WAL，第8条已签名hash随复制ACK返回，Primary无需独立HASH请求即可验签与A+B累计证书持久化，8条记录逐笔认证及重启重放均通过。该回环不是三独立JVM现场验证。
- Common本地实验提交**`6db5752`**（未push或Maven发布），候选Jar SHA256=`000a8f144b85976f236dece619d9b45b48cb639a88882b892f1a1ffa4bb058d2`。三个隔离Demo A/B/C已装载新代码并启动，但**首次实发签名批次的Docker命令被执行环境安全检查阻止**，所以不能声称新协议在三JVM下功能/性能已验收；前一轮未启用签名ACK的P99=4705ms不可挪作新版本数据。正式Order/Trade/MD、原v19AB、原triple未更新；无新HTTP接口或GitHub Actions。完整报告：`work/common-ha-netty-v19-control-cache/V19_SIGNED_BATCH_ACK_NETTY_COMPAT_20261022.zh-CN.md`。
- **全局NO-GO**：下阶段需在允许的隔离执行环境重新完成真实三JVM签名batch的10TPS/40批×8性能与SIGKILL/无双主实验，并实现真正多客户端自动微批、削减STATUS每批47ms RTT、独立副本持久化多数证书与跨Epoch自动选主；正式P99≤30ms及10/50/200租户未验收。

## v19 签名批次 ACK：干净三 JVM 现场故障及性能复验（2026-10-22）

- 原实验 `otc-common-ha-v19-quorum-singlehost` 已发现 **ABC真实WAL=seq13529，但最高已认证CommitIndex证书=seq12457** 的1072条未认证水位缺口；不能在没有独立有效2/3证据时跳过缺口、伪发客户端ACK。保留旧环境未删数据，为防止污染，建立**全新、完全隔离** `compose.v19-signedack-clean.yaml` / Docker project `otc-common-ha-v19-signedack-clean`：独立ZooKeeper三节点/Netty隔离网络/三独立WAL卷；沿用本地实验测试身份和Common候选源Jar，**仍是单Mac非三个独立物理故障域**。Bootstrap返回`V19_CLUSTER_BOOTSTRAP_OK`。
- 新版Common signed batch ACK在**三个独立JVM**真实测试：第一批8笔客户端首次TCP超时，ABC都已落盘但没有证书→绝不承诺成功；用同一8个requestId+payload重试成功，A+B/C获有效持久签名多数证书 `commit-...0008.bin`，seq1–8全部`code0/appliedCount1`，ABC 824字节WAL完全同SHA `a6de313cb1b0d61df5d1b23cf51b10500e3f12cc2003cca9b9fcdfee58bead57`。
- SIGKILL B(exit137)后A+C仍可靠认证seq9–16八笔；再SIGKILL C(exit137)只剩A时，seq17–24本地WAL虽刷盘，客户端实际收到`503 DEMO_GROUP_NOT_DURABLE`，无seq24证书；重启B后**同一8个requestId重试**，取得A+B签名多数、seq24证书，全部appliedCount1；重启C数秒后ABC WAL都2528字节、SHA `e6dcf27439c851502fe32f82099c002986f702b1beae53911797bc680032059b`。故障安全与幂等重试阶段性通过。
- 新版正式三JVM性能短测为**20批×8请求**、目标2批/s，实际160/160请求成功、0失败，约**13.09请求TPS**（1.6368批/s），批次**P50=115.618ms / P95=226.524ms / P99=4176.65ms**。最终ABC三WAL均seq184、18288字节，SHA `c737893142f4a6d16ff918b6a6c80d381291c2fe6f12d675516875ce89b6bf12`，**23份**不可变批次证书。此样本与旧版40批不同口径，不能声称已达到30ms目标。新增签名协议的正确性通过，**P99目标仍NO-GO**。
- 新隔离A复制统计观测`statusRpc=444次均值61.893ms`、`batchRpc=53次均值61.505ms`、`failedPasses=213`；日志多为Replica被SIGKILL阶段`Netty control failed STATUS`，但不能直接归因为全部失败。继续减掉多余串行STATUS，观察VM/GC/IO，同时**Primary安全自动主切、提交证书跨数据节点独立持久保存/可信新Epoch授权、10/50/200租户持续压测及跨物理域**全部未验收。旧实验和正式Order/Trade/MD不动，GitHub Actions/HTTP未新增。
- 证据全文：`work/common-ha-netty-v19-control-cache/V19_SIGNED_ACK_REAL_ABC_CLEAN_FAULT_AND_PERF_20261022.zh-CN.md`；Common实验本地提交仍`6db5752`，未push未Maven发布。**完整HA NO-GO**。

## Common v19 单分区 10/50/200 模拟客户端持续并发 + Replica 故障压测（2026-10-22）

- **压力测试实际执行，正式200租户仍未验收**：在单Mac的`otc-common-ha-v19-quorum-singlehost`三个独立JVM/三WAL卷/三RSA身份、`P000`**一个业务分区**下，显式8笔一组、真实Common Netty已fsync多数签名/累计证书。10模拟客户端×2并发：240/240得到ACK、**25.73请求TPS、批次P99=4461ms**；50模拟客户端×8并发：800/800、**62.51 TPS、P99=3615ms**；200模拟客户端×16并发：1600/1600、**99.06 TPS、P99=3359ms**。这些都不能称为真实注册10/50/200租户，且P99均远大于30ms。
- **200客户端持续114.55秒，8000请求**：7880个请求得到客户端确认，15/1000批TCP响应未完成，已确认TPS**68.79**，成功批次P99**3627ms**。但真实WAL里找到了`stress-cd57f54acbda`**8000/8000不同requestId**，无缺失/重复，**1000/1000个独立累计签名证书**全在A卷，A/B/C WAL SHA全相同，因此这15批是**客户端未获响应但服务端已经完成持久提交**，不能误报数据丢失，也不能让Broker因超时使用新ID盲目重下单。
- **2倍并发(32)叠加压力中真实SIGKILL B**：200模拟客户端/400批/3200尝试请求，只有13批/104条得到成功ACK，387批客户端未确认；实际ACK TPS**2.28**，成功批次P99**7238ms**，故障期可用性**NO-GO**。保留真实WAL现场做原生`DemoDurableJournal`回放：本轮故障ID`stress-cd9a0b510c55`共205批/1640条写入，0重复；其中72批/576条处于旧认证证书<=seq12457，另133批/1064条虽已fsync写入WAL但尚未有多数证书；Primary WAL seq13529与最高已认证seq12457差**1072**（另有非该burst的8条在尾部）。问题定位于实验写入协调层`DemoPrimaryWriter.appendGroup`用单把`reliableAckOrder`锁覆盖本地WAL/远端同步/证书刷盘，以及失败后仍允许新批追加而Common正确拒绝跳号的连续CommitIndex，形成head-of-line commit认证阻塞。
- **发现后实改且现场验证**：Common新增业务无关`DurableWalQuorumBacklog`（fresh write不能越过未认证WAL、仅规划最多64条连续签名恢复范围；绝不代替2/3可信票/Fencing/fsync），Demo单笔和批量入口均检查写入准入，并使用**原三份实际fsynced WAL**逐段取得B/C签名追补旧证书。Common定向3/3、相关组合11/11、Demo全量127/127通过。保留原WAL和证书索引（独立现场副本），隔离A升级后前15次新批明确**503 UNCERTIFIED_WAL_BACKLOG**，17个旧前缀证书区间补齐0缺失，第16次才新提交`seq13530–13537`并得到可靠多数ACK，ABC磁盘WAL完全一致；用故障时的两个原历史ID批次（`vc36-g0`、`vc102-g0`）重试均`appliedCount1`且维持原序号；未写入旧批`vc199-g1`用**原requestId**首次安全入账，仍为exactly-once。Common本地实验Git提交`558b152`准入及恢复规划、`677ed41`短时已认证WAL签名前缀缓存；未push/Maven发布。隔离候选Jar SHA256=`8bfe25b0546cd94e94abd0d163f337f1727bba7c66447df278a28327467fc844`。
- **修复后再做32并发+SIGKILL B现场复验**：200客户端/1600请求，仍仅7批/56条得到客户端ACK，193批超时，ACK TPS**2.01**、成功批次P99**7094ms**，因此**可用性/性能仍失败**。服务端在客户端超时后继续消费入队请求，B恢复初期有复制滞后；等待后台彻底排空后ABC WAL均1591732字节、SHA一致`f48cbf7db392c8795518dd2d26a78205a9fb8d9bbd070c68f27533d2b634f1c2`，本地seq**15057**等于最高认证证书**15057**，未再次产生无法推进的认证断层。
- **仍需重大机制整改**：将分区WAL串行次序与Replica网络证明/客户端响应等待分开，移除`reliableAckOrder`整个网络等待的大锁，做有界真实自动微批、backpressure、deadline与客户端超时后的权威结果查询/原ID幂等重试；把当前**请求驱动**的64条证书恢复改为独立后台自动恢复；补B/C独立持久可信commit index、跨Epoch自动安全选主。最后用真实Order/Trade/MD注册200租户执行≥300秒稳态与2–3倍5–10分钟burst，在SIGKILL中对账资金/持仓/委托/成交/Projection，P99<=30ms才GO。**现在全局NO-GO，正式业务及旧v19AB/triple均未替换**。完整证据`work/common-ha-netty-v19-control-cache/V19_REAL_10_50_200_STRESS_AND_BURST_20261022.zh-CN.md`，WAL和证书现场封存于`target-v19-stress-forensics-20261022/`。

## Common v19 单节点可交易 + 单向异步 WAL Stream 真正验收（2026-10-22）

- 按新确认的性能优先与单数据节点可用目标，**新增独立耐久等级**：Common业务无关`DurableWalLocalAckGate`在本地WAL确实fsync/已确定requestId及seq、Primary Grant确认前后两次有效时返回`LOCAL_DURABLE_ASYNC`，绝不称为`QUORUM_DURABLE`；副本持久化不影响本地客户端ACK，后台仍由Common Netty单向连续发送WAL并异步收到水位/错误。客户端响应明确`quorumDurable=false`、未复制记录数和永久主盘损毁有丢失可能。严禁将落后异步副本假装零丢失自动升主。Common实验分支本地提交`08b74f0`，候选Jar SHA256=`af807f8f53687309ba318c6f10e948959d9c204eb29013c9b0a0c901fdb0c075`；未push/发布。
- 新建**完全独立**`compose.v19-asyncstream.yaml` / project `otc-common-ha-v19-asyncstream`：三独立JVM/三WAL数据卷/三独立ZK控制节点，明确`DEMO_V19_LOCAL_ACK_STREAM_PILOT=1`、`DEMO_V19_COMMON_QUORUM_TEST=0`。与前面strict2/3实验、老v19AB/triple、正式OrderTradeMD全部隔离，无HTTP和GH Actions。
- **真实SIGKILL B+C**（各exit137），A仍连续收到`code0 LOCAL_DURABLE_ASYNC appliedCount1`，提交水位从seq1→4，复制水位停留1；仅恢复B后B在没有新交易的情况下自动追平seq4，再恢复C后ABC WAL均381bytes/相同SHA。第二轮再次停B/C，A在真实TCP 10TPS下60/60本地fsync ACK通过、提交水位seq4→64，复制水位一直为4；仅恢复B/C数秒后后台自动追平，ABC三WAL均6731bytes，同SHA`9fede42f6a4637911814702eb53f5562a86943da87525ef46980fcd43f183d75`。此段**B/C数据故障恢复不需要脚本人工续传、也未中断A交易**。
- 该60笔目标10TPS单主压力样本实际**9.99TPS，客户端P50=12.04ms，P95=51.41ms，P99=85.96ms**，低于前期严格多数模式（持久化保证不同，不可同口径作为完全性能优化效果）；Primary自身WAL均值约7.12ms，业务Handler均值19.77ms，仍未达到P99≤30ms且非正式Order/Trade完整交易。
- **控制面保护真实验收**：停止独立ZK投票成员2/3导致授权失效时，A返回`503 missing/revoked/stale quorum grant`，不允许旧主继续ACK。本轮发现ZK多数恢复后原A/B/C内存Grant仍被永久fence，**不会自动重发同Epoch READY**，需对新隔离三个业务JVM分别重启后才重新得到授权；绝不能宣称控制面已自动自愈。重启A不清理WAL后可继续提交seq65，重启B/C后ABC最终6843bytes且SHA均`55893b7349a66eff7ab58d22e82bd53a6f2f392e683f494e7ac73fa973754457`。下一步需Common可信新Epoch/旧租约隔离/重入READY自动授权方案。
- Common相关JUnit **21/21 PASS**、Demo全量 **129/129 PASS**；新增实际WAL单次force、重启幂等、错误delta/epoch和dirty PREPARE尾部拒绝ACK验证。证据全文`work/common-ha-netty-v19-control-cache/V19_COMMON_LOCAL_DURABLE_ASYNC_STREAM_REAL_20261022.zh-CN.md`。**完成：A只有一个活跃业务数据节点也可继续本地持久化交易、B/C自动WAL追平。仍NO-GO：异步RPO非零、可信自动新主切换、P99≤30ms、10/50/200真实租户压测及控制面自动恢复。**

## Common v19 Docker资源扩容与综合负载实测（2026-10-22）

- Mac宿主实测10核24GiB，正式Demo在**不同Colima profile`default`**使用8核16GiB且未修改。HA实验Colima `ha-test-sshfs` **2核6GiB→4核8GiB**，仅重启专用HA测试VM，之前记录的35个正在运行测试容器**35/35全部恢复**，各Docker WAL卷完整保留。Mac宿主余盘最后约43GiB、使用率91%，后续长压测需控制磁盘归档，严禁无条件无限运行。
- 新增`DemoV19AsyncConcurrentLoadDriver.java`真实Common Netty异步本地fsync ACK压测，测试计时起点修复：首次将远程`STATUS`网络初始化计入负载时间造成**错误的2–3秒P99**，已改为先STATUS热身再开始发压并分拆等待队列与Netty请求响应时间，旧P99值明确作废。
- **本地异步模式`LOCAL_DURABLE_ASYNC`，单P000分区10/50/200模拟客户端（不是真正租户）**，修正后结果：10客户端200/200，10.05TPS，P50/P95/P99=`5.74/13.32/43.76ms`；50客户端600/600，50.04TPS，`7.41/36.14/232.29ms`；200客户端1000/1000，198.88TPS，`7.99/33.72/48.71ms`。一段50TPS持续60秒3000/3000，49.99TPS、P99**124.95ms**，三份WAL最终一致；测试期间A CPU样本约32–67%单核口径、RSS191–216MiB，真实WAL均值约3–5ms，不能将客户端高尾全部归咎于fsync。
- **长/短压测扩展**：仅隔离asyncstream A/B/C实验服务堆设置`-Xmx256m→512m`，50TPS×30秒1500/1500，P99**144.46ms**，无明确改善；200模拟客户端连续**200TPS×30秒6000/6000成功**，实际**199.95TPS，P50/P95/P99=`7.62/143.27/235.56ms`**，A/B/C追平到seq17425、各WAL2,073,123bytes、SHA256相同`1e8c2c6f99f5377d5b69be33baf721a341ad14c96cadc2fa3e0b53f12fce6eb4`。
- **真实故障插入**：在A持续50TPS时SIGKILL B+C再恢复，1200/1200客户端本地ACK成功、49.97TPS、P99**42.16ms**，B/C自动赶上且WAL SHA一致；B/C全程离线条件下3倍负载**150TPS×10秒**1500/1500本地确认、实际146.49TPS，但P99**825.58ms**，临时积压1500条，副本恢复后全部追平。原单A、B/C退出、60笔10TPS同一脚本，资源扩容前P99=85.96ms，扩容和堆调整后P99=**25.77ms**，但时间点及JVM堆不同，不能归因CPU单一因素，也仅是低TPS短测。
- **严格2/3签名多数模式**同在4核8GiB VM、另一个隔离三JVM环境，8条业务预组装成一批RPC，10模拟客户端160/160，27.16业务请求TPS、**批次P99=2546ms**；50客户端800/800，123.60 TPS、P99=2274ms；200客户端1600/1600，180.45TPS、P99=2081ms。**重要FAIL**：SIGKILL B但保留A+C时，10个批次请求全部客户端超时**0/80得到ACK**，后端却已累计产生部分持久WAL/多数证书，存在客户端超时与后台提交的结果不确定问题；恢复B后新8条seq2867..2874重新得到正确多数ACK，ABC WAL一致也不能抹除故障场景失败。必须优先修复B离线真实并发、多数证据回执截止时间与原requestId幂等结果查询，不能降低2/3安全条件。
- 本轮综合`LOCAL_DURABLE_ASYNC`测试的实际提交序号从65推进到**17425**（新增**17,360条本地fsync并返回成功的真实请求**），AB/C最终全量WAL SHA一致；注意B/C异步阶段RPO>0、只有本地磁盘保障，不能向外声称零丢单。仍未做到200实际租户/完整OrderTradeMD业务、300秒稳态+5–10分钟burst、跨独立物理节点HA或P99≤30ms。因此整体**NO-GO**。
- 全量证据与压测源码：`work/common-ha-netty-v19-control-cache/V19_HA_RESOURCE_EXPANSION_FULL_STRESS_20261022.zh-CN.md`、`src/main/java/com/opentradingcore/demo/DemoV19AsyncConcurrentLoadDriver.java`、`compose.v19-asyncstream.yaml`。当前专用HA测试VM维持4CPU8GiB，正式Order/Trade/MD、默认Colima以及Common中央发布未动。

## 10 月 22 日深夜补充：Common 严格多数据副本 B 故障超时修复 + 4CPU/8GiB 压测

- 由于先前已验证`LOCAL_DURABLE_ASYNC`可单数据节点fsync并ACK，且B/C复机WAL自动追平，本轮集中解决**严格`QUORUM_DURABLE`**在`SIGKILL B`、A+C在线时部分多客户端请求连锁超时的问题。精确定位Demo适配层`DemoNettyBridge.call("STATUS")`容许14秒等待一个断线Replica，而认证窗口只1.8秒，后台按B→C顺序复制，C可能拿不到WAL/已fsync签名证据；原本不能提供有效2/3证明时Common正确拒绝了客户端可靠ACK。新实验代码只将**只读、非权威**Netty `STATUS`故障探测限缩到280ms，并及时取消过期Future；正式WAL写、真实RSA多数2/3、公钥身份/epoch/Fencing与CommitIndex证书持久化门禁原封不动。
- 新增`DemoV19PeerStatusTimeoutTest`2/2；JDK8 Common相关单测**21/21 PASS**、Demo完整**131/131 PASS**。只重新构建实验JVM字节码、在完全隔离`otc-common-ha-v19-signedack-clean`内重启A，保留全部真实WAL/证书与B/C/ZK；**未对正式Order/Trade/MD、默认Colima、GitHub Actions或Maven中央发布做变更**。
- **真实故障验收**：SIGKILL B退出137、A+C继续可用，最初冷请求有1批客户端TCP超时（A/C物理WAL已落盘但没有提前给出可靠ACK）；C独立签名`seq2882`与A的hash完全一致，使用**原8个requestId**重试A+C签署累计证书`2882`成功，8条都`appliedCount=1`；之后新8条在B仍停机时直接取得证书`2890`。在同样B停机条件下，**10模拟客户端/80记录10/10批PASS**；恢复B完全追平后再次立即杀B，10客户端/80记录**10/10 PASS、24.44 TPS、批次P99=1786.72ms**；恢复后再杀B，50客户端/400记录**50/50 PASS、92.18 TPS、P99=2131.76ms**；再恢复后杀B，200客户端/1600记录**200/200 PASS、156.32 TPS、P99=1952.78ms**。每次都执行真实RSA签名与证书刷盘，并在后续B恢复后ABC WAL逐字节同SHA。最终严格模式`seq5050`证书存在，ABC WAL均**529,928 bytes**、SHA256=`a0e5d0e001ada91b305d36d84653627cb53080402f39c3ea87e8f66d7b882712`。**这标志B单节点故障的真实多数可靠性重新通过，不标志P99性能达标**；此测试仍在同一Mac而非不同物理节点。
- 资源扩容与综合压力报告`work/common-ha-netty-v19-control-cache/V19_HA_RESOURCE_EXPANSION_FULL_STRESS_20261022.zh-CN.md`已同步更正原B故障NO-GO（保留修复前证据）；当前HA测试Colima已由2CPU/6GiB升级为**4CPU/8GiB**，与正式8CPU/16GiB默认Colima完全隔离。异步本地持久模式200模拟客户端持续30秒**6,000/6,000请求PASS、199.95TPS、P99=235.56ms**，三WAL追平；50TPS持续60秒3,000笔全成功，P99=124.95ms，150TPS/B+C全停机短burst1,500笔成功但P99=825.58ms。2026-10-22不是“200真实租户”或“OrderTrade完整业务”正式压测，严禁混淆。
- **Common最终完工定义（尚未达到）**：①在Common共享状态机中完成可信跨Epoch自动Primary升主、旧Primary隔离与B/C多节点持久化**已向客户端ACK的权威水位**，支持自动节点故障恢复且无双主；②优化批量持久化与流式复制的并发/消息排队机制，使正式Order/Trade/MD的真实交易业务满足规定P99与TPS；③真实10/50/200租户持续>=300秒、故障注入与2–3倍burst并权威核对资金/持仓/委托/成交/Projection watermark；④至少跨物理故障域复验安全恢复，以及自动归档与WAL清理。**基础异步续传和严格多数B故障验证PASS；完整Common上线GO仍NO-GO。**

## 2026-10-23｜Common 跨Epoch故障准备：真实SIGKILL A + 独立提交证书持久化保管

- 仅对完全隔离的`otc-common-ha-v19-signedack-clean`做真实`SIGKILL` Primary A；此时A/B/C WAL此前均为seq5050，且旧Primary A卷上存在`commit-00000000000000005050.bin`多数证书。A停机后分别对B/C真实Common Netty请求交易，**两者均返回503**（本地无可验证的权威Common CommitIndex），安全拒绝未授权冒险提升；重启A后再次确认A原始证书及所有数据保留，A/B/C物理WAL均529928bytes，SHA256同`a0e5d0e001ada91b305d36d84653627cb53080402f39c3ea87e8f66d7b882712`，A重新获得epoch1授权。**本轮仅证明fail-close，不是Primary自动升主成功**。
- 确认核心阻塞：目前Strict Common CommitIndex只在A磁盘，证书由A当场产生并向客户端ACK，而B/C仅追WAL；已确认的最高水位缺独立节点物理保管证明。仅凭A/C或B/C WAL SHA相同，不能允许跨Epoch升主；必须先完成**证书自身的多数节点持久化回执**。
- 已在Common3.0.22-SNAPSHOT实验源码分支新增`DurableWalCertificateCustody`（每节点独立物理证书安装：RSA原Membership验签、真实本地WAL fsync前缀匹配、旧Epoch双授权检查、独立排他文件锁、temp force→atomic rename→目录force、重启验签、回退/篡改/脏pending文件拒绝）与`DurableWalCustodyQuorum`（独立于WAL复制回执的`OTC_COMMON_CERT_CUSTODY_V1`域RSA签名、多物理节点多数唯一身份验证、确切旧epoch/seq/hash/membership一致）。特别：该证明的`authorizesPromotion=false`，不能当作ZooKeeper新Epoch授权。
- Common本地实验分支提交**`e458914`**，没有push或发布中央仓库。源码完整按JDK8构建，统一候选Jar SHA256=`cbe4955cde3532248fa025118dab961758b5147ad0816a55aa8a043d2873142f`；新增独立物理证书保管**7/7 PASS**，Common关联测试**24/24 PASS**，Demo全部**131/131 PASS**。测试涵盖真实文件刷盘、持久保管后重启、旧Epoch撤权、无WAL或前缀不符、错误/重复RSA签名、多数保管、证书回退/篡改等。
- **仍是基础机制而非完整链路**：尚未通过Common Netty把刚提交的证书可靠安装到B/C，也尚未在A向客户返回严格ACK前要求**物理证书2/3多数保管签名**，更没做跨Epoch真实自动升主、旧主隔离+权威最高水位发现/候选完整业务状态恢复。下一步应先做签名证书的安全Netty传送与副本落盘及ACK门禁，再接Common的ZK failover controller，让新Primary在恢复到至少最高已对外ACK的数据且新Epoch授权有效时READY；任意失败必须fail-closed。无自行伪造新主或脚本强制选主。
- 磁盘资源风险：截至本轮Mac宿主盘使用率已达**95%（约24GiB可用）**。进行下一次200真实租户长时间测试前应只审计可删的旧无引用测试工件；**不可误删在用WAL、Docker数据卷、证书、正式服务**。证据`work/common-ha-netty-v19-control-cache/V19_PRIMARY_KILL_DURABLE_CERT_CUSTODY_20261023.zh-CN.md`。正式OrderTradeMD、默认Docker环境完全不动，当前完整HA **NO-GO**。

## 二、固定实施里程碑

1. **明确 Common 复用边界、Demo 验证基线与可量化验收目标**（`scope`）
2. **独立控制线程与有界可撤销 epoch/fencing 授权，业务 WAL 零 ZooKeeper RPC**（`control`）
3. **实现 WAL group commit 与三类水位，恢复保持 crash-consistency**（`wal`）
4. **实现异步 TCP 批次流水线、累计 durable ACK 与版本兼容**（`tcp`）
5. **将历史全量状态 SHA256 移出交易 ACK，改为独立对账与可审计证明**（`audit`）
6. **完成 v17/v18 优化对照、10/50/200 租户负载和 P50/P95/P99 验收**（`perf`）
7. **完成失多数、双主隔离、SIGKILL、污尾恢复和零丢失/零重复故障注入**（`safety`）
8. **将经 Demo 验证的 Common API 沉淀为可复用版本，再接入 Order/Trade/MD**（`adopt`）

## 三、完成条件（必须逐项验收）

1. Common 核心具备稳定、业务无关的状态机(byte[])、WAL、快照/Diff、复制、控制面和恢复 API，未来不同服务无需重复实现 HA。
2. 所有业务/WAL 热路径同步 ZooKeeper RPC=0；失多数、授权过期、旧 epoch 阻断，主切绝无双主。
3. 正常预热负载下完整交易端到端服务端 p99≤30ms，性能分段监控，内存索引查询 p99≤5ms；无正常秒级请求。
4. 批量 WAL fsync 和异步 TCP 持久化 ACK 确认边界正确；已确认数据丢失=0、重复应用/重复成交=0。
5. 在 Demo 独立完成故障恢复、旧主隔离和权威一致性审计，日志/快照恢复可追溯且具备证据。
6. 完成 10/50/200 租户负载、突发与容量边界验收，并记录 p50/p95/p99/TPS/错误率/复制滞后。
7. Compact-ACK 协议版本化并解决旧客户端兼容，完整摘要转移至后台审计/检查点。
8. 只有 Demo 验收通过后，才将稳定机制应用于正式 Common 和 Order/Trade/MD；不得直接将实验 v18 发布正式服务。

## 四、工作纪律与验证边界

- **Demo 是验证手段，不是终点。** 不允许 Demo 私有 HA 实现长期替代 Common，也不允许 Order/Trade/MD 分别维护三套复制、选主、恢复框架。
- **优先 Common 机制抽象。** Business service 注入状态机 `apply(byte[])` / `snapshot()` / `installSnapshot(byte[])` / 可选 `diff(byte[])`，Common 必须独立于任何交易业务。
- **严格区分实测和目标。** 单纯异步 TCP 不等于可靠提交，单次测试通过不等于稳态 P99 达标，异步 ACK 不得绕开持久化和 fencing。
- **安全红线不可降级。** 已确认数据不丢、无重复成交、无双主；A/B 单副本降级必须说明故障风险，不得宣称仍保有多数持久化容错。
- **发布节奏。** v17 保留兼容基线；v18 Compact-ACK 仅实验，待协议兼容、ZK 热路径隔离、group commit、故障注入、真实多租户压测全部通过后，再合并、发布 Common，并回归正式 Order/Trade/MD。
