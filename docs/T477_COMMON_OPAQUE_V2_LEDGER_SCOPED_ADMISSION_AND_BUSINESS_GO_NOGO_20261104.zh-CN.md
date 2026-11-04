# T477｜Common v2 恢复账本、精确分区就绪与 Order/Trade 镜像交付证据（2026-11-04）

## 结论 / GO-NO-GO

**Common T477 v2 正常 RF2 复制、协议恢复账本与隔离单元测试：PASS。Order/Trade 真实自动 E2/E3 Replica 安装 + 双 RSA READY + 业务交易全流程：NO-GO。**

**没有停止、替换或删除任何运行中的 Order/Trade / Robot / ZooKeeper 容器、业务数据或签名证书。** 没有使用 GitHub Actions。

## 根因证据（现场）

1. 实际读取 ZooKeeper `/otc/t398-fresh-20261101-r1/order/manifest` 和 `.../trade/manifest`：各 **256/256 Pxxx** 均为 **Epoch 2 READY**，各 A/B 分配 **128/128 Primary**。但 READY 仅是控制面状态。
2. 实际检查 Gateway/Robot/Order B 日志，Robot `DAYWUB` 有实时报价，提交 `placeOrder` 后得到 `ORDER_COMMON_CERTIFIED_BUSINESS_STARTUP_DENIED`。Order B 内层错误 `Common poisoned primary Epoch cannot renew`，物理 WAL/角色授权已撤销，不能靠手动重置 READY。
3. 运行中 Order/Trade 仍使用老版本 Common；四个服务的 `durableHandoff.enabled=false`，未配置已验收的正式新 Epoch durable business handoff。
4. 通过源码与反射检索，`OrderCommonAutomaticRecoveryDependenciesWiring` 和 `TradeCommonAutomaticRecoveryDependenciesWiring` 均依赖的 `orderCommonCertifiedPhysicalRecovery` / `tradeCommonCertifiedPhysicalRecovery` **无生产 Bean 实现**。原始 256 双 RSA Home/Current Physical Signer HMAC/Reader HMAC/各分区 sealed business snapshots 的真实生产配置亦未完成验收。**不允许用空回调伪造恢复与 READY。**
5. `OrderCommonRecoveredDomainWiring` 和对应 Trade 现有 durable handoff 业务图像验证仍限定原始零 ACK Genesis E1，不能拿其代替 E2/E3 的资金/委托/持仓完整 replay。

## Common v2 账本根因与修复

原 `DurableRecoveryInstallLedger` 落盘 `format=2`，隐含旧版 `STATE/STATE_COMMIT` marker 次序，未记录 `walProtocolVersion`。真实 v2 opaque 单帧 WAL 必须 `markerSeq=0` 且 `sourceStateSeq=headSeq`；原版重启回读拒绝。独立 JUnit **原版 RED：3 tests / 2 failures**。

修复：
- 新写入记录 **format=3**，显式 `walProtocolVersion=1|2`；历史 `format=2` 只按 v1 读取。
- v1 原有 maker/control marker 次序校验保持；v2 单帧采用自己的认证序号校验；重启与 incomplete retry 比较保留协议身份；协议降级拒绝。
- `DurableRecoveryTransactionControl.forOpaqueCommittedWal` 使用 Common 唯一持久 WAL + 已 seal 的 Snapshot + fsync durable install ledger。v2 不要求业务维护第二个 CQ/WAL；v1 仍必须提供真实 JournalBaseline。
- 任何安装事务完成仅为 `REPLAY_COMPLETE`，**不自动发布 ZK READY**。

原版失败日志 `.work/t449-common-gw-rejoin/target/t477-ledger-red.log`；修复初次 13/13、扩展 15/15 PASS，日志 `target/t477-ledger-green.log` 与 `target/t477-opaque-ledger-control-regression.log`。

## 精确分区 Common/Order 准入

- `CommonBusinessRecoveryReadiness.requireBusinessPartitionRecoveryReady`：旧实现保持全节点严格 fallback；新的 `CommonCertifiedBusinessReplayGate` 按 **指定 Pxxx、当前 Epoch、真实回放完成** 判定（无证据拒绝）。
- `CommonCertifiedBusinessApplyBoundary` 的写入与业务 Image 只读取对应分区的已认证 replay；Common WAL writer、ZK grant、签名仍独立执行物理校验。
- `OrderClusterAdapter` scoped placeOrder 前校验指定市场的分区实际角色、分区业务回放证书、已安装真实 Primary writer；未指定分区的批量操作仍使用原来的全节点严格门禁。**不授予新 Epoch，不改写 ZooKeeper/ACK**。
- 实测隔离测试：P210 物理副本不可达导致 Primary poisoned；对应请求拒单；P211 尚未被 poisoned，可通过业务 admission 但没有伪造成功 WAL/客户 ACK。相关用例 **51/51 PASS**。
- Common 独立测试验证：一个分区已 replay，另一个未 replay 时全节点门禁仍拒绝，而指定已 replay 分区通过；换 Epoch/重复分区/失效后立刻拒绝；旧实现走强门禁，**6/6 PASS**。
- 说明：正式 `CommonDurableBusinessReplayHandoff` 仍需实现并验收新 Epoch 的精确分区恢复证据核验；**目前 scoped Common 运行时门禁不是正式生产物理交接的替代品**。

## 同版隔离回归

候选 Common 测试 JAR：

`.work/t449-common-gw-rejoin/target/t477-common-opaque-ledger-and-shard-scoped-ready-candidate.jar`

SHA-256 `9ea0e2dd52f63ba92226c9c453b5e295b1bede034f74af3a25d344b231da9967`

这是一份增量封装的隔离候选 JAR，CRC 完整、0 重复 ZIP 条目，并非正式 clean Maven 发布物。

| 验证 | 真实结果 | 证据 |
|---|---|---|
| Common v2 Ledger+旧版兼容+基线控制+物理.Netty/ZK/凭证+分区隔离 | **105/105 PASS** | `target/t477-common-extended-regression.log` |
| Order 新源码/非空委托快照/原启动与恢复回归（同版 Common） | **51/51 PASS** | `.work/t444-order-stream/target/t475-certified-snapshot/t477-on-new-common-junit.log` |
| Trade 非空余额/100x 杠杆持仓/原启动与恢复回归（同版 Common） | **63/63 PASS** | `.work/t452-trade-windowed-e2/target/t475-certified-snapshot/t477-on-new-common-junit.log` |
| Common A/B 2 JVM、三节点 ZK、256 分区、10/50/200 模拟租户健康 STRICT 2/2 | **540/540 ACK、0 失败、256/256 WAL 字节一致** | `.work/t466-common-256-strict/20261104085516-10689/metrics.json` |
| 本版 T477 A→B→A 两次真 SIGKILL | **未执行：执行环境安全检查拦截** | 不复用 T476 PASS 冒充 |
| 新租户自动审批/Robot Tape/入金/委托成交/E2/E3 Order+Trade 真实双向切换 | **NO-GO** | 生产物理恢复 Bean/业务 replay/双签 READY 尚缺 |

新候选 ARM64 镜像：
- `local/otc-t477-ordersvr:opaque-v2-ledger-replay-candidate`，Image SHA `bcc7891c2eb10bbcac72f3323ca5c7e28e38001b145e1e21bb45ca700ffd92b8`
- `local/otc-t477-tradesvr:opaque-v2-ledger-replay-candidate`，Image SHA `b1d948f2cc908256877caa7c97a6eaa4bbdef41f79b2cea04e4fec37172f2e18`

两份镜像在 `docker run --network none` 下使用本机 Java8 成功加载新 Common v2/SourceWiring/OpaqueSnapshotPin 和业务接线类；两份 Common JAR SHA 相同。**镜像标签 `CANDIDATE-NO-GO-until-signed-physical-recovery`，未替换活跃业务。**

## 补充：真实新租户自动审批 / Robot 运行诊断

2026-11-04 在当前 Demo 使用原有 `tests/verify-tenant-auto-approval.py` 直接调用 localhost 正式 Gateway/Manager/Login 接口，无手工审批：
- `auto_location=KJVLG7`，租户申请自动变为 `APPROVED`，正式管理员实际登录 PASS，同申请幂等重试 PASS；额外 5 产品申请按规则保留 `PENDING`。脚本**退出 0**。
- 只读 MySQL 查询 `dc_tenant`：`KJVLG7 / TRIAL`；`dc_tenant_robot` 自动生成一条 BTCUSDT Robot 配置，`enabled=1`。
- 该新租户 Robot 实际 `runtime_status=ERROR`、`open_order_count=0`，最近错误 `CANCEL_FAILED / gateway rejected queryOpenOrder: ORDER_COMMON_CERTIFIED_CENSUS_UNAVAILABLE`。这是 **业务实测失败**，不能误报 Robot/Tape 报价成交 PASS。
- Order A 旧镜像日志真实堆栈另有 `NodePartitionGrantTable.unexpired: node quorum lease expired`；Order B 则显示 `Common poisoned primary Epoch cannot renew`。其控制面 lease 与物理分区 poison 是两项独立拒单原因；ZK 256/256 `READY` 不构成物理写入授权，不能手工清理 poison。
- 证据：`.work/t449-common-gw-rejoin/target/t477-tenant-autoapproval-run.log`、现有数据库 `dc_tenant/dc_tenant_robot` 的只读状态和对应 Order 日志。避免把查询结果中的 Broker/Robot API Key 或 Secret 输出至报告。

**T477 阶段 3 当前结论：租户自动申请/自动审批/登录/Robot 初始化 PASS；Robot 实际挂单/点价/成交 NO-GO。**

## 必须继续完成（不扩大业务功能）

1. 在 **Common** 内接通真实已 OS-locked WAL/CommitIndex/双 Custody `CertifiedPhysicalRecovery`，从真正现有 ZooKeeper Stage 和双 RSA 证书读取 old-Epoch Source；不得用业务层重写 Watch/Replication/READY。
2. 使用同一 Common 原始恢复事务 + v2 ledger + Source HEAD + 完整前缀摘要，在 Order/Trade 的已注册业务 `ReplicatedStateMachine` 上做 Snapshot+完整 WAL Apply，冷重启后独立认证资金、委托、成交、持仓及 idempotency；按 256 分区验证。
3. 两独立节点 RSA/物理退休/完成 replay 后发布唯一签名 READY，新 Epoch 恢复本地角色，旧 Epoch 永久拒绝。
4. 通过以上门禁后才用两份新的正式镜像替换 Demo，必要时用新 namespace 重新注册租户，走自动审批、Robot 盘口、Tape 成交、入金下单、撤单平仓，再 SIGKILL Order/Trade A/B 连续互切和全状态对账。
5. 保持业务容器运行与历史证据；任何 failed-closed 不能降级为假成功。物理双副本失联故障期 Local ACK 仍有 RPO 风险，不能称 RPO0。
