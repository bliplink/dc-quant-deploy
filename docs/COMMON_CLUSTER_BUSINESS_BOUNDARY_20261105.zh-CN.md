# Common 集群唯一实现边界与新服务接入契约

> **长期架构约束（2026-11-05 生效）**：先完成 **Demo + Common** 的生产级 A/B 恢复验收，Order/Trade 仅实现业务状态机和原始数据编解码。将来增加任何业务服务，只接入同一个 Common，不再开发/复制集群。此约束优先于为个别服务临时补齐 `Bean` 或增加独立的恢复流程。

## 1. 唯一的集群实现只能在 Common

Common **独占**：ZooKeeper/节点存活与租约、每分区主备及 Home 布局、故障发现、撤权/fencing、Epoch/Stage、RSA 签名及双节点物理证据、TCP 单向复制、WAL/CommitIndex/Custody、严格/降级 ACK 策略、Snapshot 定时调度及文件封存、原始 WAL 安全回放、恢复进度及持久化账本、自动 A→B→A、双向追平、对外 READY、归档/删除、恢复锁和所有验证。协议必须与业务语义无关（不能出现订单类型、持仓类别等分支）；ZooKeeper 不进入交易 WAL 热路径。

业务服务 **仅负责**：以分区为单位实现已有的 `com.app.common.replication.ReplicatedStateMachine` / `ReplicatedStateMachineFactory`，在 Common 提供的独占恢复栅栏内：

- `apply(byte[] command)`：解释、校验、应用**已由 Common 认证提交**的原始业务命令；Order/Trade 自己决定订单/余额/仓位等业务规则。
- `snapshot(ChunkSink sink)`：序列化该分区完整、一致的业务状态；快照水位、物理封存及持久化由 Common 完成。
- `restore(ChunkSource source)`：解析并原子替换已验证的完整业务快照；不自行授予 READY。
- `finishReplay()`：执行回放结束后的业务收尾和去重检查；Common 独自认证最终水位与 READY。

行情 Snapshot/Diff 类型可使用已有 `SnapshotDiffStateMachine`，**不允许**另建选主/恢复协议。业务代码只能配置服务名、物理目录、RSA 身份及端点等参数，必要的 Spring Bean 只能是 Common 启动入口的薄配置绑定，而不是一个独立 HA 执行器。

## 2. 明令禁止业务仓实现的内容

任何新的 Order/Trade/其他业务 PR 都不得新增：集群选主/Watch/租约监测、分区 Epoch/Stage 状态机、业务私有 WAL/复制或 ACK 机制、Snapshot/Manifest 物理协议、恢复来源证书及本地签名、READY 发布、物理节点故障切换器。不得通过空实现、mock、测试凭据、跳过认证或 `@Bean` “补齐依赖”使启动假通过。*业务 Snapshot 的编解码、业务 WAL 帧解析与资金一致性检查不属于集群实现。*

出现业务适配困难时：**先在 Demo+Common 复现并修好统一能力**，然后 Order/Trade 仅修改必要业务解析，不得绕过 Common 自建流程。故障先收集日志、代码路径、可复现输入和影响范围，再修复、回归、部署。

## 3. 已有代码与当前边界问题

- Common 已有通用 `ReplicatedStateMachine`、`PartitionStateMachineRegistry`、物理 Snapshot/WAL/Netty 与签名校验实现；Order 和 Trade 已实现自己的 `OrderRecoveryStateMachine` / `TradeRecoveryStateMachine`，因此**不要另造第二套接口**。
- T493/T494 隔离的 Order/Trade 真实业务 Snapshot@1 + 认证 WAL@2 回放测试通过，但不代表生产 ZooKeeper A/B 自动恢复通过。T492 两 JVM 256 分区、双物理 RSA WAL 一致性及 Common 定期业务 Snapshot 局部通过，200 为**模拟租户**，不是 200 真实 SaaS 租户。
- T495 已将 Trade 业务状态机对 `CommonCertifiedFailoverCoordinator/Stage` 的直接依赖移出，Common 的 `CommonCertifiedRecoveringBusinessFence` 在恢复阶段撤权时拒绝继续应用业务；Trade 只校验快照/资金/仓位/去重语义。该变更本身**不**发布 READY 或闭合生产自动恢复。
- **当前生产 NO-GO：** `CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery` 的真正生产物理执行器及其原始双 RSA/旧主隔离/新 Epoch Snapshot+WAL 安装仍未闭合。现在 Order/Trade 的 `orderCommonCertifiedPhysicalRecovery` / `tradeCommonCertifiedPhysicalRecovery` Spring 引用没有真实统一实现；不得让业务服务各实现一份。应由 Common 自身实现及管理，然后移除这两个业务专用依赖。
- **已定位 Common 核心生命周期断点**：`CommonCertifiedNodeBootstrap.openAndStart(...)` 对 `!assignment.isRoutable()` 直接拒绝打开，而 `CommonRecoveringNodeRuntime.requireBusinessReady()` 明确持续拒绝业务 READY。两个入口各自安全但未组成 RECOVERING→已认证 Snapshot+WAL 安装→独立签名/旧主撤权→READY→新物理节点接管的自动闭环。必须在 Common 内复用两者并完成切换/重新打开节点，不能让 Order/Trade 根据 Spring 配置自建第二套生命周期，也不能把 RECOVERING 入口改成直接接受写入。

### T495 已验证证据与远端同步（2026-11-05）

1. Common 新增的物理恢复栅栏为 `final` 类型，**构造器私有**，工厂需真实的 Common 协调器、签名 Stage、精确恢复请求和物理节点；使用前、业务分区锁内及使用后重新检查 Stage。业务资金模块不能传入任意 `Runnable` 假装授权。
2. Trade 业务状态机仅接收 Common 颁发的恢复凭证，不再持有 `FailoverCoordinator/Stage`；资金恢复器只执行领域数据校验和修改。Order 业务状态机原已按 `ReplicatedStateMachine` 接口执行，没有增加 HA 代码。
3. **从 GitHub `saas-crypto-latest` 实际下载新代码重新编译运行**：`TradeSignedNonRoutableFundsRecoveryTest`（资金、持仓、去重与撤权）和 `TradeCommonPhysicalBusinessSnapshotIntegrationTest`（真实双 RSA Snapshot@1 + WAL@2）`2/2 PASS`。另行重新运行 `OrderCommonPhysicalBusinessSnapshotIntegrationTest`，真实 Order Snapshot@1 + WAL@2 回放 **1/1 PASS**。这是业务和物理回放回归，**不**代表生产 A/B 自动互切已验证。未修改运行中的 Demo 容器。
4. `tests/check-common-business-boundary.py --mode business`：**PASS**；`--mode production`：**FAIL（预期）**，明确检测 Order/Trade 业务专属物理恢复 Bean 依赖、Common 完整生产执行器缺失。严格门禁保持不放宽。

### T496–T499 最新落实与验收

- **T496**：Order、Trade 的 `*CommonRecoveryBinding` 均已只保留 `businessRegistry(request)`，物理安装、E1/E3 恢复及低级恢复执行方法已删除；两项领域工厂反射/非法 v2 入口测试 **2/2 PASS**。
- **T497**：Common `CommonCertifiedNodeRuntime` 现在必须在签名 READY 发布之前验证业务 Snapshot + WAL 安装及分区已认证回放；无生产安装器默认拒绝。Common 七组 **60/60 JUnit PASS**。
- **T497 Demo**：实际 A SIGKILL→B 接管→A 重启追平→B SIGKILL→A 接管→B 重启追平，最终业务状态 **85 / 7**，第三节点 C 的独立 RSA 授权及新 TCP fsync 全部通过。故障时客户 ACK 采用清楚标识 RPO 风险的 `LOCAL_DURABLE_ASYNC`，**不得记成 STRICT**。
- **T498**：真实在线 E3 A/B 两 JVM 关闭旧物理 WAL/Netty、各自 RSA 签署退休后，独立业务恢复 **85 / 7** 并签署 E4 证据，在三节点 ZK 单次发布 E4 `STRICT_QUORUM READY`，真实实测 PASS。
- **T499**：T498 E4 READY 上新发两条物理业务操作，A/B 双写 fsync、CommitIndex/Custody 客户 ACK 为真实 `QUORUM_DURABLE`，B SIGKILL 后 A 下一条**拒绝伪造客户 ACK**。隔离 P090 实测 PASS。
- 完整证据参见 [T497–T499 验收记录](T497_T499_COMMON_LIVE_STRICT_RECOVERY_AUDIT_20261105.zh-CN.md)。这些是隔离 Demo 验收，**不是**生产 256 分区自动 HA/Order–Trade 业务完整 GO；Common 真正统一的生产 `DurablePhysicalRecovery` 执行器缺失、两业务专属 Spring qualifier 仍存在，生产门禁仍 FAIL。

### T503–T506｜统一 Common 的物理恢复装配落点

- **T503**：修正业务 Snapshot 水位已等于认证 WAL HEAD 时的零尾段恢复：原始 WAL 终止帧的摘要来自已认证的双物理投票者 Prefix，不能从空 WAL 合成帧；缺失、错误请求身份、篡改源仍拒绝。Common 原子提交 `ef3c3a1`，9/9 定向 Netty 测试 PASS。
- **T504**：Common 在物理工厂被调用前先验证 **所有 256 分区、全量分区标识与旧主 RSA**；即便最后一个分区非法，也不能先打开其他分区的恢复凭证。提交 `fa30022`。
- **T505**：增加 **`CommonCertifiedNodeBootstrap.openAndStartWithCertifiedAutomaticRecoveryFromOpenedPhysical`** 与通用 `CertifiedPhysicalRecoveryPlanFactory`。Common 从**本 JVM 已取得 ZK 授权且实际打开的物理 WAL/Custody** 构造自动恢复计划，在 Netty 监听启动前核对签名 Source 与当前 Replica 计划的完整性。真实 A/B Netty WAL、Replica 已 fsync 的 post-open 测试 PASS；错误节点身份、缺少任一必要计划均拒绝。此入口只是 Common 内已存在选主/恢复/READY 机制的统一装配，**不是另一个集群协议**。
- **T506**：只有真实认证的 256 分区全部为当前 JVM 的 Primary 时，允许 **256 Primary / 0 Replica Watch**；不是“缺失计划”自动当成功。任何实际 Replica 仍须绑定完整物理计划；节点角色需继续由 Common 当前 ZK、RSA、WAL 认证后才能对客户处理请求。**该启动特例不提供无副本的严格 2/2 客户 ACK**：失去 B 时严格模式必须拒绝缺失物理确认的交易，若需要继续写入，只能经既有 Common 第三方独立 RSA 授权且明确标注 RPO 风险的 LOCAL 策略。T505/T506 Common 6 文件原子提交 `4948c1c`。
- **交叉编译及回归**：同一 T506 完整 Common JAR（SHA-256 `04364dd84ca84647bff7de5d4e90a33923d69a8b5872c50ddbb613538874b5e7`），Common 330 个 Java 8 源文件、Order 123 个、Trade 173 个编译 PASS，Common 十组 **72/72 JUnit PASS**。本地证据 `.work/t506-common-full-release/`。
- **尚未完成：** Common 的统一生产 `DurablePhysicalRecovery` 具体执行器仍需将旧 Epoch 原始 WAL/双 Custody、签名 Stage、Replica 独立追平、业务 Snapshot+WAL 安装及双 RSA READY 端到端接好，并从**同一个 Common 入口**供 Demo 和所有业务复用。T505 是该入口和真实物理源装配边界，**不是**已具备全部生产恢复证明的完成声明。Order/Trade 当前仍存在业务专属 `orderCommonCertifiedPhysicalRecovery`/`tradeCommonCertifiedPhysicalRecovery` Spring qualifier；不能靠空 Bean 解锁，正式启动门禁仍 **FAIL / NO-GO**。

### T507｜删除 Order/Trade 私有物理 Bean，保留完整生产门禁（2026-11-05）

- Order `e9c426fc44d7b67aba5461282fa7e4ed10ce76` 与 Trade `929bdb3f8f1f06f4d20b4353d155cd30de50e606`：删除业务层 `*CommonAutomaticReplicaPlans` Spring Bean、`orderCommonCertifiedPhysicalRecovery`/`tradeCommonCertifiedPhysicalRecovery` 专属集群依赖；两个 `*CommonNodeRuntimeWiring` 改为注入 Common 通用 `CertifiedPhysicalRecoveryPlanFactory` 并只调用 `openAndStartWithCertifiedAutomaticRecoveryFromOpenedPhysical`。业务侧只保留已存在的 opaque Snapshot/WAL 原始数据源与领域状态机，不再装配物理 HA。
- Order 全量 123、Trade 全量 173 Java8 源码使用 T506 同一 JAR 编译 **PASS**。更新 `tests/check-certified-auto-recovery-wiring.py` 和 6 项反向测试，校验业务端不能添加物理恢复 Qualifier/Bean，也不能调用旧 pre-open 启动入口；源码层 **PASS**。`--mode business` 持续 PASS。
- **明确仍 NO-GO**：Common 尚未注册可执行的生产通用 `CommonCertifiedProductionPhysicalRecovery`（含实际 RSA Stage、物理旧 WAL + 双 Custody、独立 Replica 追平、按业务快照/后续 WAL 恢复、第三方降级/双 RSA READY）；所以本轮只修复业务侧错误依赖，不能宣称新版 Order/Trade 自动 HA 可以部署。旧 Demo Order/Trade/Robot 保持原样运行。升级门禁持续保持 FAIL，禁止用空 Bean/自动 return true 绕过。

### T509–T511｜同一个 Common 业务 WAL 接口、全 Replica 稳定注入（2026-11-05）

**服务接入契约不变：业务只实现 `ReplicatedStateMachine` / 原始 `byte[]` 编解码、Snapshot、业务状态应用；所有物理 ACK、WAL fsync、选主、主备恢复、独立 RSA 和 ZooKeeper 授权均归 Common。** 新服务不得新增自己的一套 `DurablePhysicalRecovery` Spring Bean、选主 Watch 或复制协议。

- **T509 Common `dd62ad1`**：LOCAL 故障期的 `CommonCertifiedDegradedPrimary.commitThenApplyLocal(encoder,applier)` 接受相同的 partition/epoch/seq 原始业务字节，返回真实 `LOCAL_DURABLE_ASYNC`（`quorumDurable=false`）。WAL 已 fsync 而业务应用失败会永久隔离该 writer，未落盘的编码失败不误封。新增 3 项 JUnit PASS。
- **T510 Common `2e57097`**：`CertifiedBusinessCommandRegistry.commitThenApplyCertified(partition,encoder,applier)` 是**唯一统一的业务写入口**，Common 根据已装配的真实严格物理 writer 或经过独立 C RSA 策略批准的 LOCAL writer 选择路径；`CertifiedCommitReceipt` 明确给出 `durability`、`quorumDurable`、`rpoRisk`、Epoch/seq。严格写入测试从两个独立 RSA/Netty 物理节点取得新 seq=2 的 `QUORUM_DURABLE`，LOCAL 测试明确 `rpoRisk=true`，不伪造严格 ACK。**77/77 Common 测试 PASS**。Order `206aeda` 的 4 处、Trade `643300c` 的 1 处业务编码回调切换成这个 Common 入口，编译与各 1 项真实业务 Snapshot＋WAL 后缀回放测试 PASS，无业务集群实现。
- **T511 Common `a283f2b`、测试 `9903985`、Order `6a8bcff`、Trade `55f52b9`**：启动时仅有 Replica 的节点仍注入**相同的** `CommonCertifiedNodeRuntime.requireCertifiedBusinessRegistry()` 实例，不再在 Spring 暴露 `null`。在真实签名 Primary 安装前该注册表为空，所有写入严格拒绝；Common 后续认证晋升会填充同一实例。单个分区 `RECOVERING` 不影响其他 READY 分区。真实 A/B 物理测试 31/31 PASS、Common 330 / Order 123 / Trade 173 文件 Java 8 编译通过。
- **真实 Demo+Common**：T509 对最新 Common 候选重新执行真实三 ZK、原 A/B 双 RSA、独立 C 签名见证、两次 SIGKILL，A→B→A 自动主备切换/副本追平、持续业务总计 **85/7 PASS**。故障期间 LOCAL 写入仍有不可取消的 RPO 风险，不可冒称永久 2/2；此前 T508 独立验证 E3→E4 恢复 STRICT 及两副本物理 ACK。
- **正式 HA 仍 NO-GO**：`CommonCertifiedProductionPhysicalRecovery` 这类真正由 Common 持有的生产自动物理执行器、Common 原始已打开 WAL/Custody 到签名恢复计划的装配、RECOVERING→真实业务回放→独立 READY→运行时接管尚未完整连通。生产门禁 `tests/check-common-business-boundary.py --mode production` 当前仍 **FAIL（预期、正确拒绝放行）**。此轮仅隔离回归，没有部署候选镜像到运行中的 Order/Trade；不得把静态接口编译成功表述为正式 A/B HA 通过。

### T512｜Common Watch 的 LOCAL 物理角色接管（2026-11-05）

- Common `53c794c`：`CommonCertifiedNodeRuntime.RecoveredPhysicalPartition` 提供新的可选 `requireRecoveredLocal(stage)`，**默认 fail-closed**；自动 Watch 仍必须先完成签名的 `RECOVERING`、旧 Replica 的真正 WAL 关闭、Common business Snapshot/WAL 的认证恢复、外部 READY 发布器、当前 ZK `LOCAL_DURABLE_ASYNC` 准入，再由 Common 运行时安装 `CommonCertifiedDegradedPrimary`。无独立物理授权不会变成严格 2/2 ACK。
- 新建 `CommonCertifiedLocalWatchInstallTest`：真实旧 E1 Replica OS WAL 关闭后，新 E2 LOCAL WAL 的 seq1 fsync、同一个 Common Registry 对业务有效、拒绝伪造 `QUORUM_DURABLE`，以及重启存在旧 LOCAL 写入时拒绝未验证的直接重开。该测试的 ZooKeeper/C 策略证明**明确为测试替身**，不能充当独立 C RSA 生产证据。
- Common **78/78** HA/LOCAL 回归，330 个 Common、123 个 Order、173 个 Trade Java8 同一候选 JAR 全源码编译 **PASS**。候选 `SHA256=a3243ab1757d64cd25249813c1e2dad49531c79ce267cd86de638b4ef83dd5d9`。
- **仍 NO-GO**：生产 `CommonCertifiedProductionPhysicalRecovery` 真实物理计划装配仍缺失；这项新增 Watch 接线并未证明正式 256 分区 Spring A/B 自动恢复，也未在生产上提供 E(n) LOCAL→E(n+1) STRICT 的完整同运行时无损轮转。不得增加 Order/Trade 的对应集群实现。

**T512 新候选真实物理回归补证（已完成，区别于测试替身）：** T512 Demo+Common 三节点 ZooKeeper、A/B 独立 RSA、独立 C 自动见证连续完成 A SIGKILL→B E2 LOCAL 继续写→A 追平→B SIGKILL→A E3 LOCAL 继续写→B 追平→TCP 复制至 **85 / 7**，证据 `~/.opentradingcore/t124-live-kill-runs/20261105190203`；随后**使用同一轮 E3 原始 WAL 历史**重新在两物理 JVM 上封存双 RSA E4 Snapshot：`~/.opentradingcore/t512-e4-baseline-20261105190425`。真正 E3→E4 旧节点退休、两个 E4 安装回执、三 ZK E4 `STRICT_QUORUM READY`：PASS；新 E4 A/B Netty 双 RSA/Custody 两笔客户写入真实 `QUORUM_DURABLE`、B WAL seq=2，之后 SIGKILL B，新写入拒绝假 ACK：PASS。证据 `~/.opentradingcore/t512-live-e3-to-e4-20261105190450` 与本地 `.work/t512-common-local-recovery/t512-e4-strict-ack-kill.log`。**Demo 物理回归已通过，但尚未把该完整执行器直接自动装配到正式 Order/Trade 256 分区 Spring 入口，生产仍 NO-GO。**

### T513｜LOCAL→STRICT 原始物理退休（2026-11-05）

- **Common 已提交** `42ed9b2`：在同一个 `CommonCertifiedNodeRuntime` 新增 `retireCertifiedLocalForStrictRearm`，仅用于经过授权的 **LOCAL→更高 Epoch STRICT 非 READY** 恢复。在任何真正关闭旧 LOCAL WAL 前，调用者必须提交 `CommonCertifiedStrictEpochRearm.Prepared`——由 Common 私有构造器生成、已经验证**两独立物理磁盘的完整 fsync WAL HEAD、两个原始 RSA 签名回执和一致的 Snapshot/成员/Stage 关系**。不再接受任意业务传入的 `head/sha` 作为物理认证。Common 还核查签名新 Epoch Stage、原始物理 RSA 不变、当前三 ZK RECOVERING，以及旧本地 writer 的原始 fsync 前缀，然后真实关闭旧 OS WAL，签发原节点 RSA 退休凭证并注销旧注册表；**并不**发布新 Epoch READY 或客户 ACK。
- **测试** `CommonCertifiedLocalWatchInstallTest`：先由 Common Watch 在测试 C 授权下将真实旧 Replica 退休并安装 E2 LOCAL 物理 WAL，再使用真实 B 和 A 两个不同目录独立 fsync 的相同原始 E2 WAL 和两份真实 RSA 回执生成 Common 私有 `Prepared`；完成真实 E2 B writer OS WAL 关闭和 RSA 退休，严格拒绝旧 writer / 尚未发布的 E3 STRICT ACK。新增该路径测试和 T512 原路径 **2/2 PASS**；Common 12 组 **79/79** HA/STRICT/LOCAL 单元与 Netty 回归 PASS。
- **同一个候选** `SHA256=6711965ba3c452d35b32d15b02a3016fcd9999a6c94a55cc19f557110c78b40c`，Common **330**、Order **123**、Trade **173** 个 Java 8 源文件全部编译 PASS；Order/Trade **无任何新集群实现**。
- **验收界限**：T513 的 C/ZK 外部授权是标注清楚的测试替身；原始 A/B 物理 WAL 和签名凭证是真实独立 fsync/RSA。此前 T512 Demo 真实 C RSA + 双 SIGKILL + E3→E4 STRICT 双物理持久提交已实测，但**尚未**验证 T513 新方法在同一生产进程中完成自动 E3→E4 及 256 分区，因此 **生产 HA NO-GO**。仍需 Common 的统一生产自动物理恢复执行器，并真实完成 Order/Trade 服务启动、业务 E2E、完整双向 HA。

### T513｜Demo 独立 C RSA LOCAL READY 校验正式下沉 Common（2026-11-05）

- Common `7feb1ec`：新增 `CommonCertifiedIndependentLocalReady.publishFromPersistedIndependentC(...)`，统一校验真实签名 `RECOVERING` Stage、旧主 ZooKeeper Ephemeral Lease 已失效、Replica 原始 WAL/CommitIndex、双 RSA Custody、业务 Snapshot+原始 WAL `REPLAY_COMPLETE` Ledger，以及**不属于 A/B 的独立 C 公钥和其真实签名文件**，由 Common 调用原有 `publishCertifiedDegradedReady` 发布 E2 `LOCAL_DURABLE_ASYNC`。业务层不能自行拼 `CommonExternalFenceCertificate.Intent`，不能自己构造旧主 physical fencer，也不能用 C 身份替代原 A/B 签名。
- Demo `DemoCommonLiveZkProcess` 删除重复的旧 WAL/Custody/C 签名验证和 LOCAL READY CAS 代码，直接调用 Common 上述服务无关入口。此次只发布该调用区域的最小源码差异，**没有混入**工作目录里尚未提交的 T466 压测修改。Order/Trade 不新增集群类，仍只提供业务 `byte[]` 状态机及既有恢复回放接口。
- 全量本地构建：**Common 331 + Order 123 + Trade 173** 个 Java 8 源码 PASS，共用候选 JAR SHA256 `2374f4b76ddf87944edb0ad6416a9c8d58a6953c5941718cac9a0e359e7d50f9`。Common 13 组 HA/Netty/双 RSA/LOCAL 验证 **80/80 PASS**，新增 4 种独立 C 缺失、旧 A/B 密钥冒用、业务回放未完成等负例全部拒绝 READY。
- **最新真实三 ZK / Docker 双 SIGKILL PASS**：在迁移后的 Demo/Common 类上，独立 C JVM 自动签发 E2/E3 许可，A SIGKILL→B E2 恢复并写至 60→A 重加入追平→B SIGKILL→A E3 恢复写至 74→B 重加入追平→A TCP WAL 向 B 签名 fsync，**双方最终 85/7 一致**。真实隔离卷 `~/.opentradingcore/t124-live-kill-runs/20261105193305`，Mac 日志 `.work/t513-common-independent-ready/t513-final-common-owned-old-lease-ababa.log`。故障窗口的客户凭证始终 `LOCAL_DURABLE_ASYNC`、`rpoRisk=true`，**不是 2/2 ACK**。
- **严格 NO-GO 不变**：Common 尚未完成供所有服务直接启动的 `CommonCertifiedProductionPhysicalRecovery` 全量计划自发现、真实业务快照及跨 Epoch 安装执行器；本次只完成了旧 STRICT E1→E2 LOCAL 的实际物理 READY 发布共用入口，不能宣称 256 分区生产 Order/Trade 自动 A/B 故障切换通过。候选镜像没有替换运行中的服务。

### T514｜同一份 T513 故障历史恢复到真实双副本 STRICT（2026-11-05）

- 使用 T513 的真实两次 SIGKILL 后 E3 持久化卷 `~/.opentradingcore/t124-live-kill-runs/20261105193305`，A/B 各自独立物理 JVM 用原始 RSA 签署新 E4 Snapshot，业务状态 **85 / 7**，无 READY/ACK 冒充；双签名基线位于 `~/.opentradingcore/t514-e4-t513-history-20261105194136`。
- T498 真实三节点 ZooKeeper、旧 E3 A 主/B 备停机与物理 WAL/Netty 关闭、两独立 RSA 退休证据、新 E4 A/B 业务回放与恢复回执、最终 `STRICT_QUORUM READY` CAS：**PASS**。证据 `~/.opentradingcore/t514-live-e3-to-e4-t513-20261105194158`，日志 `.work/t513-common-independent-ready/t514-t513-live-e3-to-e4-strict.log`。
- T499 在新 E4 双独立 Netty/RSA 物理节点实际新增两条业务数据，A/B CommitIndex、Custody 以及 B 的原始 WAL **seq=2**，客户端返回真正的 `QUORUM_DURABLE`：**PASS**。接着 **SIGKILL B**，A 新提交因缺少独立 Replica fsync 而报错，**无客户 ACK**：PASS。日志 `.work/t513-common-independent-ready/t514-t513-e4-quorum-ack-kill.log`。
- 所有 T513→T514 运行均使用同一 Common JAR SHA256 `2374f4b76ddf87944edb0ad6416a9c8d58a6953c5941718cac9a0e359e7d50f9`。历史 E2/E3 `LOCAL_DURABLE_ASYNC` ACK **不会**追认双物理严格提交。Order/Trade 正式自动 A/B 生产门禁仍 **NO-GO**，候选容器未部署。

### T515｜Common 通用生产自动恢复装配器 E1 阶段（2026-11-05）

- Common `430af44`：新增 `CommonCertifiedProductionPhysicalRecovery`，由 Common 自己实现 `DurablePhysicalRecovery` 与 `CertifiedPhysicalRecoveryPlanFactory`。自动恢复计划只基于运行时**已真实打开并 OS 锁定**的 256 个分区和实际签名 ZooKeeper 授权生成，不依赖 Order/Trade Spring 中的 128 个物理恢复 Bean。
- Common 从 `CommonCertifiedOriginalHomeLedger.requireBothOriginalRsaReceipts` 验证原始 256 Home（A/B 两个不同 RSA 物理签名）并自动派生本节点的 128 个 Replica。**先检查全部 128 份双 RSA Genesis；全部成功以后才允许调用任一业务状态机或创建恢复 Ledger**。业务接入只有 `BusinessPorts` 的状态机注册、业务互斥及原有 JournalBaseline，而不是自行选主/复制/持久化。正式 Order/Trade v2 不应回退到遗留的 v1 JournalBaseline。
- 已实装的 E1→E2 支路：真实打开的 B Replica 物理 WAL 和双 RSA CommitIndex/Custody、旧主 ZooKeeper 撤权、不可变签名 Stage、`CommonCertifiedGenesisSurvivorInstall` 的原始 Snapshot+WAL 事务回放，以及 `CommonCertifiedIndependentLocalReady` 的独立 C RSA 许可；签名 Stage 重试不会重复打开相同旧 WAL。新主 LOCAL 必须返回 `rpoRisk=true`，绝不可伪装 `QUORUM_DURABLE`。
- 回归：Common **83/83 PASS**；332 个 Common、123 个 Order、173 个 Trade Java 8 文件同一 JAR 编译 PASS；Order、Trade 原始真实双 RSA Snapshot@1+WAL@2 业务回放各 **1/1 PASS**。候选 JAR SHA256 `a96ddf56027cf3a1073dbab55ad31006133f31800fee076fdb0a7cc19731be7d`。本次未替换 Demo 运行容器。
- **严格 NO-GO**：该执行器目前只支持原始 E1 STRICT→E2 LOCAL，尚**没有**把 `CommonCertifiedCrossEpochSurvivorInstall`（E2→E3 跨 Epoch）、v2 原始业务 Snapshot 在 B 的真实自动预热和安装、E4 严格 RSA 双副本恢复，以及服务的单一 Spring 生产 Factory 完整接通。因此不能因为它的类名存在、编译通过或隔离 E1 测试通过，就放开生产门禁。正式 256 分区 Order/Trade A/B 自动切换、Robot/资金一致性验收仍待完成。
- 生产静态门禁 `tests/check-certified-auto-recovery-wiring.py` 解析实现声明时已支持 Java 正常换行，但仍要求 Common 真实 E3/跨 Epoch 原语和完整 E2E；不得为使脚本变绿而添加空回调、字符串标记或假签名。脚本变绿仍不能替代真实 HA 业务验收。

### T516｜Common 原生 byte[] v2 无二次业务日志的 A/B/C 故障恢复（2026-11-05）

- Common `aa971d6`：新增 `CommonCertifiedOpaqueGenesisSurvivorInstall.install`，严格从 B 的原始 **A/B 双 RSA 签署 Genesis@0**、B 已 fsync 的原始物理 WAL、两份签名 Custody HEAD 读取每一个提交的原始业务 `byte[]`；使用 `RecoveryRequest.opaqueFrames`、`CommonCertifiedSurvivorRecoveryAuthority` 和 `DurableRecoveryTransactionControl.forOpaqueCommittedWal` 完成 **真正的 v2 恢复和 `REPLAY_COMPLETE` ledger**。完全不创建旧 Demo 的第二份 STATE/STATE_COMMIT 业务 JournalBaseline，也不代替独立 C RSA 发布 READY。
- `CommonCertifiedProductionPhysicalRecovery.OriginalE1` 新增显式 `opaqueV2` 持久恢复模式；v2 明确禁止非空第二份业务 JournalBaseline。基于两 RSA 签署的 256 Home 自动派生 128 个 Replica，`originalE1FromPersistedHome` 默认选择 v2，仅业务 `ReplicatedStateMachine`／Snapshot／互斥应用接口由新服务提供。旧 v1 仅作为显式兼容测试分支。
- **真实三 ZK＋独立 C RSA＋两次 SIGKILL** 已在独立新环境按 v2 全链路测试 PASS：A 死→B E2 恢复 `40→60`；A 追平；B 死→A E3 恢复 `60→74`；B 追平，A/B 最终 **85 / 7** 并完成真实 TCP RSA WAL fsync。测试数据 `~/.opentradingcore/t124-live-kill-runs/20261105203653`；日志 `.work/t516-common-opaque-v2-genesis/t516-real-v2-two-sigkill-with-C.log`。第一个原型 JAR 不完整只打包主 class，实际 E1 恢复曾失败 `NoClassDefFoundError`，已根因定位并在全源码 JAR 修复（不能误报为业务算法故障）。
- 同一 v2 历史已继续 E3 LOCAL→E4 STRICT，真实 A/B 两份独立 RSA 退休与恢复回执、ZK READY、Netty 双 Replica fsync 到 **seq=2** 后提供真正 `QUORUM_DURABLE`。再次 SIGKILL B 时正确拒绝客户虚假严格 ACK。签名基线 `~/.opentradingcore/t516-e4-v2-history-20261105203945`；E4 证据 `~/.opentradingcore/t516-live-v2-e4-20261105204007`。
- **Common 84/84 项 HA 回归 PASS**，Common 333、Order 123、Trade 173 个 Java 8 源文件使用同一 Jar 编译 PASS，JAR SHA256 `852bd211a420d50ba457c739d20fb2c1c7ce4fed70b27c6e0e16647cd6080961`。新增 v2 严格拒绝第二份业务日志 JUnit PASS。发布源码分支 `saas-crypto-latest`，Demo 为显式测试开关，未替换正在运行的业务服务。
- **仍然 NO-GO**：上面验证的是独立真实 Demo/通用 Common；正式 `Order/Trade` 全 256 分区容器尚未通过生产 auto-plan 的跨 Epoch E2→E3 物理接入、非零业务 Snapshot 在 Replica 的真正可恢复安装、资金/委托/Projection/Robot 在容器的连续一致性验收。当前 Common 通用生产执行器 E1→E2 已实装，但不可冒称 E2/E3/E4 在服务启动即自动接通。

### T517｜真实签名 RecoveryRequest 交给业务状态机工厂；完整故障链路复验（2026-11-05）

- Common `41720ce`：增加只涉及业务的 `CommonCertifiedBusinessStateFactory.businessRegistry(Common 原始认证 RecoveryRequest)`。业务**仅**实例化本来就有的 `ReplicatedStateMachine`（Snapshot restore／原始 byte[] apply）；不接收也不能制造 ZooKeeper Stage、RSA、WAL、READY 或 ACK。Order `OrderCommonRecoveryBinding` 和 Trade `TradeCommonRecoveryBinding` 已沿用该统一接口，无重复实现集群协议。
- `CommonCertifiedOpaqueGenesisSurvivorInstall` 在原始双 RSA Genesis@0 与真实 B Replica WAL/Custody 完整验签以后，才调用工厂，并传给业务有权威物理 HEAD 的 `RecoveryRequest`。`CommonCertifiedProductionPhysicalRecovery` 将此次**真正完成回放的状态机实例**与签名 Epoch 绑定，后续 E2 LOCAL writer 使用**同一个已恢复对象**；若对象／业务回放缺失则拒绝新增 writer，避免回放到 A 对象却对空的 B 对象开展交易。
- 排除了旧候选 JAR 的 `NoClassDefFoundError` 和 Demo 代码／Common JAR `NoSuchMethodError`：将当前 **334** 个 Common Java 8 源文件一次性编入不可变候选 JAR，显式验证 v2 两个 overload 和内部类齐全。真实统一 JAR SHA256：`3a1bea7408c6ef6c84ef9d48a736eb6680ec7e55b49f85ac3d3d56e990a13bc7`。
- 同一最新 JAR：Common 15 组 HA/原始双 RSA/Netty/业务 v2 回归 **90/90 PASS**；Order **123**、Trade **173** 个 Java 8 源码兼容编译 PASS；Order 委托和撤单、Trade 资金／仓位真实 Snapshot@1 + 原始 WAL@2 回放各 **1/1 PASS**。
- **真实三 ZooKeeper + 两个 SIGKILL 复验 PASS**：A 主 E1 原始双 RSA ACK → SIGKILL A → B E2 Common v2 原始 WAL/业务回放并获独立 C RSA 签名 LOCAL READY → B 写至 60 → A 重加入独立 fsync 追平 → SIGKILL B → A E3 自动 RECOVERING/跨 Epoch E1+E2 WAL 回放，独立 C RSA 授权 → A 写至 74 → B 追平 → A TCP 原始 WAL→B 签名持久化，双方 **85/7**；E2/E3 历史客户端 ACK 均为 `LOCAL_DURABLE_ASYNC` 且 `rpoRisk=true`。完整证据卷 `~/.opentradingcore/t124-live-kill-runs/20261105214503`；日志 `.work/t517-common-v2-factory-repack/t517-full-3zk-two-sigkill.log`。
- **严格模式恢复 PASS**：由同一历史 A/B 独立签名 E4 Snapshot、真实 E3 旧 WAL/Netty 关闭、独立旧 Epoch RSA 退休和 E4 业务回放回执，完成 `STRICT_QUORUM READY`；新 E4 实际双 RSA/Custody/Netty 持久 ACK `QUORUM_DURABLE`（seq=2），随后 SIGKILL B 时无双副本 fsync 的新写入正确拒绝 ACK。日志 `.work/t517-common-v2-factory-repack/t517-live-e3-e4-strict.log` 与 `t517-e4-strict-ack-kill.log`；证据卷 `~/.opentradingcore/t517-live-e3-e4-v2-20261105214746`。
- **剩余 NO-GO 范围**：以上是单分区 Demo＋Common 真实 JVM/三 ZK 验收，不等于 **256 分区正式业务生产自动 HA**。Common 的生产 `CertifiedPhysicalRecoveryPlanFactory` 尚需把 E2→E3 历史和 E4 STRICT 物理安装、C 许可的真实证据目录、v2 每分区业务快照恢复、Spring 通用自动注册配置贯通；正式 Order/Trade A/B 双向切换、Robot 交易、Projection／资金和 10→50→200 租户持续压测尚未实际通过，不应释放生产门禁。运行中 T488 Order/Trade 和 Robot 未被本轮测试替换。

### T518｜第三个业务服务通用接入 Common：去除首次部署／恢复的 Order/Trade 服务名写死（2026-11-05）

- Common `5988acd`：新增 `CommonCertifiedServiceIdentity.requireConfigPrefix`，统一服务名和属性前缀映射。改造 5 个**原有 Common 类**：`CommonExclusiveBusinessClusterStartup`、`CommonOriginalE1SignedMembersSource`、`CommonOriginalE1FleetBirthProvisioner`、`CommonRecoveryOnlyProcess`、`CommonOriginalE1FirstReadyActivation`；不增加任何新选主、Watch、WAL 或恢复协议。原 `OrderSvr -> order`、`TradeSvr -> trade` 的历史配置及证据目录继续兼容。
- 新服务例子：在其**唯一一份 Common 配置**中显式填写 `common.cluster.service=RiskSvr`、`common.cluster.configPrefix=risk`、`risk.common.nodeRuntime.service=RiskSvr`，以及已有 Common 必需开关、真实 RSA/ZK/证书／物理根目录；注册 `CommonCertifiedBusinessStateFactory.businessRegistry(Common 已认证 RecoveryRequest)`。无需创建服务专用选主、复制、确认、READY 或自动恢复实现。严禁凭服务名推断或借用 `order`/`trade` 根目录；服务名与签名物理身份或配置不一致必须拒绝启动。
- 新增拒绝放行测试：第三业务服务 `RiskSvr` 的同一 Common RECOVERING 配置装配成功；冒用另一服务名、遗漏身份声明、复用 order/trade 前缀、非法属性前缀、开启任何旧集群 lifecycle/failover/replication，全部在物理启动前拒绝。第三服务与旧服务配置测试 **10/10 PASS**。最新 Common **335 个** Java 8 源码编译通过；17 组 Common HA/Netty/双 RSA/opaque-v2/签名 Home/第三服务 JUnit **100/100 PASS**；使用同一 JAR 的 Order **123**、Trade **173** 个 Java 8 源码兼容 PASS。Common JAR SHA256 `f2c6127c42b01d28f9e4ad1206511d83cc09c628c4d049f94697dda815e89f1e`。
- 真实 T488 业务容器的**只读**物理前置检查：四个 Order/Trade A/B 节点仍运行，镜像为各自现有 `full-source-no-go`，重启次数为 0；在 `/srv/dc/data/t488-born` 可发现各自 512 个 `genesis-e1.quorum` 文件，但**没有**在该卷或 `/srv/dc/data/t488-ready-v1` 发现 `*.original-home.rsa`。这意味着生产 Common 不能凭当前 512 个 Genesis 文件“推断”独立签署的 256 分区原始 Home：必须在正式集群启动阶段由 A/B 原始物理身份各自通过 `CommonOriginalE1SignedMembersSource` 认证、签署和双签验收，不能直接生成假签名或降低启动门禁。只读检查未更改运行中容器。
- **生产仍 NO-GO**：通用身份配置的静态和隔离测试不等于第三业务服务真实部署，也不等于 Order/Trade A/B 256 分区自动切换和 Robot/Projection/资金验收。Common `CommonCertifiedProductionPhysicalRecovery` 尚需真正自动装配跨 Epoch E2→E3、严格 E4、真实业务 v2 Snapshot 接收与各分区 signed Home，并经正式服务真实 SIGKILL/交易恢复验收。Demo 单分区已过，不得混写成生产 PASS。

### T519｜Common 双 Epoch E1＋E2 原始 WAL v2 恢复（代码测试标记 T518，2026-11-05）

- Common `e3e206b`：扩展 `StateMachineRecoveryCoordinator.RecoveryRequest.opaqueSignedE1E2PhysicalFrames` 和 `CommonCertifiedCrossEpochSurvivorInstall.installE3OpaqueV2`，由 **Common** 同时验证 E1 原始 A/B RSA Genesis、双 Custody／CommitIndex／原始 WAL、E2 B LOCAL 原始 WAL 和 A 独立 fsync 签名，再用连续逻辑序号完整重放业务 `byte[]`。**不需要** Order/Trade/Demo 第二套 JournalBaseline，也不允许把历史 LOCAL RPO 风险追认成双副本 ACK。
- 普通 `opaqueFrames` 仍**拒绝**非法的跨 Epoch Snapshot/head 组合；只有显式物理 E1→E2 请求能使用 Genesis@E1 / HEAD@E2（代码和物理原始 RSA 证据另行验签）。新建 2 项 JUnit 正反对照 PASS，正常 v1 和同 Epoch v2 行为保持不变。
- **真实三 ZK＋A/B JVM＋独立 C RSA 全 v2 验收 PASS**：E1 A 严格持久化→SIGKILL A→B E2 原始 WAL v2 回放／LOCAL READY→A 加入追平→SIGKILL B→A E3 用 `installE3OpaqueV2` 恢复原始 E1+E2 共 4 条 WAL，`REPLAY_COMPLETE`，业务状态 60→独立 C 授权 E3 LOCAL READY→A 写至 74→B 恢复追平并实测 TCP RSA fsync，最终 A/B 业务状态 **85/7**。E2 与 E3 两次恢复均没有额外 Demo 业务 journal，日志 `.work/t518-common-multi-epoch-opaque/t518-real-v2-e1-e2-e3-double-sigkill.log`；原始持久证据卷 `~/.opentradingcore/t124-live-kill-runs/20261105224952`，A 节点 `t456-returned-a.log` 包含 T518 原始 E1＋E2 物理业务请求和无双重 Journal PASS。
- 同一候选 Common JAR SHA256 `a1b9329fc034dba5647c194e9de0f617fb0bd6479e5254fcafdaae901e1b393e`：Common 15 组复用 HA/Netty／RSA／LOCAL／物理恢复 **86/86 JUnit PASS**；335 个 Common、123 个 Order、173 个 Trade Java 8 源码构建 PASS；Order 真实业务 Snapshot＋原始 WAL 委托撤单回放 **1/1 PASS**，Trade 余额／仓位结算回放 **1/1 PASS**。
- **新 v2 历史重新进入严格模式 PASS**：同一 E3 历史，A/B 分别 RSA 签署 E4 原始 Snapshot，完成三 ZK 下双 RSA E4 `STRICT_QUORUM READY`；A/B 原始 Netty/Custody fsync 至 seq=2，客户端返回 `QUORUM_DURABLE`；`SIGKILL B` 后缺少副本证明的新 ACK 被拒绝。证据 `~/.opentradingcore/t518-e4-live-strict-20261105225244`，日志 `.work/t518-common-multi-epoch-opaque/t518-e3-to-e4-strict.log` 和 `t518-e4-strict-two-rsa-ack-kill.log`。
- 本次只提交 Common 两个恢复协议文件、一个负例测试和 Demo 恢复集成测试的**最小修改**，没有给 Order/Trade 写任何集群逻辑。**生产仍 NO-GO**：这里的 E2→E3 v2 被真实 Demo 调用，但正式 `CommonCertifiedProductionPhysicalRecovery` 的 256 分区计划尚未与 E2→E3、E4 严格恢复、v2 非零 Snapshot 的自动生产装配以及 Spring 通用 Factory 真正接通。正式 Order/Trade A/B SIGKILL、Robot 交易、Projection／资金一致性尚未达到最终验收，运行容器未替换。

### T520｜Common 原始物理 WAL 单实例复用（2026-11-05）

- Common `a0ac0378c1d04a0750fc989f3bf3b1025c0c4950`：真实生产恢复流水线在 `CommonCertifiedOpaqueGenesisSurvivorInstall` 完成旧 B Replica 的双 RSA 原始 WAL、CommitIndex、Custody 和 `REPLAY_COMPLETE` 后，旧物理读取器仍由 Common Registry 持有 OS 共享锁。旧 `publishFromPersistedIndependentC` 再次打开同一 WAL 会触发 `OverlappingFileLockException`，导致正式 Spring 自动 Watch 无法发布 E2 READY。这是先前 Demo 在业务恢复后**提前关闭旧物理读取器**而掩盖的真实接线差异，不是增加新的 HA 机制。
- 新增 `CommonCertifiedIndependentLocalReady.publishFromAlreadyOpenedSignedSurvivor(...)`，使用**同一已打开的原始 E1 物理读取器**验证原始 A/B 成员 RSA digest、签名 WAL HEAD、双 Custody、真实旧主 ZooKeeper 撤权、持久化业务 Replay Ledger、独立 C RSA 及当前签名 RECOVERING Stage，再由 Common 原有唯一 `publishCertifiedDegradedReady` 发布 `LOCAL_DURABLE_ASYNC`。Common `ProductionPhysicalRecovery` 改为直接传入 `e.openedSignedOld`；绝不复制 WAL、重开文件锁、伪造 C 签名或追认 STRICT ACK。读取器寿命仍由 Common Registry 管理，缺失读取器直接拒绝。
- **真实隔离 Mac Docker＋三 ZooKeeper＋三个独立 RSA JVM、两次 SIGKILL**：先实测旧入口第二次打开同一 WAL 被 OS 锁拒绝：`T520_SECOND_OPEN_OLD_WAL_OS_FILELOCK_REJECTED_PASS`；随后在**不释放原 WAL 锁**的情况下新入口完成独立 C RSA LOCAL READY：`T520_COMMON_PREOPENED_SIGNED_WAL_REUSED_C_READY_PASS`。B 继续写至 60，A 追平，B SIGKILL→A E3 回放 E1＋E2 v2 WAL 至 60 并继续写至 74，B 重新加入最终双节点状态 **85 / 7 一致**。关键证据 `~/.opentradingcore/t124-live-kill-runs/20261105232042/t520-B-original-wal-locked-through-C-ready.log`，总日志 `.work/t520-common-preopened-wal/t520-strict-proven-double-wal-reader-full-ha.log`。
- 相同 Common 候选 JAR SHA256 `3ea53430102f5d9111bc0da842bf4a95308d008a1bdf58f71f48fa1115efaf35`：335 个 Common＋123 个 Order＋173 个 Trade Java 8 源码编译通过，Common **88/88** 项全量 HA 回归通过，另新增“不存在已打开物理证据不得 fallback 到成功”的单项负例通过。同一故障历史继续执行 A/B 两独立 RSA E4 Snapshot 和真实三 ZK E4 STRICT READY，随后 E4 真实客户端双 RSA／TCP／Custody `QUORUM_DURABLE` PASS，`SIGKILL B` 后无副本证明拒绝 ACK PASS。证据 `~/.opentradingcore/t520-e4-strict-20261105232404`。
- **正式 Order/Trade/Robot 生产 HA 仍 NO-GO**：该修复解决了 Common E1→E2 生产路径的确定性双开 WAL 阻塞，但 E2→E3 自动全分区工厂、业务 Snapshot v2 非零水位自动预热／安装、实际生产 Spring 256 分区注入与 Order/Trade 自动 A/B 完整故障交易一致性未验收。继续只在 Common 实现集群机制；Order/Trade 保持原有 `CommonCertifiedBusinessStateFactory` 的业务 byte[] 状态机接口。当前未替换运行中的 Order/Trade 容器，严禁将隔离 Demo PASS 误写为生产 GO。

## 4. 实施顺序（不因某个服务缺 Bean 而改变）

1. **Common 完成统一生产物理恢复执行器**：从 Common 打开的 WAL、已认证原始成员/签名/物理状态构建恢复计划；完成旧主撤权、Replica 独立持久化验证、Snapshot+真实原始 WAL 安装、双物理签名/READY。不能凭回调有值即宣称完成；单向复制、单节点可工作及风险等级由统一 Common 策略决定。
2. **Demo + Common 实测验收**：真实 3 ZK、两独立 JVM A/B、严格提交；A SIGKILL→B 自动接管→A 恢复追平→B SIGKILL→A 自动接管→B 追平、持续读写。检查无重复/丢失、旧主不可写、原始 WAL/快照/业务状态一致；测量停写与回切时长、分区是否全部回 Home。重复多轮，禁止依赖外部脚本替代自动选主。
3. **同一个 Common 版本接 Order/Trade**：只传入现有业务 StateMachine/Codec，移除业务侧物理选主、恢复 Stage、Snapshot 认证、READY 实现与多余 Bean，真正使用与 Demo **同一启动入口**；编译/测试和 Spring 启动审计都通过后部署。
4. **真实 SaaS E2E**：全新租户注册→自动审批→Robot Maker/Tape 连续报价及真实成交→资金、持仓、委托、成交、Projection 一致；交易持续进行时做上面的 Order/Trade A/B 故障切换；接着 10→50→200 真实租户 steady/burst、Order/MD 恢复与归档巡检。任何步骤未实测通过均不得写 GO。

## 5. 源码边界检查

本仓 `tests/check-common-business-boundary.py` 以 `--common`、`--order`、`--trade` 指定源码根。`--mode business` 检查业务状态机与资金应用器没有物理选主/Stage 实现；`--mode production` 增加严格生产门禁：业务目录不应注入 `DurablePhysicalRecovery`，Common 必须实际拥有可识别的统一生产执行器（不是“自动计划接口”）。目前只允许业务边界检查通过；生产完整门禁应维持 **FAIL/NO-GO**，直到 Common 真正提供自动执行器后才解除。

**统一标准**：今后新增 Wallet、Position 或任何需要集群的服务，只实现业务 `ReplicatedStateMachine` 的 codec/callback；集群 Bug 在 Common 修一次，Demo 验证一次，所有业务服务复用；严禁复制物理恢复流程。
