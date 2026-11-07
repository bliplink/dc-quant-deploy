# T542｜K线恢复与全功能验收（2026-11-07）

## 本轮结论

**部分通过，整体 NO-GO。** 已恢复 BTCUSDT 真实 K线历史与 WebSocket 实时图表，并验证租户自动审批、六租户双边报价与 Tape、Trade 结算、自定义 TRADE 产品、Broker 签名、Python SDK、数据源切换。**两个缺口尚未关闭：ORDER_ONLY Filled 无成交回报，以及首开选择无活跃K线的自定义产品。** 本轮未执行真实 A/B SIGKILL、全订单类型、移动端和 50/200 租户性能；不可标记全部通过。

## K线三个问题的定位

**存储**：隔离 Demo ClickHouse 容器 otc-t532-fresh-clickhouse 已 OOMKilled，exit=137，内存上限1.5GiB，MD不断报 ClickHouse connection is null。保留原数据卷，Docker 将内存升至3GiB、swap 4GiB、restart unless-stopped 后启动，历史K线与市场成交批量写入恢复；Compose 默认及私有 .env.prod 同步改为 CLICKHOUSE_MEMORY_LIMIT=3072m，不上传私有env。三GiB是当前恢复参数，需做长稳态压测。

**网关接线**：运行中四个前端仍代理旧GW HTTP33002，交易Web还代理旧WS33001；新 Demo Gateway 实际 HTTP43002/WS43001。旧GW仍返回 HTTP200 但 querySymbol 空、queryKLine 空，导致所有Web页面无产品/K线。备份 Nginx 到 Mac 私有目录 ~/.opentradingcore/t542-web-e2e/nginx-backup，针对四个前端热改为 HTTP43002，交易Web WS43001，nginx -t PASS并reload，四前端均可返回有效历史K线。当前容器热修复不等于新建容器持久化；正式一键部署必须使用 Compose 的 GW_HTTP_PORT/GW_WEBSOCKET_PORT，不可将43002永久硬编码到通用模板。

**首次选品**：Web源代码 resolveTenantDefaultSymbol 默认取启用目录中的第一个产品。某些旧QA租户第一项 BTC003USDT 无最新成交/K线；虽 BTCUSDT 已正常，首开仍显示 Chart Waiting for data。不得简单强行默认BTCUSDT，因为租户支持自定义唯一产品。需要基于有效实时行情或保存的用户选品做默认项，也需要无成交时给明确状态。

## 验收矩阵

| 功能 | 状态 | 真实证据 |
|---|---|---|
| ClickHouse/MD历史K线写入 | PASS（运行时） | OOM解除、kline/market_trade恢复，错误停止 |
| 四个前端 HTTP 接线 | PASS（当前容器） | 18088/18090/18092/18094从新GW返回5M历史 |
| 六原有租户 BTCUSDT 盘口/最近成交 | PASS API | 各10档bid+10档ask、最近成交200条且有时间与ExecID |
| 六租户 24h/Mark/Index/Volume | PASS API | ticker字段校验，有实际数值 |
| 六租户 BTCUSDT 1M/5M/15M/1H | PASS API | 四周期均有真实OHLC，最近5M有更新 |
| 匿名Web选 BTCUSDT 的5M图 | PASS 浏览器 | Headless Chrome实际6条历史K线、2次实时推送、Mark/Index/24h非空，JS错误0 |
| 首次匿名页面默认K线 | **NO-GO** | A2I12Z/BML3DA 默认BTC003USDT历史0条，手选BTCUSDT正常 |
| Robot/Tape/Trade业务 | PASS | 原6租户Robot运行并持续报价、真实Tape Filled ExecID无重复、Trade认证POSTING每撮合2条，资金投影更新 |
| Broker自定义数据源A→B切换 | PASS | 独立租户H2YGSA，90001→110000（22.22%）、旧源失效、TTL15秒到期不回退，撤销API Key |
| 自定义TRADE产品 + Python SDK | PASS | 独立租户VEGLLJ，自定义BTC003USDT、Broker SDK签名、两个Trader各入金1000，Maker/Taker均Filled，2条成交、双方持仓0.001 BTC，余额999.982/999.946，密钥清理 |
| ORDER_ONLY真实撮合 | **部分通过 / NO-GO** | 独立NRPH66：Maker与Taker均Filled、cumQty0.001，但 dc_orders_execorders 0，MD最近成交0，产品LastPrice空，K线不可得 |
| 公开目录与权限隔离 | PASS API | 六租户公共目录只返回启用产品；匿名Admin LIST 返回9002，未泄露后台数据 |
| Web单元测试 | PASS | Mocha kline6、orderbook3、market-health2、position-risk3、ticker3、symbol-catalog6，共23项；新增Python市场验收单测6项 |
| 全量移动端/订单规则/撤单/清算/ADL/50和200租户性能/A-B SIGKILL | **未验收** | 不得以其他功能PASS代替 |

## ORDER_ONLY 原因进一步确认

Order 业务的 ProductMatchingExecOrder 按 matching_mode 选择 DefaultExecOrder (ORDER_ONLY) 或 TradeExecOrder (TRADE)，这没有问题。但是认证撮合链路 OrderFacade.commitPreparedExactlyFilledMatch 通过 Common物理签名WAL提交后，OrderSignedMatchDeliveryWorker 仍按 TradeSvr settleSignedOrderMatch 回执 → Order二次认证ACK → PublishOrder.publishCertifiedSettledMatch 来通知 MD/Gateway。ORDER_ONLY 原本不应走 Trade 资金、持仓结算，因此现有“统一依赖Trade回执再发布”的业务门禁不适合ORDER_ONLY。**必须在Order业务层完成签名事件幂等、安全、可恢复发布；绝不让Common理解ORDER_ONLY，不得伪造成交或手动补历史数据库。** 尚未对运行中的Order A/B修改/升级。

## 本轮脚本与可复现命令

- 市场、K线与四站只读：python3 tests/check_demo_full_market_readonly.py。结果6/6核心市场API PASS，但有两项首开默认K线缺口，脚本刻意返回 PARTIAL_DEFAULT_KLINE_NO_GO（exit3），不得掩盖。
- Tape与资金只读：python3 tests/check_trial_robot_trade_e2_readonly.py --mysql otc-t529-fresh-mysql --order-a otc-t531-order-a-e2-abcontrol --order-b otc-t531-order-b-e2-abcontrol --minutes 10 --min-locations 6。
- Chrome实测：T542_FORCE_SYMBOL=BTCUSDT node ~/.opentradingcore/t542-web-e2e/check_chart_cdp.js。无选品覆盖时可复现首开BTC003USDT空数据。
- Broker真实A/B切源：python3 tests/test-price-source-switch-live-e2e.py --execute --endpoint http://127.0.0.1:43002/httpapi/。
- Broker/Trader TRADE模式：PYTHONPATH="$PWD/.work/sdk-realtime-017/sdk/python" OTC_E2E_MYSQL_CONTAINER=otc-t529-fresh-mysql python3 tests/test-custom-product-live-e2e.py --execute --with-traders --sdk-signed --endpoint http://127.0.0.1:43002/httpapi/。
- ORDER_ONLY 复现失败：OTC_E2E_MYSQL_CONTAINER=otc-t529-fresh-mysql python3 tests/test-order-only-product-live-e2e.py --execute --endpoint http://127.0.0.1:43002/httpapi/。原旧测试硬编码已停的 dc-saas-mysql 导致先验失败，现已支持 OTC_E2E_MYSQL_CONTAINER，真正揭示业务报表缺口；不改数据库。
- 公开租户产品只读：python3 tests/test-public-tenant-product-e2e.py --api-only --gateway http://127.0.0.1:43002 --tenant A2I12Z --tenant AGKW5V --tenant BML3DA --tenant CN8U7C --tenant J4BMAH --tenant RU7WZO --expect BTCUSDT。

保留当前运行的所有核心容器，未注入HA故障；Maven构建和镜像的正式统一发布、Web默认项优化、ORDER_ONLY可靠成交投影仍为后续任务。