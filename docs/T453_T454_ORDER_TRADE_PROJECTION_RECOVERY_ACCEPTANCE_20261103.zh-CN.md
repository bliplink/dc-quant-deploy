# T453–T454｜Order/Trade RPC 重连、认证交易与财务 Projection 真实恢复验收（2026-11-03）

## 验收范围与边界

仅覆盖 Demo Mac 的 Common 公共客户端重连、Order B→Trade B 业务连接、DAYWUB Robot 持续报价/真实成交、Trade P144 认证事件投影与财务 ReadModel 一致性。**不代表 Order/Trade A/B 自动双向主切、256 分区完整一致性或 MD 价格源切换最终验收通过。**

## 故障根因与对照证据

1. 旧 Order B `otc-t450-order-b-common-rejoin` 在 Trade B 07:28:56 TCP 连接成功后，依旧持续返回 `[1015] SERVER.TradeSvr is not Online`，08:21 实际 DAYWUB 订单被 `Trade_Correct/Rejected`；待撤单的 Trade 资金释放也被挡住。
2. ZK 原始分区 `/dc/cluster/tradesvr-t398/partitions/P144` 为 `epoch=2,state=READY,primary=TradeSvrB`。独立只读诊断进程在**与 Order B 相同镜像、配置和 ZK**下验证 `DAYWUB→P144→TradeSvrB`，另 JRHHXA P242 与 KCV203 P240 一致。进程独立创建 Common RPC 客户端，约 3 秒从 `physical=false` 自动转为 `true`。证明配置、分区哈希和 Trade B 物理网络并非根因。
3. 现场版本核对：Order B 只接入 T449 `GwClient` 的物理断线重连，没有接入 T451 `ZkCluster` 的 `RegType=2` 父目录 `EPHEMERAL_SEQUENTIAL` 成员 watch；Gateway 与 Trade B 已接入。长时间运行的 Order B 客户端因此存在重注册不更新的路径；本轮补齐后真实 DAYWUB 订单的 [1015] 消失。Common 源码修复已在 `bliplink/com.app.common` 的 `saas-crypto-latest`，其中 T451 最终提交 `d2f545649a71e0fb5185afc1a0ae9e541c3033c2`；Common 本地 706 tests、0 failures、0 errors、72 skipped。
4. Projection `otc-t448-projection-trade-consumer` 仍使用旧 `com.app.common-3.0.15` 的客户端，缺少 T449/T451 物理重连/服务目录 watch。Trade B 的 P144 物理 CommitIndex 到 60344，数据库 `dc_trade_projection_watermark` 和 `dc_trade_financial_readmodel_cursor` 仍是 60103/60103，**真实积压 241 序号**。不能因为两条 SQL 游标相等，就说资金已追到权威 WAL HEAD。

## T453：真实 Order B 部署与交易验证

- 构建 `local/otc-t453-ordersvr:standby-parent-watch`，基于原 `local/otc-t450-ordersvr:common-zk-rejoin`，仅添加 Common `ZkCluster*.class` 五个 class；不改 Order 业务状态机、风险规则或 Gateway 透传。
- 容器 `otc-t453-order-b-standby-parent-watch` 复用原环境、host 网络与原始数据卷，旧 `otc-t450-order-b-common-rejoin` 停止、保留回退。没有清理或更改 WAL、RSA、Snapshot、财务表。
- 原始 WAL CommitIndex 逐条物理证书验证（`DurableWalCommitIndex.loadAndVerify` 和 `DurableWalCommitQuorum.verify`）后，08:31:55 Order B TCP 33041 监听且 `COMMON_GATEWAY_DISCOVERY_CERTIFIED exactOwnerSession=true`，08:31:59 `TradeSvr physical client connected: SERVER.TradeSvrB`。
- 08:32–08:33 的真实 DAYWUB Robot 日志：121 条 `TRADESVR_NEWING_COMMIT_END location:DAYWUB targetStatus:New`，**0 条 [1015]**；Robot 回到 RUNNING、`OPEN_ORDERS_OK count=40`。
- 08:38–08:42 再观察：330 条 DAYWUB `New`、0 条 [1015]。08:39 有一条 `ORDER_COMMON_PENDING_CANCEL_STILL_RECOVERING ... ORDER_COMMON_CANCEL_NOT_FOUND`，源码 `OrderCertifiedCancelSaga.beginPendingCancelRecovery` 先遍历快照后 `cancelOne` 再次查找订单，可能在这段时间内被其他线程终结。单次告警后未持续复现，**不能据此声称撤单全量 PASS**。

## T454：真实 Projection 消费积压修复

- 构建 `local/otc-t454-projectionsvr:common-zk-rejoin`，基于原 `local/otc-t437-projectionsvr:financial-readmodel-disabled`，仅叠加已验证 Common `GwClient*.class` 五个与 `ZkCluster*.class` 五个。保留原应用二进制消费者、`-Dprojection.trade.binary.enabled=true`、`-Dtrade.financial.readmodel.enabled=true`、MySQL 及原数据卷。
- 停止并保留旧 `otc-t448-projection-trade-consumer`，启动 `otc-t454-projection-common-rejoin`。08:38 新进程启动，日志 `CERTIFIED_TRADE_FINANCIAL_READMODEL_STARTED pollMs:1500`，新客户端再次读取 `TradeSvrB0000000021` 成员。
- 真实数据库 P144 两游标：**60103/60103 → 60349/60349 → 61251/61251 → 61596/61596**，均为 0 差值。08:41 前的 Trade B 物理 CommitIndex 为 `commit-00000000000000061552.bin`，已被新消费者追过。
- 五个已有 Trade 财务分区 P129/P144/P238/P240/P242 的 Projection 与 ReadModel 游标逐分区一致。
- 在 P144 序号 60103 之后的认证 Mutation 中，DAYWUB 存在 `ACCOUNT_BALANCE=1151`、`POSITION=1151`、`OPEN_ORDER=1151`、`DEDUPE_RESULT=1151`（截至 61251）；`POSTING=6`，分布于三个不同 journal_seq。Posting 内容的 `ID` 为签名 `E2TRADE-...`，发生于 08:34、08:37、08:39，覆盖 DAYWUB 做市/Tape 两个用户，是**真实认证成交资金事件**，不是模拟盘口更新。
- 使用最新已落库认证 Mutation 后状态，对 `DAYWUB` 的 MySQL 资金数据：**2 个账户** balance、used_margin、freezed_margin、freezed_commission，全部 0 不一致；持仓数据：**2 个持仓** leverage、long_position、short_position、long_used_margin、short_used_margin，全部 0 不一致。
- DAYWUB Robot 仍 `RUNNING`，最近开放委托数 40；Order B、Trade B、Gateway、Projection、Robot、MD A/B 容器均运行且无 OOM。

## 提交与后续门禁

- Common T449 物理客户端修复：`2531b3a53251008e087666b5afcb0888576b7600`。
- Common T451 ZK STANDBY 成员监听：`d2f545649a71e0fb5185afc1a0ae9e541c3033c2`；706 项 Common 测试通过。
- Trade T452 有界签名 WAL 冷恢复：`9c8425b82d3f3416b4a3155f07b9e03cd49290a4`；216 项 Trade 测试通过。
- T453 与 T454 均为**本地已验证公共类覆盖镜像**；原服务容器和 WAL 保留。此报告记录准确部署实例、镜像 tag 和物理验收结果，不宣称已发布完整服务重建镜像或使用 GitHub Actions。
- 剩余：Order 投影旧 P060 物理 writer 不可用等分区问题须单独处理；Order/Trade A/B 全部统一最新 Common 接线、双向自动主切、旧主拒写、真实 ACK/CommitIndex/WAL 和全分区/资金/持仓/委托/成交一致性仍 **NO-GO**。MD 的 QuerySymbol→APS/Binance 自定义价格源逻辑不可与 Order 源误混，MD HA 仍需单独注入验证。

**本轮结论：T453 Order→Trade 客户端自动重连及真实下单 PASS；T454 Trade 财务投影追平及 DAYWUB 逐字段对账 PASS；完整 HA 仍 NO-GO。**
