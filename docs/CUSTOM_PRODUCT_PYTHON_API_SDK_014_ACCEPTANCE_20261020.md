# 自定义产品 + Python SDK 0.1.4 交付验收（2026-10-20）

## 本轮交付与版本

- API Docs 主机：`api.opentradingcore.com`，英文/中文同一 OpenAPI 源；本地容器 `dc-saas-api-docs-1`。
- 最新部署镜像：`local/dc-saas-api-docs:sdk-014-20261020`，容器 `healthy`。
- Compose 覆写：`config/api-docs-sdk-014-20261020.yaml`，搭配已有 `config/frontend-language-rollout-20261020.yaml`，只替换 `api-docs`，不重启 Gateway/Order/Trade/MD/Common。
- SDK 仓库：`.work/opentradingcore-api-docs`，`saas-crypto` 分支，提交 `bcf9627`。
- Wheel 下载：`https://api.opentradingcore.com/sdk/opentradingcore-0.1.4-py3-none-any.whl`。
- ZIP 下载：`https://api.opentradingcore.com/sdk/opentradingcore-python-sdk-0.1.4.zip`。
- 本次升级没有运行 GitHub Actions、发布 Maven Common、修改 HA 状态机、删除交易数据或者访问 Mac `文稿` 目录。

## 1. Trader API Key 与真实交易

- Python 客户端 `OpenTradingCoreClient.login(mode='trader')` 的 HMAC-SHA256 登录、同租户 `UserID` 和 `Location` 绑定、`OrderSvr/placeOrder`、`cancelOrder`、`AdminSvr/queryOrder/queryExecOrder`、`TradeSvr/queryAccountBalance/queryTradePosition` 均有 SDK 契约单测。
- 新增 `account_config`、`set_leverage`、`set_position_type`、`cancel_batch_orders`，以及只重试**只读查询**的 `wait_for_order_ready()`；拒绝自动重试有不确定结果的写操作。
- 之前的真实 Maker/Taker 两交易员自定义产品 `BTC003USDT` 开仓已通过，但主要使用 WEB token 而非两把新的 SDK Trader Key。
- 本次新建 Demo 租户 `B0T3YG`，真实签发并成功登录一把 SDK Trader Key；该 Key 已撤销，未打印 Secret。本轮完整签名交易流程在后续 `CUSTOMER_CASH` 测试路径上停止，不能声称两把 Trader Key 实际完成开仓、平仓、撤单或 PnL 对账。
- `tests/test-custom-product-live-e2e.py --execute --with-traders --sdk-signed` 已补独立签名流程、密钥撤销和 Web 模拟资金准备；最后修订后的完整写入验收**未重新运行通过**。下一轮先用正式本地测试授权环境完成该命令，再做 `--near-simultaneous` 和 CLOSE/ReduceOnly 对账。

## 2. Broker Key 代客操作

- SDK 中 `place_customer_limit_order`、`cancel_customer_order`、`customer_order_history`、`customer_execution_history`、`cancel_customer_batch_orders` 均带强制客户 `UserID`、签名租户及 Broker `ORDER_READ/ORDER_WRITE` 检查；有相应请求契约测试。
- 新建 Demo 租户 `B0T3YG` 下 Broker API Key 的 **Python SDK 签名登录成功**；自定义源 `QA_ALT_...` 的 **SDK `publish_price` 成功**。测试密钥已经注销。
- 服务端与租户 Web 当前明确限制普通 Broker Key 仅为交易权限：不支持 `TENANT_WRITE` 或 `CUSTOMER_CASH`。曾实测拒绝模拟入金 `Broker API session lacks required CUSTOMER_CASH`，属于正确权限拒绝，不是价源/撮合缺陷。
- `create_customer`、`customer_cash_in/out` SDK 方法仅允许具有明确特殊权限的会话；**不能误写为普通 Broker Key 提供的对外功能**。当前新建客户和模拟入金应从租户 Web / WEB 用户流程进行。外部 Broker 代客下单/撤单/平仓真实完整闭环仍待验收。

## 3. 自定义产品与 SDK 改进

- 新增无需账号/API Key 的 `PublicMarketClient(base_url, location)`，支持 `.products()` 与 `.snapshot(symbol)`。
- SDK 0.1.4 Wheel 安装后的实际 localhost HTTP：租户 `N9NZV5` 匿名产品列表包含 `BTC003USDT`，`MDSvr/queryPublicMarket` 快照返回相同租户/产品；租户 `H2FIJU` 的已停用 `BTC001USDT/BTC002USDT` 不公开。
- 自定义产品始终只有**一个**当前数据源；用户显式 BIND 便使用新源，价格 TTL 过期即失效，不回退旧源、不检查切换时相对涨跌幅 1%。此前真实 Broker APS 价格发布成功。
- 测试仍记录 `query_symbol_refresh=QUEUED`，新增产品 Admin 可见可能早于 Order 目录就绪。SDK `wait_for_product` 和 `wait_for_order_ready` 用只读轮询，不改变后端异步传播机制。

## 4. WebSocket 与文档

- Python 新增 `GatewayWebSocket`，可选依赖 `websocket-client`，二进制 V2 22 字节大端请求头 + GZIP，支持旧式回复解码、公开行情匿名 CONNECT、订阅、退订、心跳和手动 close。
- **正式域名实测**：`wss://trade.opentradingcore.com/gateway` HTTP 101 Switching Protocols，PUBLIC_MARKET CONNECT 返回 `code=0`，深度 Topic 订阅确认 `Code=0000`，Heartbeat `cmd=2` 收到对应回复。
- 部分 Demo 产品没有持续行情 ticks；不能把收到订阅 ACK 当作已验证实时盘口数据或增量追平。私有 Trader token WebSocket 会话、订单成交回报、断线重连与快照 diff 缺口真实测试仍未完成。
- 更新 Python 示例：`demo_trader_api.py`、`demo_broker_api.py`、`demo_public_websocket.py`，写操作需显式传参。SDK **32/32 单测通过**、OpenAPI **17** 方法结构检查通过，自动文档导航包含 **16** 个对外功能接口；英文/中文单页均严格构建通过。
- 外网 0.1.4 Wheel / ZIP 下载均返回 `200`，大小分别为 19858 / 25068 字节。本地 0.1.4 实例 `healthy`。此前 0.1.3 ZIP 的 Cloudflare HIT 缓存返回旧版，已通过新版本号避免覆盖缓存文件。

## 关键阻碍：Cloudflare HTTP 1010

- 同一 Demo Mac：本地 Gateway `http://127.0.0.1:18088/httpapi/` 匿名 `AdminSvr/querySymbol` 返回 HTTP 200、业务 `code=0`。
- 外部 Python `POST https://trade.opentradingcore.com/httpapi/` 和 `/api` 返回 Cloudflare HTTP **403 / `error code: 1010`**（`Server: cloudflare`），请求被边缘拒绝，未进入 Gateway；主页 GET 和公开 WSS 仍可能成功。这是已观测到的**当前客户端访问受阻**，不能据此断言所有外部 IP 或浏览器都会失败。
- 域名管理员需要在 Cloudflare **Security Events** 追踪该请求，并对 `/api` 和 `/httpapi/*` 的正常 API 客户端配置适当 WAF 规则或豁免；不能关闭后端 HMAC、租户检查或 API 权限，也不建议通过变更 User-Agent 绕过规则。
- 外部 SDK Trader/Broker 完整 HTTP 写入流程发布前必须确认 Cloudflare 对开发者 Python 客户端放行。

## 合并及下一阶段门槛

1. 先处理 Cloudflare API 路径的合法客户端 HTTP 可达性，保持 Gateway 鉴权。
2. 在 Demo 独立测试租户中完成 **两 Trader SDK Keys → 模拟资金准备 → limit 成交 → 私有历史查询 → 撤单 → ReduceOnly 平仓 / 余额和 PnL 对账**，全部真实接受；避免重试结果不明的订单。
3. 使用普通 Broker 交易 Key 完成代客同租户授权交易及跨租户拒绝；如产品决定要 Broker Key 开户/模拟入金，须单独审查接口权限设计，而非隐式扩大公开 Key 权限。
4. 实测私有 WSS 推送、断线重新登录/订阅、深度快照 + diff gap；此轮不触碰另一会话的 Common/Trade HA 测试。
