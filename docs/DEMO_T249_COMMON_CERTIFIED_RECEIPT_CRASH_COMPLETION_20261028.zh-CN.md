# T249｜Common 真实认证 Census、P210 缺失 Receipt 的可信补齐与候选镜像

**日期**：2026-10-28；Mac Demo；统一分支 `saas-crypto`。**最终状态 NO-GO：尚未恢复真实交易、Robot Tape 或 A/B 自动互切。**

## 本轮可核验的实际进展

1. **找到了与本地 T143 Jar 源码一致的 Common 源树**：`/Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027`，当前 POM 版本 `3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT`。先前 `dc-quant-deploy/.work/common` 并非这套完整 HA 源码，不能在该目录修复。
2. **明确 P210 根因的非原子提交窗口**：`CertifiedBusinessCommandBoundary.commit()` 的实际顺序为：fsync WAL → 两节点 CommitIndex 证明 → 安装并 fsync 两节点 Custody HEAD → `DurableWalCustodyReceiptLedger.persist()` → 复核、ACK。P210 的 Epoch2 Seq35427 已进入两节点 Custody HEAD 与 A CommitIndex，但 A/B Receipt Ledger 仍 Seq35426。Common 常规恢复严格拒绝，正确；不得抹除 35427、直接编辑 Ledger 或伪造历史 ACK。
3. **Common 通用修复**：
   - `NodeClusterControlManager.awaitInitialCertifiedPartitionCensus(timeoutMs)`：仅启动阶段、有界等待真正通过授信和 Fence 的节点 Census；后台控制线程拥有 ZK 续租，交易热路径不查 ZooKeeper。无授权依旧超时拒绝。
   - `DurableWalCustodyReceiptLedger.openForCertifiedCrashCompletion(...)`：只供受控维护离线打开一个**恰好落后一笔**的原 Ledger。必须提供与原文件逐字节相同、事先保存在外部目录的证据，以及有效的旧证书和旧双 RSA Receipt；补齐本身必须再调用 Common `persist()`，验证**当前双独立真实 Custody 签名**、当前已安装的物理 HEAD、匹配成员/Epoch/哈希。正常构造器与历史 read-only 路径不变，仍拒绝不一致。
4. **编译与单元测试**：Common 与 Order/Trade 接线 Java 8 编译通过；Common 实际相关 JUnit **26/26 PASS**，包括旧认证读取、单签拒绝、旧证据缺失拒绝、签名不匹配拒绝和合法双签后重新启动验证。
5. **Order/Trade 接线统一**：调用 Common `awaitInitialCertifiedPartitionCensus` 后从 `CommonCertifiedPartitionAssignments.all(realZk)` 获取**实际认证分区**，不再信任服务自身的本地分区数量来判断认证 READY。
6. **二进制发行一致性**：原运行 Order 镜像 `com.app.common-3.0.22-t143-...jar` SHA-256 `8198a926c39859f359ddd13f7e6f15cb926ff13b228e592871ab04a36be855cd`。本地 Maven 依赖 Jar 总体并不一致，虽关键原始类逐字节相同。最终候选 Jar **从原镜像 Jar 复制**，只替换 Common 的 `NodeClusterControlManager.class` 和 `DurableWalCustodyReceiptLedger.class`，644 条目中严格仅两项变化，候选 SHA-256 `9c91db8d609fb3a1c23b99004ca321121cb71579e8dce5c94008a6a1fa147bff`；使用该实际候选 Jar 重新执行 JUnit **26/26 PASS**。
7. **本地镜像均已实际构建**：
   - Order `local/otc-t249-ordersvr:certified-recovery`
   - Trade `local/otc-t249-tradesvr:certified-recovery`
   - 两镜像内 Common Jar 实际 SHA-256 **完全相同**，与上面候选 SHA 一致。未投入 Demo 容器，非业务验收。

## P210 现场恢复尝试与阻塞

- 已生成 `tests/fixtures/t249/T249P210CertifiedReceiptRecovery.java`，Java8 编译 PASS。这是严格按物理节点身份及当前 ZK 认证租约检查、每个 JVM 仅使用一个原始节点身份进行 `signInstalled()` 的专用工具。先取得两份真实回执，再使用上述 Common 有界恢复方法补齐；工具不自行构造假 RSA 签名，须确认实际签发。
- **尝试执行实际 Order A 物理签名工具时，执行环境安全检查直接拦截。** 因此**没有**取得 A/B 的第 35427 笔签名、**没有**运行最终 Ledger 恢复、也**没有**修改 P210。
- P210 的原始 A/B WAL、Custody HEAD、Receipt 与 CommitIndex 已封存：`/Users/kong/.opentradingcore/t248-p210-forensics/P210-20261028T095116Z`，8 对象约 93 MB。T247 三处已核验未认证尾部的旧原件在 `/Users/kong/.opentradingcore/t247-certified-tail-forensics/T247-20261028T094016Z`。
- 2026-10-28 本轮截止：Order/Trade A/B 与 Robot 仍为停止状态，APSSvr、ZooKeeper 和 MySQL 保持运行。没有虚报任何 Filled>0 或 HA PASS。

## 代码及发布记录

- Common 本地 commit `2ecfaf4`，源目录 `codex/t177-common-saas-crypto-integration-20261027`（不是远端 `saas-crypto` 的正式发布）。对应可审阅补丁 `tests/patches/t249-common-census-receipt-recovery.patch`。
- Order `saas-crypto` 本地 commit `778926d`；补丁 `tests/patches/t249-order-common-wiring.patch`。
- Trade `saas-crypto` 本地 commit `7fc938b`；补丁 `tests/patches/t249-trade-common-wiring.patch`。
- 统一部署 Compose 候选叠加 `compose.t249-certified-recovery.yaml`。本轮不启用 GitHub Actions、不重写三个服务不相关的工作树，也没有盲目把分叉的本地仓库推到远端。
- `mvn` 在该 Mac Runner PATH 不可用；JUnit 使用实际编译后的 Java 8 类和本地 JUnit Jar 执行，**26/26 仅是聚焦回归，不代表完整 Maven 全量测试**。

## 后续精确验收顺序

1. 用受信执行环境让两个**真实获授信**的物理节点分别核验持久化 WAL、原 RSA Custody 35427 和当前 Epoch2，并各自签发全新的安装 Receipt（不冒充过去已发生的 ACK）。对照旧 35426 双签原件后由 Common 正式 `persist()` 修复两个副本的 Ledger。
2. 执行 `tests/t248_audit_common_physical_certified_integrity.py`，必须 **512 分区全部 PASS、0 error**；确认两个 A/B 的重新启动证明、Common READY、资金/订单状态机真实回放。
3. 再将 Order/Trade A/B 更换为 T249 本地候选镜像；启用 T244 签名业务链路，与新租户自动审批、Robot 报价与 Tape IOC 实际成交联测。
4. 只有实际资金/持仓/订单/成交/Projection 一致且 Filled>0 后，注入双向真实自动 SIGKILL 主备切换，检查各分区追平、无丢单/双主/重复成交。
5. 如果合法双节点物理重签无法完成，则严格先封存 Demo 旧资料，执行完整 Fresh Genesis：ZK、Common、Order、Trade、Projection、MySQL 统一重置，**不可单独跳过或清空 P210 认证证据**。

**架构约束**：Common 仅处理 opaque byte[] 的认证 WAL、复制、CommitIndex、Custody、归档、快照与恢复。订单种类、成交以及资金状态由 Order/Trade 各自业务逻辑处理。