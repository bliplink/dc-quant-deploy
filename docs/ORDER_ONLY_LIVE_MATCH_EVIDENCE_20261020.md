# ORDER_ONLY 真正 Demo 撮合和 Trade 账本隔离验收（2026-10-20）

## 结论

`python3 tests/test-order-only-product-live-e2e.py --execute` 在新的、自动审批的独立测试租户 `S7S98G` 返回退出码 0。产品 `BTC003USDT` 在当前 Admin/Order/MD/APS 部署镜像下选择 `ORDER_ONLY`，双方订单真实撮合。**本证据只覆盖 ORDER_ONLY 两方成交及 Trade 资金/持仓隔离，不代表并发压力、断线恢复或集群 HA 已通过。**

## 真实验证结果

- TenantAdmin 正常登录，CUSTOM 来源与启用产品创建，`dc_tenant_symbol.matching_mode=ORDER_ONLY`。
- 两个普通交易员以正常注册/WEB 登录取得不同的 12 位 `user_id`；没有进行 TradeSvr 入金。
- 临时签名 Broker Key 发布 `index=90000, mark=90001`；MD 公共行情返回标记价 `90001`。
- Maker 卖出 0.001 @ 90000；待其持久化成 `New` 后，Taker 买入 0.001 @ 90000；两条 `dc_orders` 记录均达到 `Filled`。
- 对该租户和产品的读库核对：**两条唯一 execution，均为 0.001 @ 90000**。
- 对两名测试交易员分别对比撮合前后的 `dc_users_balance`：**没有变化**；`dc_orders_position` 该产品的持仓记录均保持 **0**。
- 临时 Broker Key 删除响应 `code=0`；没有 HA 故障注入，也没有直接写数据库。

## 本轮修复的验收误报

第二次验收 `T1XE5N` 曾在交易和成交记录通过后出现断言 `ORDER_ONLY unexpectedly changed TradeSvr balances`。只读 SQL 后确认变更来自**第三名流动性账户**（`liquidity_*`）的异步 Demo 启动入金 `10000`；Maker 与 Taker 两个独立账户仍为 `0`，该产品 Trade 持仓记录 0。这不是 ORDER_ONLY 对测试交易员扣款的证据。此前测试错误地将**全租户的所有用户**作为余额不变比较目标。

测试脚本修复为仅比较两名被测交易员的资金和该产品持仓，并在 Broker 新 Key 未同步至 Gateway（`7000/7004`）时有界重试**只读登录**；不重试任何状态不明的写订单。第一次测试 `PQCV4O` 在签名 Broker Key 登录处收到 `7000` 后停止并撤销临时 Key；后两次新租户 Broker 登录首次均成功，因此无法断言出现了持续的网关缓存问题。

## 未验证范围

- ORDER_ONLY 撤单、未完成挂单服务重启恢复、跨租户隔离和并发大压力。
- SDK Gateway 行情通知实际推送、私有账户通知和断线重订阅。
- Trade / Order / MD 的 HA 自动主切、200 租户负载、最终一致性。

重现命令只应在隔离 Demo 环境执行；会真实创建测试租户、产品和少量测试委托。此记录不包含密码、Key 或 Session。

## Python SDK 公开实时通知：新增真实成交触发验证

在新的独立租户 `PZT10Y/BTC003USDT`，使用 OpenTradingCore Python SDK 0.1.6 `MarketStreams` 于 Maker/Taker 撮合**前**建立匿名连接和订阅。执行 `PYTHONPATH=.work/sdk-realtime-probe-deps:.work/api-python-methods-corrected-016-20261020/sdk_source python3 tests/test-order-only-product-live-e2e.py --execute --verify-streams`，退出码 0。真实 Gateway 事件而非仅 ACK：

- `dc.md.depth.snapshot.BTC003USDT.PZT10Y`：1
- `dc.md.depth.diff.BTC003USDT.PZT10Y`：1
- `dc.md.market.trade.BTC003USDT.PZT10Y`：1
- `dc.md.trade.BTC003USDT.PZT10Y`：1

本次订单同样 2 笔 `Filled`、2 条唯一 execution，Maker/Taker 两名交易员资金和持仓均未变化；临时 Broker Key 关闭成功。测试仅记录 topic 和数量，不打印用户密码、Secret、Session 或正文。该测试使用 Python `websocket-client==1.8.0` 可选依赖。未观察到 K 线 notification，不能据此宣称 K 线、账户私有事件或断线恢复已通过。
