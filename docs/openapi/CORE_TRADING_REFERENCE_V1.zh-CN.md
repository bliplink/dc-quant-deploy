# DC Core Trading API Reference v1

> 面向 Trader、Broker 和量化开发者的核心交易接口参考。  
> 当前 v1 继续使用 GW Native HTTP Transport，不虚构尚未实现的 REST-friendly URL。  
> 机器可读规范：`crypto-openapi-v1.yaml`

---

## 1. 通用约定

### Endpoint

Session 业务请求统一使用：

```http
POST /httpapi/
Content-Type: application/json
sessionId: <LOGIN_SESSION>
```

Body 使用统一 GW envelope：

```json
{
  "serverName": "OrderSvr",
  "method": "placeOrder",
  "content": {}
}
```

### Authentication

调用本页接口前，客户端必须先通过 signed API Key login 获取 session。

Trader：

`client_type = API`

Broker：

`client_type = TenantAPI` 且 `api_key_type = broker`

### Common Response

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {},
  "info1": null,
  "info2": null,
  "cid": "optional-client-request-id"
}
```

调用方必须判断：

`code == 0`

不能只根据 HTTP 200 判断业务成功。

### Rate Limit

当前 GW 使用 Token Bucket：

- Trader session：`TRADER_STANDARD = 100 req/s, burst 30`
- TenantAPI session：`TENANT_STANDARD = 20 req/s, burst 10`
- scope：`sessionId`
- 当前每个业务请求统一消耗 `1 token`
- 当前没有 per-method weight

详见：

`docs/api/RATE_LIMITS.zh-CN.md`

超限：

```json
{
  "code": 10003,
  "msg": "RATE_LIMIT_EXCEEDED"
}
```

---

# 2. Place Order

创建订单。

## Permission

`ORDER_WRITE`

## Server / Method

```text
serverName = OrderSvr
method     = placeOrder
```

## Rate Limit

```text
Weight: 1
Scope: session
Profile: current session rate_limit_profile
```

> 当前 Weight=1 是 GW 当前统一规则，不是接口独立权重配置。

## Request

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
    "ClOrdID": "client-order-000001",
    "ReduceOnly": "false"
  }
}
```

## Request Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| SecurityID | string | Yes | 交易品种，例如 `BTCUSDT` |
| MarketIndicator | string | Yes | 当前 Crypto 基线使用 `4` |
| Side | enum | Yes | `BUY` / `SELL` |
| OCType | enum | Yes | `OPEN` / `CLOSE` |
| OrdType | enum | Yes | `Limit` / `Market` |
| TimeInForce | enum | Conditional | `GTC` / `IOC` / `FOK` / `PO` |
| OrderQty | decimal string | Yes | 委托数量 |
| Price | decimal string | Limit order | 限价 |
| ClOrdID | string | Yes | 客户端订单 ID / 幂等键 |
| ReduceOnly | boolean/string | No | 仅减仓 |

金融数值建议全部使用字符串，避免 JSON double 精度问题。

## Identity Rules

Trader：

- 不需要提交 `Location`
- 不需要提交 `UserID`
- 账户身份由 Session 决定
- 请求不能切换到其它用户

Broker：

- 可以在 Broker 权限范围内指定本租户 customer / trading user
- 服务端必须校验 customer 属于当前 Broker location
- body 中的 `UserID` 不能绕过 Session 权限

## Routing

OrderSvr cluster routing 逻辑维度：

```text
location + MarketIndicator + SecurityID
```

SDK 应负责 routing key 构造，外部客户不感知 OrderSvrA/B。

## Success

示例：

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "info1": "server-order-id"
}
```

## Async Semantics

`code=0` 表示请求已经被当前 API 接受。

客户端仍必须继续通过：

- Order status stream
- queryOrder
- queryOpenOrder

获取最终状态。

典型订单状态：

```text
Newing
New
Partially_Filled
Filled
Cancelled
Rejected
```

不要把一次 HTTP success 等同于最终成交。

## Common Errors

| Code | Msg | Meaning |
|---:|---|---|
| 10003 | RATE_LIMIT_EXCEEDED | 当前 session 超限 |
| 9002 | USER_SESSION_NOTEXIST | Session 无效 |
| 9004 | PARAMETER_ERROR | 参数错误 |
| 9016 | TRADE_PERMISSION_DENIED | 无交易权限 |
| 5000 | TRADE_BALANCE_NOT_ENOUGH | 余额不足 |
| 5001 | TRADE_ACCOUNTBALANCE_NOTEXIST | 账户余额不存在 |
| 5003 | MARK_PRICE_NOT_FOUND | 缺少标记价格 |
| 5004 | SYMBOL_NOT_FOUND | 品种不存在 |
| 9000 | INTERNAL_ERROR | 内部错误统一脱敏 |

---

# 3. Cancel Order

撤销单笔订单。

## Permission

`ORDER_WRITE`

## Server / Method

```text
serverName = OrderSvr
method     = cancelOrder
```

## Rate Limit

```text
Weight: 1
Scope: session
```

## Request

```json
{
  "serverName": "OrderSvr",
  "method": "cancelOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "OrderID": "server-order-id",
    "ClOrdID": "cancel-request-000001"
  }
}
```

## Request Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| SecurityID | string | Yes | 品种 |
| MarketIndicator | string | Yes | 市场 |
| OrderID | string | Yes | 服务端订单 ID |
| ClOrdID | string | Yes | 本次撤单请求客户端 ID |

## Success

```json
{
  "code": 0,
  "msg": "NO_ERROR"
}
```

最终订单状态仍以订单事件或查询结果为准。

## Common Errors

| Code | Msg |
|---:|---|
| 8000 | ORDER_NOT_FOUND |
| 9004 | PARAMETER_ERROR |
| 9016 | TRADE_PERMISSION_DENIED |
| 10003 | RATE_LIMIT_EXCEEDED |
| 9000 | INTERNAL_ERROR |

---

# 4. Query Open Orders

查询当前活动订单。

## Permission

`ORDER_READ`

## Server / Method

```text
serverName = OrderSvr
method     = queryOpenOrder
```

## Rate Limit

```text
Weight: 1
Scope: session
```

## Request

```json
{
  "serverName": "OrderSvr",
  "method": "queryOpenOrder",
  "content": {
    "securityid": "BTCUSDT",
    "marketIndicator": "4",
    "maxOrderCount": 100
  }
}
```

## Request Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| securityid | string | No | 品种过滤 |
| marketIndicator | string | No | 市场过滤 |
| maxOrderCount | integer | No | 最大返回数量 |

## Identity Rules

Trader：

只返回当前 Trader 自己的活动订单。

Broker：

只能查询当前 Broker location 内授权 customer 的订单。

## Response

`data` 返回当前活动订单集合，实际字段以 OpenAPI / Order DTO 合同为准。

典型订单字段：

```text
OrderID
ClOrdID
SecurityID
Side
OrdType
TimeInForce
OrderQty
Price
CumQty
LeavesQty
OrdStatus
CreateTime
UpdateTime
```

## Client Guidance

不要通过每 100ms 高频轮询 Open Orders 来追踪订单。

推荐：

1. WebSocket / private order stream 接收实时变化
2. reconnect 后再调用 queryOpenOrder 做 image 重建

## Common Errors

| Code | Msg |
|---:|---|
| 9002 | USER_SESSION_NOTEXIST |
| 9004 | PARAMETER_ERROR |
| 9016 | TRADE_PERMISSION_DENIED |
| 10003 | RATE_LIMIT_EXCEEDED |
| 9000 | INTERNAL_ERROR |

---

# 5. Query Account Balance

查询账户资金。

## Permission

`ACCOUNT_READ`

## Server / Method

```text
serverName = TradeSvr
method     = queryAccountBalance
```

## Rate Limit

```text
Weight: 1
Scope: session
```

## Request

```json
{
  "serverName": "TradeSvr",
  "method": "queryAccountBalance",
  "content": {}
}
```

Trader 不允许通过 body 切换其它账户。

## Response

实际字段以 TradeSvr 当前 DTO 为准。

典型业务字段包括：

```text
currency
balance
available
margin
realizedPnL
unrealizedPnL
```

资金、保证金、PnL 必须以 TradeSvr 返回为权威值。

## Private Stream

账户快照 / 更新 topic：

```text
dc.trade.accountbalance.<UserID>.<Location>
```

Trader 只能订阅自己的 UserID + Location。

## Common Errors

| Code | Msg |
|---:|---|
| 5001 | TRADE_ACCOUNTBALANCE_NOTEXIST |
| 9002 | USER_SESSION_NOTEXIST |
| 9016 | TRADE_PERMISSION_DENIED |
| 10003 | RATE_LIMIT_EXCEEDED |
| 9000 | INTERNAL_ERROR |

---

# 6. Query Position

查询当前持仓。

## Permission

`ACCOUNT_READ`

## Server / Method

```text
serverName = TradeSvr
method     = queryTradePosition
```

## Rate Limit

```text
Weight: 1
Scope: session
```

## Request

```json
{
  "serverName": "TradeSvr",
  "method": "queryTradePosition",
  "content": {
    "securityid": "BTCUSDT"
  }
}
```

## Request Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| securityid | string | No | 指定 symbol；为空时行为以当前 TradeSvr 合同为准 |

## Response

典型持仓字段：

```text
SecurityID
PositionSide
PositionQty
EntryPrice
MarkPrice
Leverage
Margin
UnrealizedPnL
LiquidationPrice
```

具体字段名以当前 TradeSvr DTO / OpenAPI schema 为准。

## Private Stream

```text
dc.trade.position.<UserID>.<Location>
```

资金和持仓的权威来源是 TradeSvr。

客户端可以做展示计算，但不能把本地计算当成最终账户状态。

## Common Errors

| Code | Msg |
|---:|---|
| 10000 | NO_POSITION |
| 5004 | SYMBOL_NOT_FOUND |
| 9002 | USER_SESSION_NOTEXIST |
| 9016 | TRADE_PERMISSION_DENIED |
| 10003 | RATE_LIMIT_EXCEEDED |
| 9000 | INTERNAL_ERROR |

---

# 7. Trader 与 Broker 的差异

以上五个交易接口使用同一套核心业务合同。

Trader：

```text
Session owner == Trading account owner
```

Broker：

```text
Session owner == Broker
Target trading account == authorized customer
```

区别在账户 scope，不在撮合协议。

服务端必须保证：

```text
broker.location == customer.location
customer.user_type == TRADER
customer.enable == 1
customer.enable_trade == 1
```

---

# 8. 推荐客户端调用方式

推荐流程：

```text
Signed API Key Login
      |
      v
Session
      |
      +--> HTTP place/cancel/query
      |
      +--> WebSocket public market
      |
      +--> WebSocket private order/execution/account/position
```

下单：

```text
HTTP placeOrder
  -> code=0
  -> wait order.update
  -> New / Rejected / Filled ...
```

断线恢复：

```text
Reconnect
  -> re-auth
  -> re-subscribe
  -> queryOpenOrder
  -> queryPosition
  -> queryAccountBalance
  -> rebuild local state
```

---

# 9. 下一批 Reference

后续按相同模板继续补：

- API Key Login
- Query Order
- Query Executions
- Cancel Batch
- Set Leverage
- Set Position Mode
- Kline
- Public Market
- Durable Order History
- Durable Execution History
- Broker Create Customer
- Broker Deposit
- Broker Withdrawal
- Broker Place Order for Customer
- WebSocket Public Streams
- WebSocket Private Streams

---

# 10. Source of Truth

本 Reference 是面向开发者的可读文档。

机器可读 contract：

`docs/openapi/crypto-openapi-v1.yaml`

字段级内部/外部映射参考：

`docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md`

API 变更顺序：

```text
implementation
 -> tests
 -> OpenAPI schema/catalog
 -> Markdown reference
 -> generated static developer portal
```

不要只改生成后的 HTML。
