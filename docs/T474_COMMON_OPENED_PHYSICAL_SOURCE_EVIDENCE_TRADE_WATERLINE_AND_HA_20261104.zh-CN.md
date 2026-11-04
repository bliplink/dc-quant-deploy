# T474｜Common 真实物理恢复源接线、业务 WAL 水位校验与同版 HA 实测（2026-11-04）

**最终门禁：Demo+Common 物理自动双向切换与严格健康复制阶段 PASS；Order/Trade 正式业务自动 E2/E3 集群仍 NO-GO。**

## 范围
本轮以 T473 Common [6f528b9c37fc55fd17b4c632822bd07c5a1d8fd4](https://github.com/bliplink/com.app.common/commit/6f528b9c37fc55fd17b4c632822bd07c5a1d8fd4) 为基础，仅复用现有 Common WAL/CommitIndex/Custody/Netty/Snapshot/Catalog/Prefix/HA Watch。业务只处理各自的 Snapshot 与 WAL payload。未修改网关、未加独立选主或业务类型专用持久化机制，未改运行中 Order/Trade 容器，未触碰 P060 旧数据，未运行 GitHub Actions。

## 本轮已提交 GitHub

### Common（saas-crypto-latest）
- [d59e587d7398343238bf1477cd3ab8921a6daca5](https://github.com/bliplink/com.app.common/commit/d59e587d7398343238bf1477cd3ab8921a6daca5)：`CommonCertifiedAutomaticSourceWiring.fromOpenedCertifiedPhysical`，**只能在真实物理 WAL/CommitIndex/Custody 被 Common 打开后**，凭调用方提供的精确认证业务 Snapshot 检查点与真实 ZK 版本构造原有四类签名 RPC 数据源；所有请求复查 Common 当前物理身份、严格已认证 HEAD、完整磁盘 Snapshot Seal 与原始 WAL。
- [607142f373b71cd1c5ef69686ed8a2ced080ec11](https://github.com/bliplink/com.app.common/commit/607142f373b71cd1c5ef69686ed8a2ced080ec11)：真实 A/B RSA/Custody/WAL/非零 Snapshot SourceEvidence 单测；A 是业务 Source，B 只能做独立物理 WAL Prefix 投票，不能冒充业务 Snapshot Primary。
- [0598bd60b88f694f54fc4bff6e163a2303205d1b](https://github.com/bliplink/com.app.common/commit/0598bd60b88f694f54fc4bff6e163a2303205d1b)：真实严格 ACK 水位从 2 提交至 3 后，旧 Snapshot/旧 Replica Prefix 都拒绝继续签发，避免过期水位伪装新恢复源。

### Trade（saas-crypto-latest）
- [52000687566464c298edefe6bacca36efec06f7e](https://github.com/bliplink/com.app.dc.tradesvr/commit/52000687566464c298edefe6bacca36efec06f7e)：`TradeRecoveryStateMachine` 现在要求业务 WAL seq 逐条连续，拒绝重复/缺号，检查业务批次身份和 version，并在 finishReplay 前确认达到 Common 认证 HEAD。没有添加任何业务专用 HA。
- [232a55927b1b2d5aa9745da75e35c4926193f079](https://github.com/bliplink/com.app.dc.tradesvr/commit/232a55927b1b2d5aa9745da75e35c4926193f079)：非零 v2 Snapshot + 错序、重复、未到水位、无效业务批次拒绝的实际 JUnit。

### Order（saas-crypto-latest）
- [45b2b3862579db991adfe184df02038e120a0070](https://github.com/bliplink/com.app.dc.ordersvr/commit/45b2b3862579db991adfe184df02038e120a0070)：非零 v2 Snapshot 恢复边界；缺少已提交 WAL、重复基线、跳号必须拒绝。不更改既有 Order 业务 HA 实现。

> Mac 上 Common 原始 `git push` 因无法连接 `github.com:443`（75 秒超时）失败，本轮代码改由已连接的 GitHub 工具逐文件提交至 `saas-crypto-latest`。**远端实际提交 SHA 以上述 GitHub commit 为准**，本地隔离 Common clone 的历史未与远端额外提交自动对齐，不能直接强推。

## 最新候选 JAR（同一份用于以下压力及故障注入）
`.work/t449-common-gw-rejoin/target/t474-common-opened-physical-v2.jar`

SHA-256：`3e034b90e16c9e1d713edbf86476e0cd0e6569fc70ac09bae59cdc59c8525caa`。

Java 8 候选，在 T473 本地已验证 Jar 上增量合并 T474 类：Zip CRC 检查通过、0 重复 ZIP entry、`javap` 验证新的真实物理 SourceEvidence API。**不是 Maven clean 版、不是新生产业务镜像。**

## 实际测试记录

| 范围 | 实际结果 | 证据 |
|---|---|---|
| Common v1+v2 物理与 Netty 回归 | **58/58 PASS**；新增严格水位移动断言后单独真实 RSA 测试 **7/7 PASS** | `.work/t449-common-gw-rejoin/target/t474-real-source-regression.log`，`target/t474-live-ack-movement.log` |
| 实际 A/B 已打开原始 WAL、双 RSA/Custody、Snapshot Catalog | A 真实 Source HEAD/Manifest/Data，A/B 独立 Prefix；篡改 Snapshot SHA、Replica 冒充来源、过期提交 HEAD 均拒绝 | `T474_COMMON_REAL_OPENED_A_B_SOURCE_BEANS_PASS`，`T474_SOURCE_STALE_WATERLINE_AFTER_REAL_ACK_REJECTED_PASS` |
| Common 最新 Jar 256 分区严格健康 E1 压力 | 2 JVM 各 128 Home，**540/540 ACK**，**256/256 原始 WAL 字节一致**，10→50→200 租户模拟阶段全部通过 | `.work/t466-common-256-strict/20261104054515-95449/metrics.json` |
| 同版候选 JAR 真实自动两次 SIGKILL | A 挂→B E2 恢复/继续写→A 追平；B 挂→A E3 恢复/继续写→B 追平；E3 新 WAL 通过 TCP 到 B fsync：**PASS，脚本退出码 0** | `.work/t449-common-gw-rejoin/target/t474-two-sigkill-run.log`，`/Users/kong/.opentradingcore/t124-live-kill-runs/20261104134549` |
| Order 源码与业务精选测试（使用同一 T474 Jar） | **122 Java 8 源文件编译 PASS；41/41 测试 PASS** | `.work/t444-order-stream/target/t474-common-abi/junit.log` |
| Trade 源码与业务精选测试（使用同一 T474 Jar） | **172 Java 8 源文件编译 PASS；56/56 测试 PASS** | `.work/t452-trade-windowed-e2/target/t474-common-abi/junit.log` |
| 现有四个业务容器 | 均处于 Up，未部署替换 | `otc-t453-order-b-standby-parent-watch`、`otc-t452-trade-b-windowed`、`otc-t436-trade-a-margin`、`otc-t432-order-a-restored` |

故障时 `quorum=false`、`rpoRisk=true`、`localAckNotRetroactiveQuorum=true`，即明确 **LOCAL_DURABLE**，不能说故障期严格 2/2 RPO0。256 分区压测仍属于健康期 E1，不等于 256 分区同时自动 Home 双向恢复。

## 尚需真实接通的阻塞（不能伪造）

1. Common 的 `fromOpenedCertifiedPhysical` 已经过真实物理来源和 Snapshot/WAL 测试，但 Order/Trade 的 Spring `order/tradeCommonPersistedSignedSourceEvidence` 真实业务**精确 Snapshot 检查点选择**还未实现完整；不能通过扫描“最近一个”快照或拿 Spring 内存状态直接冒充已认证来源。`OrderSnapshotManager.capturePartition()` 目前明确拒绝未经 Common 屏障的业务快照产生；Trade Snapshot 也要求真实 Common 排他屏障。必须在 Common 认证提交/快照事务内实际 seal 业务 Snapshot，再把签名物理 HEAD 与具体 Snapshot 绑定。
2. `order/tradeCommonCertifiedPhysicalRecovery` 对应的 `CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery` 真实实现缺失。需要将已存在的 Common 故障恢复/旧主隔离、原始 WAL、业务 Apply 和双物理 READY 认证贯通到真实 Order/Trade E2/E3，**不能写空成功 Bean 或业务自建 Watch**。
3. 尚无新业务镜像实际替换、自动审批新租户、Robot 持续报价、Tape 点价成交、真实 Order/Trade A/B 连续互切、资金/持仓/委托/成交/Projection 与 MD 一致性验证。故此 **完整产品验收仍为 NO-GO**。

**状态：T474 通用 Common 源适配与恢复边界通过真实物理/网络测试，并再次验证最新 JAR 的 256 健康严格复制和 Demo A→B→A；正式 Order/Trade 业务 E2/E3 仍 NO-GO。**
