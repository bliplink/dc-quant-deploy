# DC Open API v1 开发者指南（Draft）

> **状态**：Developer Preview  
> **适用分支**：`saas-crypto`  
> **机器可读规范**：`docs/openapi/crypto-openapi-v1.yaml`  
> **适用对象**：普通 Trader、量化用户、Broker、自建交易前端、Tenant 自建系统  
> **原则**：本指南只把已经进入公开 OpenAPI catalog 的 method 写成稳定接口；未进入 YAML 的能力会明确标记为“待公开契约”，不会使用内部方法名冒充公开 API。

---

## 1. 这套 API 适合谁

DC Open API 面向三类开发者。

| 开发者类型 | 典型场景 | 可以代表谁操作 |
| --- | --- | --- |
| Trader | 量化交易、自动交易、自建终端 | 仅自己 |
| Broker | 自建 Broker 后台、App、CRM、客户交易系统 | 自己名下客户 |
| Tenant | 基于 DC 交易核心开发完整 SaaS / Broker 平台 | 当前 tenant/location 范围内的用户 |

三类客户端共用同一套交易核心和订单协议。

差异主要在：

- API Key 类型；
- permission scope；
- `location`；
- 可以操作的用户范围；
- 是否具备 Tenant/Broker 管理权限。

---

# 2. Quick Start

一个最小交易流程通常是：

```text
1. 创建 API Key
2. 对 /api 发起签名 apiKeyLogin
3. 获得 session token
4. 使用 sessionId 调用 /httpapi/
5. 下单后继续查询订单或订阅实时订单事件
```

## 2.1 第一步：准备 API Key

你需要：

```text
api_key
secret_key
location
```

不要：

- 把 `secret_key` 写进前端 JavaScript；
- 提交到 Git；
- 输出到日志；
- 多个系统共用一个高权限 key。

建议为不同用途创建不同 API Key：

```text
read-only
trading
broker-service
tenant-service
```

---

# 3. API Transport

DC Open API v1 不强制把内部服务重新包装成大量 REST URL。

统一通过 GW 的两个 HTTP 入口访问。

## 3.1 Signed API-Key Request

```http
POST /api
```

主要用于：

- API Key 登录；
- 建立 API session。

Headers：

| Header | 必须 | 说明 |
| --- | ---: | --- |
| `apikey` | 是 | API Key |
| `expiry` | 是 | Epoch milliseconds |
| `signature` | 是 | HMAC-SHA256 签名 |
| `cid` | 否 | 客户端请求标识 |

## 3.2 Session Request

```http
POST /httpapi/
```

Headers：

| Header | 必须 | 说明 |
| --- | ---: | --- |
| `sessionId` | 是 | `apiKeyLogin` 返回的 token |

Body 使用统一 GW Envelope：

```json
{
  "serverName": "OrderSvr",
  "method": "queryOpenOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4"
  }
}
```

Envelope：

| Field | 类型 | 必须 | 说明 |
| --- | --- | ---: | --- |
| `serverName` | string | 是 | 稳定服务契约名 |
| `method` | string | 是 | v1 catalog method |
| `content` | object/string | 是 | method-specific request |

公开可用 `serverName`：

```text
LoginSvr
MDSvr
OrderSvr
TradeSvr
ProjectionSvr
AdminSvr
ManagerSvr
```

> 客户端使用的是稳定逻辑服务名，不需要知道 A/B 节点、partition primary 或物理地址。

---

# 4. Authentication

## 4.1 签名算法

DC v1 使用：

```text
HMAC-SHA256
```

待签名明文：

```text
raw_http_body + expiry
```

签名结果：

```text
HEX(HMAC-SHA256(secret_key, UTF8(raw_http_body + expiry)))
```

其中：

- `raw_http_body` 必须和真正发送的 HTTP body 字节完全一致；
- `expiry` 使用 epoch milliseconds；
- 不要在计算签名后重新格式化 JSON。

## 4.2 签名登录请求

Request body：

```json
{
  "serverName": "LoginSvr",
  "method": "apiKeyLogin",
  "content": {
    "api_key": "0123456789abcdef",
    "location": "ABC123",
    "cid": "quant-client-001"
  }
}
```

示意 curl：

```bash
BODY='{"serverName":"LoginSvr","method":"apiKeyLogin","content":{"api_key":"YOUR_API_KEY","location":"ABC123","cid":"quant-client-001"}}'
EXPIRY=1790000000000
SIGNATURE="<HMAC_SHA256_HEX_OF_BODY_PLUS_EXPIRY>"

curl -X POST 'https://YOUR_DC_HOST/api' \
  -H 'Content-Type: application/json' \
  -H 'apikey: YOUR_API_KEY' \
  -H "expiry: $EXPIRY" \
  -H "signature: $SIGNATURE" \
  -H 'cid: quant-client-001' \
  --data "$BODY"
```

> 上面的 host、key、expiry、signature 都是示意值。

## 4.3 Python 签名示例

```python
import hashlib
import hmac
import json
import time

api_key = "YOUR_API_KEY"
secret_key = "YOUR_SECRET_KEY"
location = "ABC123"

body_obj = {
    "serverName": "LoginSvr",
    "method": "apiKeyLogin",
    "content": {
        "api_key": api_key,
        "location": location,
        "cid": "quant-client-001",
    },
}

# 发送什么字符串，就签什么字符串。
raw_body = json.dumps(body_obj, separators=(",", ":"))
expiry = str(int(time.time() * 1000) + 5000)

payload = (raw_body + expiry).encode("utf-8")
signature = hmac.new(
    secret_key.encode("utf-8"),
    payload,
    hashlib.sha256,
).hexdigest()

print("expiry =", expiry)
print("signature =", signature)
print("body =", raw_body)
```

---

# 5. Session

成功的 API Key 登录响应示例：

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {
    "client_type": "API",
    "user_id": "500020",
    "location": "ABC123",
    "token": "opaque-session-token",
    "sid": "opaque-session-token",
    "api_key_type": "trade",
    "permissions": "MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE",
    "rate_limit_profile": "TRADER_STANDARD"
  }
}
```

后续请求：

```http
sessionId: opaque-session-token
```

服务端 session 中保存的以下信息是权威身份：

- `client_type`
- `user_id`
- `location`
- `api_key_type`
- `permissions`
- `rate_limit_profile`

请求 body 不能扩大这些权限。

---

# 6. Permission Scopes

当前 v1 使用明确 scope。

| Scope | 用途 |
| --- | --- |
| `MARKET_READ` | 市场行情 |
| `ACCOUNT_READ` | 账户、持仓、配置读取 |
| `ORDER_READ` | 订单与成交查询 |
| `ORDER_WRITE` | 下单、撤单、交易配置 |
| `TENANT_READ` | Tenant 管理读取 |
| `TENANT_WRITE` | Tenant 管理写入 |

建议：

### 普通量化 Trader

```text
MARKET_READ
ACCOUNT_READ
ORDER_READ
ORDER_WRITE
```

### 只读监控程序

```text
MARKET_READ
ACCOUNT_READ
ORDER_READ
```

### Broker / Tenant Backend

根据产品权限增加：

```text
TENANT_READ
TENANT_WRITE
```

使用最小权限原则。

---

# 7. Common Response

所有 GW HTTP 请求使用统一业务响应：

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {},
  "info1": null,
  "info2": null,
  "cid": "client-request-id"
}
```

| Field | 说明 |
| --- | --- |
| `code` | 业务响应码；0 表示当前请求成功 |
| `msg` | 稳定公开错误消息 |
| `data` | 业务数据 |
| `info1` | 可选扩展信息 |
| `info2` | 可选扩展信息 |
| `cid` | 请求相关标识 |

内部异常、SQL、stack trace、文件路径、集群内部信息不会作为公开 API 契约返回。

---

# 8. Market API

当前公开 catalog：

| Service | Method | Scope |
| --- | --- | --- |
| MDSvr | `queryPublicMarket` | MARKET_READ |
| MDSvr | `queryKLine` | MARKET_READ |

## 8.1 Query Public Market

Envelope：

```json
{
  "serverName": "MDSvr",
  "method": "queryPublicMarket",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4"
  }
}
```

具体 response schema 以 OpenAPI method schema 为准。

## 8.2 Query Kline

```json
{
  "serverName": "MDSvr",
  "method": "queryKLine",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4"
  }
}
```

> 实时 Kline / depth / bookTicker 最终应优先使用 WebSocket，而不是高频轮询 HTTP。

---

# 9. Order API

当前公开 catalog：

| Method | Scope |
| --- | --- |
| `placeOrder` | ORDER_WRITE |
| `cancelOrder` | ORDER_WRITE |
| `cancelBatchOrder` | ORDER_WRITE |
| `queryOrder` | ORDER_READ |
| `queryOpenOrder` | ORDER_READ |
| `queryExecOrder` | ORDER_READ |

---

# 10. Place Order

## 10.1 Request

```json
{
  "serverName": "OrderSvr",
  "method": "placeOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "Side": "BUY",
    "OCType": "OPEN",
    "OrdType": "Limit",
    "TimeInForce": "GTC",
    "OrderQty": "0.010",
    "Price": "60000.0",
    "ClOrdID": "my-order-000001"
  }
}
```

## 10.2 主要字段

| Field | 示例 | 说明 |
| --- | --- | --- |
| `SecurityID` | BTCUSDT | 品种 |
| `MarketIndicator` | 4 | 市场类型 |
| `Side` | BUY | BUY / SELL |
| `OCType` | OPEN | OPEN / CLOSE |
| `OrdType` | Limit | 订单类型 |
| `TimeInForce` | GTC | GTC / IOC / FOK / PO 等支持值 |
| `OrderQty` | 0.010 | 数量 |
| `Price` | 60000.0 | Limit price |
| `ClOrdID` | my-order-000001 | 客户端订单 ID |

## 10.3 ClOrdID

每个调用方都应该生成唯一 `ClOrdID`。

建议：

```text
<system>-<strategy>-<timestamp-or-sequence>
```

例如：

```text
quant01-grid-00000018291
broker7-client83-00009122
```

不要重复使用已经确认受理的 `ClOrdID`。

## 10.4 异步订单语义

交易系统是异步状态机。

应用必须区分：

```text
request accepted
    ->
Newing
    ->
New / Rejected
    ->
PartiallyFilled
    ->
Filled / Cancelled
```

**一次 HTTP 成功响应不能替代最终订单状态确认。**

建议：

- 下单后用 `queryOrder` / `queryOpenOrder` 查询；
- 生产系统优先消费 WebSocket private order event；
- 不要仅依靠 HTTP response 推断“订单已经成交”。

---

# 11. Cancel Order

稳定公开 method：

```text
OrderSvr / cancelOrder
```

典型 Envelope：

```json
{
  "serverName": "OrderSvr",
  "method": "cancelOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "ClOrdID": "my-order-000001"
  }
}
```

实际 required fields 以最终 OpenAPI schema 为准。

---

# 12. Batch Cancel

```text
OrderSvr / cancelBatchOrder
```

适合：

- 策略停止；
- 风控撤单；
- 批量管理多个订单。

调用方必须处理“部分成功 / 部分失败”。

---

# 13. Query Open Orders

```json
{
  "serverName": "OrderSvr",
  "method": "queryOpenOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4"
  }
}
```

Scope：

```text
ORDER_READ
```

只返回当前 session 有权访问的订单。

---

# 14. Query Order / Execution

订单：

```text
OrderSvr / queryOrder
```

成交：

```text
OrderSvr / queryExecOrder
```

历史查询还可以使用 Projection API。

---

# 15. Account API

当前公开 catalog：

| Method | Scope |
| --- | --- |
| `queryAccountBalance` | ACCOUNT_READ |
| `queryTradePosition` | ACCOUNT_READ |
| `getAccountConfig` | ACCOUNT_READ |
| `setLeverage` | ORDER_WRITE |
| `setPositionType` | ORDER_WRITE |

## 15.1 Query Account Balance

```json
{
  "serverName": "TradeSvr",
  "method": "queryAccountBalance",
  "content": {}
}
```

用户身份应由 session 绑定。

## 15.2 Query Position

```json
{
  "serverName": "TradeSvr",
  "method": "queryTradePosition",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4"
  }
}
```

## 15.3 Set Leverage

```text
TradeSvr / setLeverage
```

需要：

```text
ORDER_WRITE
```

## 15.4 Set Position Type

```text
TradeSvr / setPositionType
```

需要：

```text
ORDER_WRITE
```

---

# 16. History API

当前公开 catalog：

| Service | Method | Scope |
| --- | --- | --- |
| ProjectionSvr | `queryProjectedOrderHistory` | ORDER_READ |
| ProjectionSvr | `queryProjectedExecutionHistory` | ORDER_READ |

历史数据不要求客户端知道 OrderSvr / TradeSvr 的实际 primary。

---

# 17. Broker API

## 17.1 Broker 模式

Broker 模式面向自建经纪商系统。

```text
Broker Web/App
    |
Broker Backend
    |
DC Open API
    |
Customer Trading Accounts
```

Broker 需要能够完成：

```text
create customer
create trading account
cash in
cash out
place order for customer
cancel order for customer
query customer balance
query customer position
query customer order
query customer execution
```

## 17.2 Broker 和 Trader 最大区别

Trader：

```text
API Key owner == trading user
```

Broker：

```text
API Key owner == broker/service identity
target trading user == broker-owned customer
```

Broker API 必须同时验证：

```text
broker session
location
customer ownership
permission
target user
```

不能仅相信请求 body 里的 UserID。

## 17.3 当前公开契约状态

目前 `crypto-openapi-v1.yaml` 已公开：

- Tenant user 管理入口；
- Order API；
- Account query；
- History；
- Market。

但以下 Broker GA 能力仍需要在公开 YAML 中冻结稳定 method/schema 后，才能让第三方正式接入：

| 能力 | 当前状态 |
| --- | --- |
| 创建 Broker customer / trading account | 后端能力已验证；公开 schema 需冻结 |
| Customer cashIn | 后端业务链已验证；公开 method/schema 需冻结 |
| Customer cashOut | 后端业务链已验证；公开 method/schema 需冻结 |
| Broker 指定 customer 代客 placeOrder | 产品能力明确；公开 subject schema 需冻结 |
| Broker customer balance/position aggregation | 需要冻结公开查询 schema |

**在这些能力进入 `crypto-openapi-v1.yaml` 前，不建议第三方依赖内部 method 名称。**

---

# 18. Tenant API

当前 AdminSvr catalog：

| Method | Required Permission |
| --- | --- |
| `tenantUserAdmin` | TENANT_READ_OR_WRITE |
| `tenantSymbolAdmin` | TENANT_READ_OR_WRITE |
| `tenantRobotAdmin` | TENANT_READ_OR_WRITE |
| `tenantSettingsAdmin` | TENANT_READ_OR_WRITE |
| `tenantTradeAdmin` | TENANT_READ |
| `tenantUserRegistration` | PUBLIC_POLICY_GATED |

Tenant API 适合：

- 自建 Broker 平台；
- 管理客户；
- 管理 symbol；
- 管理 Robot；
- 管理 Tenant settings；
- 组合交易和账户 API。

Tenant 仍只能访问自己的 `location`。

---

# 19. API Key Management

当前 Authentication catalog：

| Method | 认证方式 |
| --- | --- |
| `apiKeyLogin` | SIGNED_API_KEY |
| `updateApiKey` | INTERACTIVE_SESSION |
| `queryApiKey` | INTERACTIVE_SESSION |
| `deleteApiKey` | INTERACTIVE_SESSION |
| `tenantApiKeyAdmin` | TENANT_ADMIN |

建议：

- 只读 key 和交易 key 分离；
- Broker service key 单独管理；
- 定期轮换；
- 立即禁用泄露 key；
- 不在第三方前端暴露 service secret。

---

# 20. Rate Limits

每个 API session 都绑定：

```text
rate_limit_profile
```

例如：

```text
TRADER_STANDARD
```

限流应考虑：

- API Key；
- user；
- Broker / tenant；
- method；
- 写操作和读操作；
- WebSocket connection。

**当前 v1 OpenAPI YAML 尚未冻结不同 profile 的公开数值。**

因此 Developer Preview 阶段不要在客户端写死未经发布的具体 QPS。

GA 前文档必须补充类似：

| Profile | Trading Write | Order Read | Market Read |
| --- | ---: | ---: | ---: |
| TRADER_STANDARD | TBD | TBD | TBD |
| BROKER_STANDARD | TBD | TBD | TBD |

过载时客户端应：

- 停止无意义重试；
- 使用 exponential backoff；
- 不要在多个连接中绕过同一个 key 的限流。

---

# 21. Error Handling

公开 API 只暴露稳定错误码。

OpenAPI 当前 whitelist 包含：

```text
0
1
1004
1005
1006
1007
1050
5000-5004
7000-7004
8000
9000
9001
9002
9004-9009
9016
9018
9019
10000
10003
10004
10005
```

其中已明确：

| Code | Meaning |
| ---: | --- |
| 0 | Success |
| 9000 | INTERNAL_ERROR（未公开 backend error 会归一化到此类） |

其余 code/message 的正式客户含义应由公共 error catalog 统一发布，不应从内部异常猜测。

客户端处理原则：

```text
code == 0
  -> 当前请求成功

code != 0
  -> 不要只看 HTTP 200
  -> 按 DC business code 处理
```

---

# 22. WebSocket

DC 交易产品的实时能力最终通过 GW WebSocket 统一提供。

目标公开频道包括：

## Public

```text
bookTicker
depth
trade
Kline
```

## Private

```text
order
execution
position
balance/account
```

生产交易应用建议：

```text
HTTP
  -> command / snapshot query

WebSocket
  -> realtime state/event
```

**当前 `crypto-openapi-v1.yaml` 主要定义 HTTP transport，WebSocket topic / subscription schema 需要单独冻结后再进入 GA 文档。**

---

# 23. 推荐的订单客户端模型

不要这样：

```text
HTTP code=0
  -> 认为订单最终成功
```

推荐：

```text
placeOrder
  -> accepted
  -> remember ClOrdID / OrderID
  -> consume private order event
  -> New / Rejected
  -> PartiallyFilled / Filled / Cancelled
```

HTTP query 用于：

- reconnect；
- reconciliation；
- missed-event recovery。

WebSocket 用于：

- 正常实时状态。

---

# 24. Broker Integration Example

目标 Broker 工作流：

```text
1. Broker API Key login
2. Create / locate customer
3. Ensure customer trading account
4. Customer cashIn
5. Broker places order on behalf of customer
6. Consume private order / execution
7. Query position and balance
8. Customer cashOut
```

其中 4 / 5 / 8 的公开 Broker schema 需要在 GA 前补齐进 OpenAPI YAML。

---

# 25. Security Checklist

上线前：

- [ ] Secret 不进入浏览器
- [ ] Secret 不写日志
- [ ] API Key 最小权限
- [ ] expiry 校验
- [ ] signature 使用原始 HTTP body
- [ ] location 由服务端 session 约束
- [ ] Trader 不能操作其它 UserID
- [ ] Broker 只能操作自己的 customer
- [ ] ClOrdID 唯一
- [ ] 对重试做幂等设计
- [ ] WebSocket reconnect 后做状态 reconciliation
- [ ] rate limit 后退避
- [ ] 不把内部 error / stack trace 暴露给客户端

---

# 26. 当前 v1 Method Catalog

## Authentication

```text
LoginSvr/apiKeyLogin
LoginSvr/updateApiKey
LoginSvr/queryApiKey
LoginSvr/deleteApiKey
LoginSvr/tenantApiKeyAdmin
```

## Market

```text
MDSvr/queryPublicMarket
MDSvr/queryKLine
```

## Trading

```text
OrderSvr/placeOrder
OrderSvr/cancelOrder
OrderSvr/cancelBatchOrder
OrderSvr/queryOrder
OrderSvr/queryOpenOrder
OrderSvr/queryExecOrder
```

## Account

```text
TradeSvr/queryAccountBalance
TradeSvr/queryTradePosition
TradeSvr/getAccountConfig
TradeSvr/setLeverage
TradeSvr/setPositionType
```

## History

```text
ProjectionSvr/queryProjectedOrderHistory
ProjectionSvr/queryProjectedExecutionHistory
```

## Tenant

```text
AdminSvr/tenantUserAdmin
AdminSvr/tenantSymbolAdmin
AdminSvr/tenantRobotAdmin
AdminSvr/tenantSettingsAdmin
AdminSvr/tenantTradeAdmin
AdminSvr/tenantUserRegistration
```

---

# 27. 在正式 GA 前还要补齐什么

这份样稿已经可以作为开发者文档首页，但要达到 Binance / Bybit 级别的可用性，还需要继续完成：

1. 为每个 method 增加**独立参数表**；
2. 为每个 method 增加完整 response schema；
3. 冻结所有枚举：
   - Side
   - OrdType
   - TimeInForce
   - OCType
   - OrderStatus
   - ExecType
4. 冻结公开 error code dictionary；
5. 发布 rate limit 数值；
6. 冻结 Broker customer / cashIn / cashOut / delegated trading schema；
7. 发布 WebSocket subscription protocol；
8. 提供 Python / Java / JavaScript 示例；
9. 提供 Postman collection；
10. 由 OpenAPI 自动生成静态 Developer Portal；
11. 提供 Testnet / Demo endpoint；
12. 将 API 文档入口加入 Tenant Web / Trade Web。

---

# 28. 文档设计原则

DC API 文档的目标不是复制 Binance 或 Bybit 的 URL。

我们借鉴成熟交易所开发者文档的体验：

```text
Quick Start
Authentication
Permissions
Rate Limits
Errors
Market
Trade
Account
History
WebSocket
Broker
Examples
```

但保留 DC 自己的架构优势：

```text
统一 GW
统一 Envelope
统一 Session Identity
统一 Trading Core
Broker / Trader / Tenant 共用协议
location 隔离
HTTP + WebSocket
```

最终目标：

> 一个第三方开发者只看公开文档，不需要理解 DC 内部微服务拓扑，就可以完成认证、行情、下单、撤单、订单状态同步、持仓资金查询，以及 Broker 代客交易集成。
