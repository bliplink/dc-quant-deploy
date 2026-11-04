# T476｜非空业务 Snapshot 验证与 Common v1/v2 恢复请求身份修复（2026-11-04）

## 阶段结论
**T476 Common v2 认证 Snapshot + 物理原始 WAL 正确性验证 PASS；正式 Order/Trade A/B 业务自动 E2/E3、Replica 安装以及双签 READY 仍 NO-GO。** 本轮未替换任何 Order/Trade 运行镜像，未清理 P060 旧数据，也未使用 GitHub Actions。

### 1. 根因与最小修复
审阅 `CommonCertifiedRecoveryInstall.identical` 发现原来的两个恢复请求身份匹配只对比了分区、Epoch、seq、快照 SHA、路径等，没有对比 `walProtocolVersion`。在零业务 Snapshot 基线的构造中，v1 `STATE/STATE_COMMIT` 和 v2 已认证 opaque 单帧 WAL **可拥有完全一致的其他字段**，原版错误返回等价。

先编写 `CommonV1V2RecoveryRequestIdentityTest`，**原版失败（Red）**：`Common recovery accepted legacy v1 as authenticated opaque v2`。然后最小修复：`CommonCertifiedRecoveryInstall.identical` 必须要求 `a.walProtocolVersion==b.walProtocolVersion`，**修复版通过（Green）**。不新增任何集群协议、选主、WAL、READY 机制。

远端 Common:
- [修复 commit 60c42291de1f1f95b5da33be7dbcd54749fcaac2](https://github.com/bliplink/com.app.common/commit/60c42291de1f1f95b5da33be7dbcd54749fcaac2)
- [回归用例 commit 205e4a908ce837d3c7b93b120245e22b7b789d00](https://github.com/bliplink/com.app.common/commit/205e4a908ce837d3c7b93b120245e22b7b789d00)

### 2. 真业务非空快照回归

- Order `OrderCertifiedNonEmptyOrderbookSnapshotTest`：实际 `OrderManager` 内存数据中两笔本分区委托订单（qty 0.500 + 1.250 = **1.750**，带真实价格 43000.25 和 43150.50），外加另外租户一笔订单，调用实际 `OrderSnapshotManager.captureAtCertifiedWriterHead(P090, E1, seq11)`。业务 JSON round-trip 后仍只包含本租户两笔委托，原价/数量及 seq11 一致。**PASS**。测试通过反射布置内存测试数据，**并非实盘入金/下单**，不构成真实交易 HA 证据。
- Trade `TradeCertifiedNonEmptyFundsSnapshotTest`：向实际 `AccountBalanceFacade` 恢复两条本租户余额及另一租户余额，调用实际 `TradeBusinessSnapshotCapture.captureAtCertifiedWriterHead(P091, E2, seq9)`。本租户 U001 余额 **10000.00**、已用保证金 **100.00**、冻结保证金 **20.00**、可用余额 **9880.00**；业务 JSON round-trip 后一致，其他租户资金完全隔离。**PASS**。这不等于已经验收真实交易资金/持仓跨 Epoch 恢复。
- [Order 测试提交 1b426913490eaaff5e004f6748040805ffef0426](https://github.com/bliplink/com.app.dc.ordersvr/commit/1b426913490eaaff5e004f6748040805ffef0426)
- [Trade 测试提交 029a17f2522801c49fdd26b9d7f12edeb59a5d7e](https://github.com/bliplink/com.app.dc.tradesvr/commit/029a17f2522801c49fdd26b9d7f12edeb59a5d7e)

### 3. 最新 Common 候选 JAR 与真实实测

候选：`.work/t449-common-gw-rejoin/target/t476-common-snapshot-v2-protocol-identity-tested.jar`  
SHA-256：`906ce74c762526b775eaafd68fb665d171ad9d910836e5790d0e2843e959d5de`。

这份 JAR 是 T475 已验收候选上增量合并 T476 编译类的**隔离测试产物**，非 clean Maven 或正式容器镜像。ZIP CRC 通过、0 重复 ZIP entries。

| 验证 | 本轮结果 | 具体证据 |
|---|---|---|
| Common 全恢复回归（含真实 A/B RSA+Custody、v1/v2、ZK、快照/失效、Netty） | **80/80 PASS** | `.work/t449-common-gw-rejoin/target/t476-common-regression.log` |
| 原版 v1/v2 相同元数据漏洞复现 | **原版 RED** | `.work/t449-common-gw-rejoin/target/t476-protocol-bound-red.log` |
| 修复版 v1/v2 防混淆单测 | **GREEN** | `.work/t449-common-gw-rejoin/target/t476-protocol-bound-green.log` |
| Order 真业务快照、启动门禁及旧恢复回归（同一 T476 JAR） | **50/50 PASS** | `.work/t444-order-stream/target/t475-certified-snapshot/t476-on-finaljar-junit.log` |
| Trade 真业务快照、启动门禁及旧恢复回归（同一 T476 JAR） | **63/63 PASS** | `.work/t452-trade-windowed-e2/target/t475-certified-snapshot/t476-on-finaljar-junit.log` |
| 两台真实 Common JVM、三台 ZooKeeper、256 分区、128:128 Home，10/50/200 租户模拟的健康严格 ACK | **540/540、0 失败、256/256 字节一致 PASS** | `.work/t466-common-256-strict/20261104080428-4965/metrics.json`, `.work/t449-common-gw-rejoin/target/t476-256-strict-run.log` |

最新 T476 修复针对恢复请求身份边界；之前 T475 的**同一 T475 候选 JAR**已实际通过 A→B→A 双次真实 SIGKILL，但**本次未重新执行 T476 候选 JAR 的双次 SIGKILL**，不可误报成新的相同测试。故障期仍为 `LOCAL ACK` 带 RPO 风险，并非严格 RPO0。

### 4. 正式业务集群的明确 NO-GO 阻塞

- 已有 `CommonCertifiedAutomaticSourceWiring.fromOpenedCertifiedPhysical`、真实 `CommonCertifiedOpaqueSnapshotPin`、`OrderSnapshotManager` / `TradeBusinessSnapshotCapture` 业务快照源。源数据一侧取得实测证据。
- **Order/Trade 正式 `orderCommonCertifiedPhysicalRecovery` / `tradeCommonCertifiedPhysicalRecovery` Bean 仍缺少可核验的生产实现**。它应调用 **Common** 的 `CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery` 四项真实来源：签名控制协调器、独立 fsync Replica catchup、双方签名 READY、经认证的新 Epoch 物理 WAL 和业务 Snapshot/Apply 安装。不允许实现占位成功回调，也不允许在业务中复制 Common 的 Watch/Epoch/WAL。
- `OrderCommonRecoveredDomainWiring` 目前仍明确限制仅能验证原始 E1 空 Genesis；尚未验证正式 Order/Trade 的 E2/E3 实际业务恢复、资金/持仓/委托/成交/Projection 一致性与 Robot 持续报价成交。
- 四个当前运行中的业务容器依然 Up：`otc-t453-order-b-standby-parent-watch`、`otc-t452-trade-b-windowed`、`otc-t436-trade-a-margin`、`otc-t432-order-a-restored`；没有替换、更改或清理旧数据。

**结论：Common 层通过本轮验证；正式 Order/Trade 业务 HA NO-GO。下一步只攻克真实物理 Replica installer + 两签 READY，随后可直接在隔离/可清空数据的 Demo 环境执行完整业务重部署和租户/Robot 验收。**
