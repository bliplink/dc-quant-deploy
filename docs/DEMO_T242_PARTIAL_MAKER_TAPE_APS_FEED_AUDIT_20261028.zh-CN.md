# T242｜Order/Trade 通用部分成交状态与 APSSvr aggTrade 实时恢复验收

**日期**：2026-10-28 CST。代码分支：各仓 `saas-crypto`。Demo 状态：**NO-GO**，未达到“Robot 持续点价成交、Order/Trade A/B 自动双向互切且账目一致”的终验标准。

## 原则

Common 仍只管理 opaque `byte[]` / WAL / TCP 复制 / fsync / CommitIndex / Snapshot / Recovery / HA，不新增 IOC/FOK/Trade/手续费/持仓类型白名单。Order 计算任意业务 after-state，Trade 计算资金和持仓 after-state；服务间以认证业务消息加各自的 Common 原子提交闭环。不能把普通 API 200、单元 FakeCommon 或 MySQL 读数冒充物理证书和真实订单。

## 本轮订单功能进展

- 新增 `OrderCertifiedPartialMakerPlan`：例如 Maker 挂单 0.003 BTC，Tape IOC 0.0003 BTC，同一条认证业务 WAL 更新 Maker 累计成交量/价格并以 UPSERT 留在盘口（余额 0.0027 BTC），Taker 完成 REMOVE Filled。无提交前 live book 修改。
- 扩展原 `STATE_ATOMIC_MATCH_V1` 域模型和 `OrderCertifiedMatchSettlementEnvelope` 支持 Maker `UPSERT Partially_Filled` + Taker `REMOVE Filled`，以及 Maker 上轮部分成交、这轮刚好吃完时正确累加 CumQty / CumAmount / LastQty / LeavesQty。保持原完整成交和 E2 WAL 格式回放兼容。
- Order 实际 `OrderFacade.commitPreparedExactlyFilledMatch()` 在 Maker 余额足够时自动选择完全成交或 Maker 部分成交的业务计划，仍走原 Common 单事务认证及 Order→Trade Outbox。超过单 Maker、无 Maker 的 IOC 剩余取消及 Market/Close 的完整计划仍未放开。

## 本轮资金功能进展

- Trade `TradeOrderMatchEconomicEvidence` 在固定节点 RSA 验签之后，**逐字段比对** Order 原始 `STATE_ATOMIC_MATCH_V1` signed WAL 后状态和 Maker/Taker 经济报告，含用户、产品、Qty、CumQty、LastQty、LastPx、LeavesQty、Maker/Taker 与确定性 ExecID。即便签名有效，篡改报告数量依然拒绝改账；绝不改变 Common。
- Trade `TradeCertifiedOpenFillPlan` 根据本次成交数量结算资金和持仓/手续费，Maker 未成交的部分继续保留冻结、open order UPSERT 和执行去重；完成一侧订单则 REMOVE。一次 Maker+Taker 的 after-state 保持 10 个业务 mutation 放进一条 Trade Common WAL，先提交后 apply。
- 单 Maker 两次真实经济事件的本地 FakeCommon 回归：第一笔部分成交后保留冻结，第二笔吃完 Maker 后释放剩余，重复 ExecID 不再追加任何新的资金 WAL。该测试不是独立 JVM 物理 Custody 证书。

## 编译/回归（Mac 本地，不使用 GitHub Actions）

- Order：**118 Java 8 主源码编译 PASS；30/30** 相关测试 PASS。
- Trade：**167 Java 8 主源码编译 PASS；36/36** 相关测试 PASS。
- APSSvr：项目原编码 GBK，**99 Java 8 主源码编译 PASS；5/5** 相关单测 PASS。
- 实际 Order JSON WAL + `OrderTradeSignedMatch` RSA 业务签名 + Trade 原始经济逐字段认证跨仓 CLI 合约测试输出：`REAL_ORDER_PARTIAL_WAL_TO_TRADE_ECONOMIC_CONTRACT_PASS makerLeaves=0.0027 takerStatus=Filled`。
- 编译使用现有 Maven `target/dependency` 和 Java8 `javac`；Mac 本机无 `mvn` 命令。与正式 Maven Release / 新 Order、Trade 镜像真实部署验收不同。

## APSSvr 现场实际修复与限制

- 旧 Binance Futures `BNFuturesImpl.subscribeSymbolTradeEvent` 打开 aggTrade socket 后**没有注册 tradeLt**，也无连接 ID、消息时间、定时断线恢复；ticker/mark stream 独立恢复正常，因此 Robot 可得到 mark 价但 Tape 真实 Binance 成交源序号长期不变。
- 在 APSSvr 业务连接器增加按 Symbol 的 `tradeLastMessageHm`、连接 ID、注册幂等、超时/异常重连、只认证格式正确 aggTrade 才刷新心跳，不修改 Common。添加低频的 `APS_AGGTRADE_SOURCE_FIRST_ACCEPTED` 与 `APS_AGGTRADE_GATEWAY_FIRST_PUBLISHED` 观察点，区分外部 WebSocket 与内部 Gateway 发布问题。
- 在 Mac 使用旧镜像 `local/otc-t219-apssvr:binance-mark-1s` 作为基底，仅以带全部 Java 匿名内部类的覆盖层构建 `local/otc-t242-apssvr:aggtrade-health`；`docker compose --env-file .env.prod -f compose.yaml -f compose.t219-aps-mark-one-second.yaml -f compose.t242-aps-aggtrade-heartbeat.yaml up -d --no-deps --force-recreate apssvr` **只替换 APSSvr**。保留原 Host 网络、6 挂载、登录与配置，Order/Trade A/B 和 Robot 均未重启。
- 首轮新 APSSvr 现场启动日志明确 4 个 aggTrade WS 已订阅且 Open（BTC、ETH、SOL、UNI），0 JVM 重启。然而 Robot 在 16:01 CST 的 `lastSequence=158976`、`events=0` 仍未更新。Gateway 约 12s 清除、重建 trade topic 的现象已经记录，可能涉及下游过滤/会话刷新。**不能宣布 Tape 恢复。** 添加了二段一次性诊断，等待实际新版 APSSvr 初始化完成后核对源与 Gateway 哪段未达。

## 尚未完成的用户验收

1. APS→GW→Robot Binance aggTrade 真实事件持续增加、Robot Tape 真实 IOC 请求触发。
2. Order/Trade 新签名部分成交和财务闭环正式镜像构建与**物理 Common RSA 2/2 CommitIndex/Custody**，新租户自动审批后 Robot 稳定报价；对 IOC 无对手/多 Maker、FOK 跨多档、Market/Close 等业务仍需完整规划，不允许假成功。
3. Trade Common 认证 CommitIndex 投影到 MySQL Orders / Executions / Postings / Positions / Balances；实际 Filled 计数大于 0，双边金额和手续费一致。
4. Order/Trade A/B 自动 SIGKILL 主备互切及回切、旧主隔离、恢复水位、无丢单/双重成交；之后多租户负载测试。

## 不允许的验收捷径

- 不允许通过取消 Common 的物理认证、关掉订单资金风控、伪造 Filled 或用无真实交易的日志报终验通过。
- 原 Demo 数据和有效服务保留；仅 APSSvr 子服务已做可回滚定向替换，旧镜像 `local/otc-t219-apssvr:binance-mark-1s` 不删除。
