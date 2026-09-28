# DC Broker API Reference v1

> 面向自建 Broker / 经纪商后台的正式接口级参考。  
> 本文只描述当前已经存在或已经进入真实 E2E 的能力，不虚构 REST-friendly URL。  
> 当前传输继续使用 GW Native HTTP / TCP / WebSocket contract。

---

# 1. Broker Identity Model

Broker API Key：

```text
api_key_type = broker
client_type  = TenantAPI
```

当前默认权限域：

```text
MARKET_READ
ACCOUNT_READ
ORDER_READ
ORDER_WRITE
TENANT_READ
TENANT_WRITE
CUSTOMER_CASH
```

Broker API 的核心模型：

```text
Broker API Key = actor
Customer       = owner
location       = tenant isolation boundary
```

所有 customer 操作必须满足：

```text
broker.location == customer.location
customer.user_type == TRADER
customer.enable == 1
```

交易写操作还要求：

```text
customer.enable_trade == 1
```

跨 location customer 必须拒绝。

---

# 2. Authentication

Broker 使用和 Trader 相同的 signed API Key login：

```http
POST /api
apikey: <BROKER_API_KEY>
expiry: <EPOCH_MS>
signature: <HMAC_SHA256>
```

请求：

```json
{
  "serverName": "LoginSvr",
  "method": "apiKeyLogin",
  "content": {
    "api_key": "BROKER_API_KEY",
    "location": "ABC123",
    "cid": "broker-auth-001"
  }
}
```

典型成功响应：

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {
    "client_type": "TenantAPI",
    "user_id": "broker-actor-user",
    "location": "ABC123",
    "token": "opaque-session-token",
    "sid": "opaque-session-token",
    "api_key_type": "broker",
    "permissions": "MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE,TENANT_READ,TENANT_WRITE,CUSTOMER_CASH",
    "rate_limit_profile": "TRADER_STANDARD"
  }
}
```

当前 Broker 使用：

```text
TRADER_STANDARD
100 req/s
burst 30
```

限流以 LoginSvr 返回的 `rate_limit_profile` 为权威，不是单纯根据 `client_type` 判断。

---

# 3. Create Customer

创建 Broker 名下交易客户。

## Permission

`TENANT_WRITE`

## Server / Method

```text
serverName = AdminSvr
method     = tenantUserAdmin
action     = CREATE
```

## Rate Limit

```text
Weight: 1
Scope: session
Current profile: TRADER_STANDARD for broker key
```

## Request

```json
{
  "serverName": "AdminSvr",
  "method": "tenantUserAdmin",
  "content": {
    "action": "CREATE",
    "username": "client001",
    "password": "strong-initial-password",
    "name": "Client 001",
    "email": "client001@example.invalid",
    "request_id": "create-customer-000001"
  }
}
```

## Request Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| action | enum | Yes | `CREATE` |
| username | string | Yes | 客户登录名 |
| password | string | Yes | 初始密码 |
| name | string | No | 客户显示名称 |
| email | string | No | 客户邮箱 |
| request_id | string | Recommended | 幂等 / 审计请求标识 |

服务端负责绑定当前 Broker 的 authoritative `location`。

Broker 不应自行指定其它租户 location。

## Result

服务端创建内部 customer / user identity，并初始化对应交易账户能力。

Broker 应保存：

```text
Broker external customer identity
    <->
DC customerId / user_id
```

如果未来增加正式 `externalCustomerId` 字段，应作为稳定幂等键进入 OpenAPI schema；当前不能把它写成已经锁定的字段。

---

# 4. List / Manage Customers

## Permission

`TENANT_READ` / `TENANT_WRITE`

当前管理入口：

```text
AdminSvr / tenantUserAdmin
```

当前 action 包括：

```text
LIST
CREATE
ENABLE
DISABLE
RESET_PASSWORD
```

示例：

```json
{
  "serverName": "AdminSvr",
  "method": "tenantUserAdmin",
  "content": {
    "action": "LIST",
    "page_num": 0,
    "page_size": 50
  }
}
```

所有结果必须限定在 Broker 当前 location。

---

# 5. Deposit for Customer

给 Broker 名下客户入金。

## Permission

`CUSTOMER_CASH`

## Server / Method

```text
serverName = TradeSvr
method     = cashIn
```

## Rate Limit

```text
Weight: 1
Scope: session
```

## Current Runtime Request

当前真实 Broker E2E 使用 TradeSvr `CashRequest`：

```json
{
  "serverName": "TradeSvr",
  "method": "cashIn",
  "content": {
    "Location": "ABC123",
    "UserID": "customer-user-id",
    "AccountID": "customer-user-id",
    "Currency": "USDT",
    "Amount": "10000",
    "Info1": "DEP-20260928-000001"
  }
}
```

## Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| Location | string | Yes | customer location；必须等于 Broker location |
| UserID | string | Yes | customer user ID |
| AccountID | string | Yes | 当前交易账户 ID |
| Currency | string | Yes | 例如 `USDT` |
| Amount | decimal string | Yes | 入金金额 |
| Info1 | string | Strongly recommended | 外部资金流水 / 幂等引用 |

### External Reference

`Info1` 当前承载 Broker 外部资金引用。

建议 Broker 使用全局唯一值，例如：

```text
DEP-<broker>-<customer>-<timestamp>-<sequence>
```

正式 GA 前应把它在外部文档中统一命名为更友好的 `externalRef`，但 façade 只做字段映射，不能改变资金幂等语义。

### Internal Field Warning

当前内部 E2E 的 `CashRequest` 还会设置内部 `Demo` 标志。

**正式外部 Broker API 不应让客户自行控制 Demo/Internal 字段。**

GA 前应该由服务端 / SDK / façade 固定处理该内部字段。

---

# 6. Withdraw for Customer

给 Broker 名下客户出金。

## Permission

`CUSTOMER_CASH`

## Server / Method

```text
serverName = TradeSvr
method     = cashOut
```

## Request

```json
{
  "serverName": "TradeSvr",
  "method": "cashOut",
  "content": {
    "Location": "ABC123",
    "UserID": "customer-user-id",
    "AccountID": "customer-user-id",
    "Currency": "USDT",
    "Amount": "1000",
    "Info1": "WD-20260928-000001"
  }
}
```

服务端必须验证：

- Broker 拥有 `CUSTOMER_CASH`
- customer 属于 Broker location
- customer account 存在
- 余额 / 可用资金足够
- external reference / request identity 满足幂等要求

常见错误：

| Code | Msg |
|---:|---|
| 5000 | TRADE_BALANCE_NOT_ENOUGH |
| 5001 | TRADE_ACCOUNTBALANCE_NOTEXIST |
| 9004 | PARAMETER_ERROR |
| 9016 | TRADE_PERMISSION_DENIED |
| 10003 | RATE_LIMIT_EXCEEDED |
| 9000 | INTERNAL_ERROR |

---

# 7. Place Order for Customer

Broker 代客户下单继续复用统一：

```text
OrderSvr / placeOrder
```

不创建第二套撮合协议。

## Permission

`ORDER_WRITE`

## Request

```json
{
  "serverName": "OrderSvr",
  "method": "placeOrder",
  "content": {
    "Location": "ABC123",
    "UserID": "customer-user-id",
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "Side": "BUY",
    "OCType": "OPEN",
    "OrdType": "Limit",
    "TimeInForce": "GTC",
    "OrderQty": "0.010",
    "Price": "60000.0",
    "ClOrdID": "broker-customer-order-000001"
  }
}
```

Broker 模式与 Trader 模式的核心区别：

```text
Trader:
Session user == order owner

Broker:
Session user == actor
content UserID == customer owner
```

服务端不能因为 body 中出现 `UserID` 就直接信任。

必须验证：

```text
customer.location == broker.location
customer is enabled
customer trading is enabled
broker has ORDER_WRITE
```

当前真实 E2E 的 Broker 客户订单会被标记为 authoritative customer order，而不是 Robot internal/demo order。

---

# 8. Cancel Customer Order

## Permission

`ORDER_WRITE`

## Server / Method

```text
serverName = OrderSvr
method     = cancelOrder
```

## Request

```json
{
  "serverName": "OrderSvr",
  "method": "cancelOrder",
  "content": {
    "Location": "ABC123",
    "UserID": "customer-user-id",
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "OrderID": "server-order-id",
    "ClOrdID": "broker-cancel-000001"
  }
}
```

Broker 只能撤销自己 location 内 customer 的订单。

---

# 9. Query Customer Open Orders

## Permission

`ORDER_READ`

## Server / Method

```text
serverName = OrderSvr
method     = queryOpenOrder
```

## Request

当前真实 E2E 使用兼容字段：

```json
{
  "serverName": "OrderSvr",
  "method": "queryOpenOrder",
  "content": {
    "userid": "customer-user-id",
    "Location": "ABC123",
    "securityid": "BTCUSDT",
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4"
  }
}
```

这里同时出现 legacy lowercase alias 和 canonical field，是当前运行时兼容性事实。

**外部 GA 前应由 SDK / façade 统一成一套规范字段，避免客户手工发送重复 alias。**

---

# 10. Query Customer Balance

## Permission

`ACCOUNT_READ`

## Server / Method

```text
serverName = TradeSvr
method     = queryAccountBalance
```

## Request

```json
{
  "serverName": "TradeSvr",
  "method": "queryAccountBalance",
  "content": {
    "userid": "customer-user-id",
    "location": "ABC123"
  }
}
```

Broker 的 Session actor 不等于 customer，因此这里必须显式携带目标 customer。

服务端必须检查 customer scope。

---

# 11. Query Customer Position

## Permission

`ACCOUNT_READ`

## Server / Method

```text
serverName = TradeSvr
method     = queryTradePosition
```

## Request

```json
{
  "serverName": "TradeSvr",
  "method": "queryTradePosition",
  "content": {
    "userid": "customer-user-id",
    "location": "ABC123",
    "securityid": "BTCUSDT"
  }
}
```

---

# 12. Customer Order History

## Permission

`ORDER_READ`

## Server / Method

```text
serverName = ProjectionSvr
method     = queryProjectedOrderHistory
```

## Request

```json
{
  "serverName": "ProjectionSvr",
  "method": "queryProjectedOrderHistory",
  "content": {
    "location": "ABC123",
    "userId": "customer-user-id",
    "securityId": "BTCUSDT",
    "limit": 200
  }
}
```

---

# 13. Customer Execution History

## Permission

`ORDER_READ`

## Server / Method

```text
serverName = ProjectionSvr
method     = queryProjectedExecutionHistory
```

请求结构与 Customer Order History 相同。

---

# 14. Customer Execution Stream

当前真实 Broker E2E 已验证 customer execution private stream：

```text
dc.order.trade.<SecurityID>.*.<CustomerUserID>.<Location>
```

例如：

```text
dc.order.trade.BTCUSDT.*.customer-user-id.ABC123
```

Broker 只能订阅：

```text
Broker location 内
自己有权限管理的 customer
```

跨 location customer subscription 必须拒绝。

---

# 15. Reconnect Rules

当前 Broker E2E 已验证强制断线后重新通过 signed API Key 恢复。

推荐行为：

```text
disconnect
  -> signed apiKeyLogin
  -> new session
  -> reconnect TCP/WebSocket
  -> resubscribe customer streams
  -> query balance
  -> query position
  -> query open orders
  -> rebuild local state
```

对于写操作：

> 如果连接在写请求结果返回前断开，客户端不能盲目重放。

应依靠：

- `ClOrdID`
- external cash reference
- query order
- query history

确认结果后再决定下一步。

---

# 16. Isolation Guarantee

Broker API 必须满足：

```text
Broker A cannot access Broker B customer
```

当前 Broker E2E 已真实验证：

- 本 tenant maker customer
- 本 tenant taker customer
- foreign tenant customer
- foreign customer balance query 被拒绝

这项应继续作为 Broker API release gate。

---

# 17. Current Rate Limit

当前 Broker Key：

```text
client_type        = TenantAPI
api_key_type       = broker
rate_limit_profile = TRADER_STANDARD
```

因此当前默认：

```text
100 req/s
burst 30
Token Bucket
scope = sessionId
weight = 1 per request
```

当前还没有：

- `BROKER_STANDARD`
- per-method weight
- per-customer sub-bucket
- per-Broker-location secondary bucket

正式增加这些能力前需要真实 Broker 并发压测。

---

# 18. Current E2E Coverage

当前生产验收链已经覆盖：

1. signed Broker login
2. customer public market
3. 两个 customer deposit
4. customer balance
5. Broker 为 customer A 下 maker order
6. Broker 为 customer B 下 IOC taker order
7. customer execution streams
8. customer positions
9. execution history
10. order history
11. place + cancel customer order
12. customer withdrawal
13. foreign tenant customer rejection
14. forced disconnect + reconnect
15. DB posting / execution persistence verification

部署侧入口：

`tests/run-broker-api-e2e-host.sh`

---

# 19. Public GA Cleanup Before External Release

当前 Broker contract 已经真实可跑，但对外 GA 前建议继续做协议清理：

1. 把 legacy `userid/securityid` 与 canonical `UserID/SecurityID` 统一到外部 schema；
2. 隐藏 `Demo/Isdemo/Terminal/AlgoName` 等内部字段；
3. 把 `Info1` 对外映射成明确的 `externalRef`；
4. 增加正式 customer create response schema；
5. 明确 cashIn/cashOut 幂等规则；
6. 把 Broker customer scope 写进 OpenAPI machine schema；
7. 生成 Java/Python SDK；
8. 再决定是否增加 REST-friendly façade。

这些清理不应改变核心业务语义：

```text
Broker actor
 + customer owner
 + location isolation
 + unified trading contract
```
