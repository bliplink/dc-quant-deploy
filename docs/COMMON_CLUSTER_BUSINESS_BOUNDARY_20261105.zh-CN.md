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

### T495 已验证证据与远端同步（2026-11-05）

1. Common 新增的物理恢复栅栏为 `final` 类型，**构造器私有**，工厂需真实的 Common 协调器、签名 Stage、精确恢复请求和物理节点；使用前、业务分区锁内及使用后重新检查 Stage。业务资金模块不能传入任意 `Runnable` 假装授权。
2. Trade 业务状态机仅接收 Common 颁发的恢复凭证，不再持有 `FailoverCoordinator/Stage`；资金恢复器只执行领域数据校验和修改。Order 业务状态机原已按 `ReplicatedStateMachine` 接口执行，没有增加 HA 代码。
3. **从 GitHub `saas-crypto-latest` 实际下载新代码重新编译运行**：`TradeSignedNonRoutableFundsRecoveryTest`（资金、持仓、去重与撤权）和 `TradeCommonPhysicalBusinessSnapshotIntegrationTest`（真实双 RSA Snapshot@1 + WAL@2）`2/2 PASS`。另行重新运行 `OrderCommonPhysicalBusinessSnapshotIntegrationTest`，真实 Order Snapshot@1 + WAL@2 回放 **1/1 PASS**。这是业务和物理回放回归，**不**代表生产 A/B 自动互切已验证。未修改运行中的 Demo 容器。
4. `tests/check-common-business-boundary.py --mode business`：**PASS**；`--mode production`：**FAIL（预期）**，明确检测 Order/Trade 业务专属物理恢复 Bean 依赖、Common 完整生产执行器缺失。严格门禁保持不放宽。

## 4. 实施顺序（不因某个服务缺 Bean 而改变）

1. **Common 完成统一生产物理恢复执行器**：从 Common 打开的 WAL、已认证原始成员/签名/物理状态构建恢复计划；完成旧主撤权、Replica 独立持久化验证、Snapshot+真实原始 WAL 安装、双物理签名/READY。不能凭回调有值即宣称完成；单向复制、单节点可工作及风险等级由统一 Common 策略决定。
2. **Demo + Common 实测验收**：真实 3 ZK、两独立 JVM A/B、严格提交；A SIGKILL→B 自动接管→A 恢复追平→B SIGKILL→A 自动接管→B 追平、持续读写。检查无重复/丢失、旧主不可写、原始 WAL/快照/业务状态一致；测量停写与回切时长、分区是否全部回 Home。重复多轮，禁止依赖外部脚本替代自动选主。
3. **同一个 Common 版本接 Order/Trade**：只传入现有业务 StateMachine/Codec，移除业务侧物理选主、恢复 Stage、Snapshot 认证、READY 实现与多余 Bean，真正使用与 Demo **同一启动入口**；编译/测试和 Spring 启动审计都通过后部署。
4. **真实 SaaS E2E**：全新租户注册→自动审批→Robot Maker/Tape 连续报价及真实成交→资金、持仓、委托、成交、Projection 一致；交易持续进行时做上面的 Order/Trade A/B 故障切换；接着 10→50→200 真实租户 steady/burst、Order/MD 恢复与归档巡检。任何步骤未实测通过均不得写 GO。

## 5. 源码边界检查

本仓 `tests/check-common-business-boundary.py` 以 `--common`、`--order`、`--trade` 指定源码根。`--mode business` 检查业务状态机与资金应用器没有物理选主/Stage 实现；`--mode production` 增加严格生产门禁：业务目录不应注入 `DurablePhysicalRecovery`，Common 必须实际拥有可识别的统一生产执行器（不是“自动计划接口”）。目前只允许业务边界检查通过；生产完整门禁应维持 **FAIL/NO-GO**，直到 Common 真正提供自动执行器后才解除。

**统一标准**：今后新增 Wallet、Position 或任何需要集群的服务，只实现业务 `ReplicatedStateMachine` 的 codec/callback；集群 Bug 在 Common 修一次，Demo 验证一次，所有业务服务复用；严禁复制物理恢复流程。
