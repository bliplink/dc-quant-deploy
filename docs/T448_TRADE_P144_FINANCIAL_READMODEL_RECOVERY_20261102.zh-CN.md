# T448｜DAYWUB Trade P144 认证投影与财务 ReadModel 恢复验收（2026-11-02）

## 现场确认

- Demo 服务在本轮开始时 Order A/B、Trade A/B、MD A/B、Robot 和 Gateway 均运行且未 OOM。
- `DAYWUB/BTCUSDT` 已真实撮合、`Filled`，Robot 运行；但 `dc_trade_projection_watermark[P144]` 和 `dc_trade_financial_readmodel_cursor[P144]` 均停在 Epoch 2、序号 **34**，更新时间 12:59。
- Trade B 当前物理卷 `/srv/dc/data/t398-ready-v1/TradeSvr/TradeSvrB/TradeSvr/TradeSvrB/P144/epoch-2/business.wal` 不断增长，已存在最高约序号 6512 的 `commit-index` 文件，说明 Query 投影显著落后于物理 WAL 提交索引。
- Projection 的 `CertifiedTradeFinancialReadModel` 自身已启动且能处理现有投影事件；`TradeProjectionBinaryConsumer.class` 存在于镜像，但重启前日志未见该消费者的启动记录。不能把这解释为财务计算错误或直接删 WAL。
- Projection 日志还有大量 **Order** 侧 `SERVER.OrderSvr is not Online` 与 P060 的物理 writer 不可用，这与 Trade 财务事件落后是不同的问题，不能混淆。

## 本轮受控恢复

- 原 Projection 容器 `otc-t440-projection-financial-readmodel` 停止但保留，可回退；**未删除任何卷、WAL、MySQL 数据或认证凭据**。
- 新建并启动 `otc-t448-projection-trade-consumer`，复用完全相同的原镜像、网络、环境和数据卷，显式加入 JVM 启动参数：
  - `-Dprojection.trade.binary.enabled=true`
  - `-Dtrade.financial.readmodel.enabled=true`
- 受控重启之后 `dc_trade_projection_watermark[P144]` 与财务 ReadModel 游标由 34 迅速追到 7064，再一致推进到 7167、7258 以及更高值。Trade B 原 WAL 继续保持原状。
- **不要把“重启+显式参数”推断成单一根因**；本轮还没有完整复现区分条件配置、运行期连接状态和重新订阅触发的作用。须保留该缺陷追踪，并修复无自动连接恢复的问题。

## 财务实测

- 在 P144 序号 7167 时，`dc_trade_projection_event` 条数 **7167**，最小序号 1、最大序号 7167、去重序号 7167，无缺号。
- P144 同时查询 Projection 水位与财务 ReadModel 游标，二者 **7167/7167**；隔 7 秒再次查询结果一致。随后两者继续一致推进到 7258。
- 另四个现有 Trade 财务分区 P129/P238/P240/P242 同样满足 Projection 水位 = 财务游标，**共 5/5**。
- 对 `DAYWUB` 的 2 个账户，将最新已认证 `dc_trade_projection_mutation` 的 JSON 后状态与 MySQL `dc_users_balance` 的 balance、used_margin、freezed_margin、freezed_commission 精确 DECIMAL 比较：**2/2，0 不一致**。
- 对 2 个 `DAYWUB/BTCUSDT` 持仓比较 leverage、long_position、short_position、long_used_margin、short_used_margin：**2/2，0 不一致**。
- 两个账号的实际杠杆均为 100×，余额/保证金与多空持仓在交易后发生真实更新。不要把旧业务订单表缺少数据当成 Common WAL 事件不存在。

## 边界与剩余 NO-GO

- 当前证据支持 **已落库认证事件 → 财务 ReadModel 逐字段一致**，不等于覆盖全部分区、所有资金流水及 Trade A/B 主备切换全过程。
- Gateway/公共 RPC 客户端在后端节点重启后，存在“物理连接回来了、路由/订阅未自动恢复”的历史症状。当前 Gateway 镜像的 `gw-3.0.12.jar` 已包含 `GWApi.ConnectionCycle`，所以 **不能误将旧版 `isFirstConnected` 单次订阅缺陷当成现网根因**；必须继续核查实际回调/客户端连接与 ZK 观察证据。
- Order P060 已有旧主 Epoch 失权和副本历史恢复问题；不能通过重用旧 Epoch、直接改写水位或删除 WAL 消除。
- 还需执行 Trade A/B 与 Order A/B 自动主切故障注入、ACK/CommitIndex/WAL、资金/持仓/成交及 Projection 的前后权威对账，以及 MD 价格续推、自动回连、旧主隔离。

**结果：T448 财务投影恢复与 DAYWUB 逐字段对账 PASS，整体 HA 仍 NO-GO。**
