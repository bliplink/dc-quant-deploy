# T489｜Order/Trade 自动恢复生产物理接线门禁（2026-11-05）

**最终结论：NO-GO，不能替换正在运行的 Demo Order/Trade，也不能报告业务自动双向 HA 通过。**

## 可核验已通过的底层证据

- Common T486 `target/t486-common-full-regression.log`：151 项测试通过；非空密封 Snapshot 完整读取、快照之后 WAL 后缀越界拒绝、篡改拒绝通过。
- Common T486 双 JVM 严格 256 分区：A/B 分别 128 Home、合计 540 条严格提交、跨节点逐分区一致；日志 `target/t486-256-strict-run.log`。
- Common T485 双 SIGKILL Demo：存在真实 A→B→A 及反向 Replica 追平证据；故障后明确有 `LOCAL` ACK、`rpoRisk=true`，不得反向追认为双节点严格 ACK。日志 `target/t485-two-sigkill-run.log`。
- Order T486：非空委托簿签名 checkpoint 读取 PASS；Trade T486：非空余额/持仓签名 checkpoint 读取 PASS。分别见对应 `target/t485-allsource-audit-v2/t486-nonzero-checkpoint-readback.log`。
- 完整 T486 Common JAR SHA256：`ac5d772e022bf82da63e5d51e6de3604ac32d274991bd25b00530a8dfe95b24e`。

上述不是生产 Spring 容器初始化、真实业务 READY 或新租户成交的证据。

## 生产根因（代码路径和重现）

1. `OrderCommonAutomaticRecoveryDependenciesWiring.physicalReplicaPlans` 明确需要名为 `orderCommonCertifiedPhysicalRecovery` 的 `CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery`；Trade 对称需要 `tradeCommonCertifiedPhysicalRecovery`。对两套生产源码搜索，均无定义该 Bean 的 `@Bean` 生产者。**这是两套默认自动恢复 Spring DI 依赖图未接通的直接阻断。**
2. Common `CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery` 要求四项真实实现：**签名 ZooKeeper Stage 协调器**、**独立持久化 Replica 追平**、**双物理 RSA READY**、**Snapshot+原始 WAL+业务回放后的物理安装**。现有 Common 测试中的实例故意在访问时抛异常，绝不可移植为生产 Bean。
3. `OrderCommonPhysicalProofWiring` 和 `TradeCommonPhysicalProofWiring` 当前只创建**空** `CommonCertifiedPhysicalEvidenceRegistry` 并构造验证器；Common `installSignedSurvivor(...)` 才能在真实签名阶段、物理源、旧主隔离的证据完整时安装旧 Epoch。两个业务生产启动路径没有调用。即使盲目补齐 Bean 名，也不能据此恢复或发布 READY。
4. 共用的 `CommonCertifiedAutomaticSourceWiring.forCertifiedOpenedNode` 已能在开启真实 WAL 后配置源端 HEAD/Manifest/Snapshot/WAL RPC，但**源端读取能力 ≠ 恢复安装执行器**；Demo 子工程的测试进程复用 Common API，不等于 Spring 生产路径已自动接通。
5. T489 只读复现命令：`python3 tests/check-certified-auto-recovery-wiring.py --order-common-jar .work/t488-latest-common-snapshot-images/order/common-certified-v2.jar --trade-common-jar .work/t488-latest-common-snapshot-images/trade/common-certified-v2.jar`；当前两 Bean 均为零定义，预期退出码 **2**。它是结构门禁，即使以后退出码 0，仍须做真实物理恢复与业务验收。

## 本轮完成及安全状态

- 已构建但**未部署**两份 ARM64 候选镜像：`local/otc-t488-ordersvr:common-t486-snapshot-v2-nogo`（image ID `sha256:43cee93b...`）、`local/otc-t488-tradesvr:common-t486-snapshot-v2-nogo`（`sha256:eb4526d3...`）。二者嵌入的 Common SHA256 完全相同，Docker label 是 `T488-NO-GO-physical-recovery-executor-missing`。
- 旧 Demo 服务继续运行，未清空数据、未进行 SIGKILL、未打开业务写入资格；保留原来的未提交工作区变更。

## 必须继续完成后才允许结束验收

1. **只在 Common** 补足可复用的持久化物理恢复执行器（若已有 API 则直接组合使用，不新增集群协议），将真实原始签名 WAL、Snapshot/Manifest、两物理 Custody、旧主隔离、真实 ZooKeeper 阶段接入。业务服务仅提供自己的 `byte[]` Snapshot/恢复状态机和配置。
2. Order/Trade 各自绑定**同一个 Common 执行器类型**到缺失的生产 Bean，不能返回空回调/假成功；检验 Spring 启动真实 256 分区依赖图、所有节点相同 Common JAR 和旧主故障时的真实安装。
3. A 主→SIGKILL→B 自动接管继续写→A 自动追平/回主；反向对称测试，并核对快照+原始 WAL、委托/成交/余额/持仓与 SQL Projection 一致。若 READY 失败，保留明确 NO-GO 而非放宽门禁。
4. 全新租户→自动审批→Robot 持续报价和 Tape 点价→真实下单成交/撤单/平仓→MD/Web、24h、余额持仓与 Projection→10/50/200 租户分段压力验收。成功后才能部署并把状态改为 GO。

禁止用测试回调、空 Bean、关闭安全校验、构建成功或容器 UP 替代上述证据；GitHub Actions 本阶段不使用。
