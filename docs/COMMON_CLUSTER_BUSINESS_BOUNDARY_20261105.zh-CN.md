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

## 4. 实施顺序（不因某个服务缺 Bean 而改变）

1. **Common 完成统一生产物理恢复执行器**：从 Common 打开的 WAL、已认证原始成员/签名/物理状态构建恢复计划；完成旧主撤权、Replica 独立持久化验证、Snapshot+真实原始 WAL 安装、双物理签名/READY。不能凭回调有值即宣称完成；单向复制、单节点可工作及风险等级由统一 Common 策略决定。
2. **Demo + Common 实测验收**：真实 3 ZK、两独立 JVM A/B、严格提交；A SIGKILL→B 自动接管→A 恢复追平→B SIGKILL→A 自动接管→B 追平、持续读写。检查无重复/丢失、旧主不可写、原始 WAL/快照/业务状态一致；测量停写与回切时长、分区是否全部回 Home。重复多轮，禁止依赖外部脚本替代自动选主。
3. **同一个 Common 版本接 Order/Trade**：只传入现有业务 StateMachine/Codec，移除业务侧物理选主、恢复 Stage、Snapshot 认证、READY 实现与多余 Bean，真正使用与 Demo **同一启动入口**；编译/测试和 Spring 启动审计都通过后部署。
4. **真实 SaaS E2E**：全新租户注册→自动审批→Robot Maker/Tape 连续报价及真实成交→资金、持仓、委托、成交、Projection 一致；交易持续进行时做上面的 Order/Trade A/B 故障切换；接着 10→50→200 真实租户 steady/burst、Order/MD 恢复与归档巡检。任何步骤未实测通过均不得写 GO。

## 5. 源码边界检查

本仓 `tests/check-common-business-boundary.py` 以 `--common`、`--order`、`--trade` 指定源码根。`--mode business` 检查业务状态机与资金应用器没有物理选主/Stage 实现；`--mode production` 增加严格生产门禁：业务目录不应注入 `DurablePhysicalRecovery`，Common 必须实际拥有可识别的统一生产执行器（不是“自动计划接口”）。目前只允许业务边界检查通过；生产完整门禁应维持 **FAIL/NO-GO**，直到 Common 真正提供自动执行器后才解除。

**统一标准**：今后新增 Wallet、Position 或任何需要集群的服务，只实现业务 `ReplicatedStateMachine` 的 codec/callback；集群 Bug 在 Common 修一次，Demo 验证一次，所有业务服务复用；严禁复制物理恢复流程。
