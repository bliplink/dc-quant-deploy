# T545｜ORDER_ONLY 明确走 DefaultExecOrder，成交与 TRADE 共用发布路径

日期：2026-11-07。适用：OpenTradingCore SaaS，Order `saas-crypto-latest`、Common 认证 WAL。

## 架构纠正（用户明确）

- `matching_mode=ORDER_ONLY`：`ProductMatchingExecOrder` 按租户和 security_id 路由到现有 `DefaultExecOrder`。不调用 TradeSvr 进行风险冻结、成交资金/持仓结算。
- `matching_mode=TRADE`：继续由 `TradeExecOrder` 触发 TradeSvr 风险、资金/持仓结算。
- **两模式共用同一套 Order 撮合和业务成交后处理**：Maker/Taker 成交事实、ExecType=Trade、确定性 ExecID、订单历史、最近成交、MD 与 OHLC/K 线、对外推送。不能将 ORDER_ONLY 解释为“仅变更订单状态，不产生真实成交”，也不能另造一种行情流或独立集群协议。
- Common 只负责业务字节帧 WAL、物理提交 ACK、复制、Snapshot、恢复、选主/隔离。业务匹配模式和成交报文由 Order 负责。

## 具体根因

原 `DefaultExecOrder.Trade()` 给 Filled/Partially_Filled 的执行回报设置 `ExecType.OrderStatus`，并在找不到 Order 时 `continue` 静默跳过。已经改为真实 `ExecType.Trade`，缺失权威订单直接拒绝。该老路径的业务状态变更与 `OrderFacade.addExecOrder` 后续成交历史/MD 侧效果本来就是现有机制。

认证 WAL 模式 `CrossStrategy.matchOrder` 则直接提交 `STATE_ATOMIC_MATCH_V1` 双订单 after-state；Common 回调 `OrderStateRecovery.apply` 已更新订单和盘口，因此**不能**在已认证的撮合之后再次调用旧 `DefaultExecOrder.Trade()`，否则重复累计成交量、数量及资金数据。原程序仍通过 `OrderSignedMatchDeliveryWorker` 等待 TradeSvr 的财务 RSA 回执才发布两条 `ExecutionReport`，但 ORDER_ONLY 没有财务回执，导致 Filled 后最近成交/历史/K线缺失。

## T545 最小业务层候选

GitHub repo `bliplink/com.app.dc.ordersvr`，从 `saas-crypto-latest` 创建隔离分支 `t545-default-exec-unified-candidate`（不含 T544 多余 business WAL marker）。代码：

1. `DefaultExecOrder.Trade`：保留原路径，只修正成交回报必须是 `Trade` 及缺失订单必须拒绝。
2. `DefaultExecOrder.publishCertifiedMatch`：接受 Common 已签名持久化的原始 Match 并校验 partition、epoch、seq、matchKey；由原始 after-state 和同一个 `OrderCertifiedMatchSettlementEnvelope` 产生两条确定性 ExecID 的历史执行，使用**现有** `IOrderDao.insertExecOrder`；使用**同一个** `PublishOrder.publishCertifiedSettledMatch` 将 Maker/Taker 送往 MD 和 Robot，不二次调用 `OrderFacade.addExecOrder` 修改订单状态。
3. `OrderSignedMatchDeliveryWorker` 仅按 `SymbolRuleFacade.matchingMode(location,securityId)` 选择业务分支；TRADE 原业务 RSA 财务确认保持不变；ORDER_ONLY 进入 Default 统一报告处理，不调用 Trade RPC。不新增 OrderOnlyMatchNotificationAck、ORDER_ONLY 特殊 Common 事件或独立 ReadModel。
4. `ORDER_ONLY` 新接线在候选分支依旧由 `order.orderOnly.certifiedDefault.enabled=false` **默认关闭**。暂存 Common 原始 Match outbox（此处只作进程内一次投递提示，不是持久 MD ACK）。

## 候选测试与剩余门禁

从远端真实分支拉取 `defe4f9` 并在独立干净 worktree `.work/t545-default-exec-validation` 中，使用 Java 8、现有 Common 编译类及本地 Maven 缓存依赖，增量编译成功，**18 项 JUnit 全部 PASS**：覆盖 Default 完整/部分成交回报和拒绝静默丢单、同租户路由、认证 Maker/Taker ExecID 与 TRADE 业务报文一致、ORDER_ONLY 无 TradeSvr RPC、默认开关拒绝提前发布、Trade 原财务路径不变、失败拒绝，以及原有 Outbox 约束。这个结果**不是完整 Maven Release / 容器 E2E / HA PASS**。

**仍然不能正式部署这个候选**：当前既有 `IOrderDao.insertExecOrder` 和 Gateway 发布队列是异步的；已经入队不等于 MySQL/MD 均持久接收。ORDER_ONLY 原始 Outbox 在当前候选不会持久退休，故障恢复或长时间积累可能导致重放/重复 MD 成交或容量门禁问题。需要复用现有确认/重放与 MD 的业务幂等机制，验证丢包、重启和重复 ExecID，不得凭内存提示冒充持久确认。不能重新引入独立 ORDER_ONLY ACK/集群语义。

接受之后先在隔离新租户下做两笔真实 Default 撮合，核对 2 个唯一 ExecID、MySQL 成交历史、MD 最新成交、ClickHouse K 线推进且 Trade 资金/持仓不变；接着再做 Order A/B 主备自动双向切换与一致性，最后可切换正式 `saas-crypto-latest` 镜像。

## T544 纠错

`docs/T544_ORDER_ONLY_CERTIFIED_BUSINESS_E2_20261107.zh-CN.md` 及 `t544-order-only-business-publish-candidate` 中的 `STATE_MATCH_ORDER_ONLY_NOTIFIED_V1`、单独 Order-only 历史投影类和单独回执协议**被 T545 纠正方案取代，不应合并或部署**。T544 的已验证 TRADE / K线 / ClickHouse 运行数据不受此业务边界纠正影响。