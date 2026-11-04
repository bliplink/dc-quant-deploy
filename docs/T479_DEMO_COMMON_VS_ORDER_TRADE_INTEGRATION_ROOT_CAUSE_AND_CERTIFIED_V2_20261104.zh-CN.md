# T479｜Demo+Common 已通过，但 Order/Trade 不同路径的根因与正式业务接线进展（2026-11-04）

## 一句话结论

**Demo+Common 两次真实 SIGKILL A→B→A 的 PASS 真实有效，但它验证的是隔离 Demo 主备流程；正式业务 Order/Trade 使用了不同的 Spring 物理恢复集成路径，所需的生产恢复执行者没有提供。** 这不是 Common TCP 异步复制或 ZK 选主需重新设计，而是业务恢复接线尚未闭环。

T479 已将 Order、Trade 的 **v2 完整业务恢复入口显式绑定到同一个 Common `CommonCertifiedRecoveryInstall`**，并禁止旧业务回调跳过物理认证进行 v2 回放。实际 Spring `CertifiedPhysicalRecovery`、正式 E2/E3 Replica 安装/双签 READY、Bot 真实成交均仍 **NO-GO**，不能宣告产品集群完成。

## 根因和代码路径对照

| 项目 | Demo 已验证的路径 | Order/Trade 现有代码 |
|---|---|---|
| 两次真实 SIGKILL | `examples/common-only-demo/.../DemoCommonLiveZkProcess`、`DemoCommonRejoinProcess`，由 Common Watch/Coordinator/原始 WAL/签名 Stage 与 C 独立见证完成真实 E2/E3 接管/追平 | Spring 的 `OrderCommonNodeRuntimeWiring`、`TradeCommonNodeRuntimeWiring` 预期 128 个 Replica 计划，目前仅接入依赖声明 |
| 物理证据 | Demo 调用真实 `CommonCertifiedPhysicalEvidenceRegistry.installSignedSurvivor`、`CommonCertifiedGenesisSurvivorInstall.install`，针对 E1 原始双签 Genesis/WAL；故障期间可 LOCAL ACK 但显式 RPO 风险 | `@Qualifier("orderCommonCertifiedPhysicalRecovery")`、`@Qualifier("tradeCommonCertifiedPhysicalRecovery")` 未有实际生产 Bean；四个必须提供的 Common 回调（signedCoordinator/independentFsyncedReplica/bothSignedPhysicalReady/recoveredBusinessWalAndSnapshot）尚未接到真正的 physical source |
| 业务恢复 | Demo 的特定状态机 + 认证 Genesis/WAL；并非证明了正式订单资金结算 | Order/Trade `RecoveryStateMachine`、业务 Snapshot/Applier 存在；其旧 `FencedRecoveringBusinessState.inspect` **只接受原始空 E1**，不能作为非空 E2/E3 的真实恢复 |
| 网络单帧 v2 | Common T478 Netty 双测试 voter 认证+真实 `CommonCertifiedRecoveryInstall` 已通过 | T479 新增业务入口可使用此**同一 Common 安装器**，真实生产双 RSA/Epoch 注册仍待接线 |
| 运行状态 | Demo 真实物理双向脚本 PASS，故障期 LOCAL ACK 有 RPO 风险 | 现网四容器为旧 Common/配置，`durableHandoff.enabled=false`；ZK 256 分区 E2 READY 但 Order A 存在 `node quorum lease expired`、Order B 存在 `Common poisoned primary Epoch cannot renew`，不能 ACK |
| 新租户与 Robot | 不属于纯 Demo+Common HA 验收范围 | 新租户 `KJVLG7` 自动审批、管理员登录和 BTCUSDT Robot 配置初始化 PASS，但 Robot 运行 ERROR、0 挂单，遭 `ORDER_COMMON_CERTIFIED_CENSUS_UNAVAILABLE` 拒单 |

**重要：** Demo 单分区/Genesis + C 签名见证与正式 256 分区分配、真实历史业务状态、全部已确认成交账本是不同的验收维度。不能用 Demo PASS 代替正式业务 READY；也不能因为业务缺 Bean 而反复修改 Common 选主算法。

### 另外确认的启动门禁差异

`OrderCommonNodeRuntimeWiring.certifiedWriters` 和 `TradeCommonNodeRuntimeWiring.certifiedWriters` 在 Spring Bean 创建时都会调用 `installed.requireAuthenticatedReady()`、`attestedBusinessRecovery.requireBusinessRecoveryReady(service,node)`。这两个当前是全节点聚合门禁，而不是“只有指定 Pxxx 下单时才检查对应分区”。在一个分区缺认证或被 Common poison 时，**可能连带使整节点 writer Bean 不可用**；即使后面业务适配器已增加逐分区校验也不能逆转已经失败的 Spring 启动。这是仍需按 Common 真正物理分区 READY 数据分解的具体后续问题，不得简单去掉全局门禁而让未恢复分区进入写入。

## 本轮 T479 实际代码交付

两个业务仓 `saas-crypto-latest`：

1. `OrderCommonRecoveryBinding.recoverCertifiedOpaquePhysical` 和 `TradeCommonRecoveryBinding.recoverCertifiedOpaquePhysical`：必须提供由 Common Netty 已验证的 `VerifiedRecoveryStagingClient.Result`、`CertifiedRecoverySourceAuthority`（独立真实源与 voter 新鲜验证）、`DurableRecoveryTransactionControl`（排他/不可变 Snapshot）、`DurableRecoveryInstallLedger`（fsync 账本）。内部仅创建各自业务 Registry，统一调用 **`CommonCertifiedRecoveryInstall.install`**，原始 WAL 的完整认证、Epoch、HEAD、Snapshot/回放/ledger 与 NOT_READY 均由 Common 完成。业务只负责 `OrderJournalRecord` 或 `TradeJournalRecord` 的自己的语义 Apply。
2. 旧业务 `recover(Common Control, Common LogSource)` **明确拒绝 walProtocolVersion 2**，不允许用自建/不完整恢复 Controller 走 v2 快捷路径。v1 行为保留。
3. 新增 `OrderCommonPhysicalOnlyV2EntryTest`、`TradeCommonPhysicalOnlyV2EntryTest`，证实缺 Stage 或尝试旧 v2 bypass 会 IOException 拒绝。两项测试均 PASS。
4. 不新增业务 Watch/Epoch/WAL、订单类型持久化特例、READY 投票者或所谓“业务认证捷径”。

具体 GitHub commits：
- Order 认证安装入口 [f6cb9ec](https://github.com/bliplink/com.app.dc.ordersvr/commit/f6cb9ec6934f7fca4ee827870593e56a07b89e43)，拒绝 v2 旧路径 [f80fae4](https://github.com/bliplink/com.app.dc.ordersvr/commit/f80fae4da02b86c05c0f7daf3b06396737744f85)，门禁测试 [b38efb3](https://github.com/bliplink/com.app.dc.ordersvr/commit/b38efb351333ba9d3825c881146ecc80722aaa11)
- Trade 认证安装入口 [05f35ea](https://github.com/bliplink/com.app.dc.tradesvr/commit/05f35eab250669620623a2dba7b876bfed0b99df)，拒绝 v2 旧路径 [da6a099](https://github.com/bliplink/com.app.dc.tradesvr/commit/da6a09906adb13f079e1e8a465fa71043dc2ed95)，门禁测试 [cd40897](https://github.com/bliplink/com.app.dc.tradesvr/commit/cd40897a43a9e852a763a6df80fc3870841bacb5)

## 本地实际验证

| 项目 | 测试结果 | 证据 |
|---|---|---|
| 与 T478 同版 Common 的 Order 回归 + 新 v2 门禁 | **52/52 PASS** | `.work/t444-order-stream/target/t475-certified-snapshot/t479-physical-only-final-regression.log` |
| 与 T478 同版 Common 的 Trade 回归 + 新 v2 门禁 | **64/64 PASS** | `.work/t452-trade-windowed-e2/target/t475-certified-snapshot/t479-physical-only-final-regression.log` |
| Order Java 8 全部实际源码 | **122 sources / 179 classes 编译 PASS** | `.work/t444-order-stream/target/t479-full-compile/` |
| Trade Java 8 全部实际源码 | **172 sources / 219 classes 编译 PASS** | `.work/t452-trade-windowed-e2/target/t479-full-compile/` |
| Common T478 基础恢复+Netty+原始 WAL/账本+控制回归 | **108/108 PASS** | `.work/t449-common-gw-rejoin/target/t478-common-full-netty-regression.log` |
| Common T478 2 JVM/3 ZK/256 健康负载 | **540/540 严格 ACK、256/256 WAL bit-exact PASS** | `.work/t466-common-256-strict/20261104092254-12360/metrics.json` |
| 最新 T479 ARM64 镜像离线构建（全量主源码，无测试类） | **两份 PASS** | local Docker image inspect 与 `docker run --network none` ABI |
| 真实生产 E2/E3、Robot/Tape 下单成交、双次业务 SIGKILL | **NO-GO，未验收** | 上述 Common 物理恢复 Bean/真实签名/业务接管仍未闭环 |

**同一 Common JAR**：`.work/t449-common-gw-rejoin/target/t478-common-v2-netty-durable-install-candidate.jar`，SHA256 `223abacd4bd05757ce6f5241cdb8c71431f9d4991100a5a9c2fa1781923a889c`；这仍是隔离增量验证候选，**非 clean Maven 生产发布**。

新镜像：
- `local/otc-t479-ordersvr:full-java8-certified-v2-no-go` SHA256 `313d7bab3884`（镜像 ID 前缀）
- `local/otc-t479-tradesvr:full-java8-certified-v2-no-go` SHA256 `c0d57b922c28`（镜像 ID 前缀）

两份 Docker 离线容器内均验证 **恰好一份 Common JAR**、新版 SourceWiring、OpaqueSnapshotPin、业务 Snapshot 与签名安装入口类可以装载；标签注明 `T479-NO-GO-until-signed-physical-recovery`。四个实际 Order/Trade 业务容器仍 UP，**没有镜像替换/数据重置**。

## 继续推进时必须完成的唯一主线

1. **Common 实现正式 `DurablePhysicalRecovery` 源证据供给**，重用 Demo 已验证的 old-Epoch 物理注册表/签名 Stage/真实 fsync 和现有 watcher/READY；Order/Trade Spring 只做真实配置和业务状态机交付，绝不复写 HA。
2. 必须按 256 分区可认证原始 Snapshot + WAL，补 **E1→E2→E3 非空历史**恢复水位与相同业务状态，独立验证资金/委托/持仓/成交/outbox。任一真实签名缺失继续 NO-GO。
3. 正式签名 READY 之后构建/替换 Demo 业务镜像；如果需重置业务数据，允许在留存证据后重建开发数据与新租户，但不得清除不完整签名/损坏数据并伪造证书。
4. 新租户自动审批→Robot 报价/Tape→入金/下单/成交/撤单/平仓，持续写入中 Order/Trade 双次真实 SIGKILL，核对所有资金/订单/成交/Projection/MD。
5. **注意故障期可使用 Common 明确记录 RPO 风险的 LOCAL ACK**，不能把死掉的 A 虚构成仍能物理 2/2 ACK。现有 Demo C 独立见证的策略可复用，但不等于两个活跃物理 voter 的严格 RPO0。
