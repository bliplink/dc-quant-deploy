# DC Crypto Open API v1 调用参考

当前基线：2026-09-19。本文只描述已经存在或已经进入当前开发基线的 GW/服务接口，不虚构 Binance 风格 URL。

## 1. 通用请求模型

### 1.1 Signed API Key HTTP

```http
POST /api
Content-Type: application/json
cid: client-request-id
apikey: <API_KEY>
expiry: <epoch-ms>
signature: <HEX_HMAC_SHA256>
```

```json
{
  "serverName": "LoginSvr",
  "method": "apiKeyLogin",
  "content": {}
}
```

签名原文严格为：

```text
rawBody + expiry
```

签名算法：

```text
HEX(HMAC-SHA256(secretKey, UTF8(rawBody + expiry)))
```

推荐 `expiry = now + 60000ms`。

### 1.2 Session HTTP

```http
POST /httpapi/
Content-Type: application/json
sessionId: <LOGIN_SESSION>
```

Body 仍然是同一 GW envelope：

```json
{
  "serverName": "OrderSvr",
  "method": "queryOpenOrder",
  "content": {}
}
```

### 1.3 通用响应

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {},
  "cid": "optional-client-request-id",
  "info1": "optional",
  "info2": "optional"
}
```

调用方必须先判断 `code == 0`，不能只按 HTTP 200 判断业务成功。

## 2. API Key 登录

### Request

```json
{
  "serverName": "LoginSvr",
  "method": "apiKeyLogin",
  "content": {
    "api_key": "xxxxxxxx",
    "location": "TENANT_A",
    "cid": "auth-001"
  }
}
```

GW 在签名校验后注入 key 对应用户身份；LoginSvr 再从自己的 API Key registry 解析 authoritative `user_id + location + key type`。

### Trader key success

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {
    "client_type": "API",
    "user_id": "u-001",
    "location": "TENANT_A",
    "token": "<SESSION>",
    "sid": "<SESSION>"
  }
}
```

### Tenant Service key success

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {
    "client_type": "TenantAPI",
    "user_id": "tenant-admin-user",
    "location": "TENANT_A",
    "token": "<SESSION>",
    "sid": "<SESSION>"
  }
}
```

安全边界：

- `API` 会话可进入 Trader 订单/账户 API；
- `TenantAPI` 会话被 OrderSvr/TradeSvr 拒绝；
- Tenant 管理仍由 AdminSvr 检查实际 TENANT_ADMIN 角色；
- caller body 中的 location/userId 不能覆盖 Session 身份。

## 3. Trader API Key 管理

### 创建 Trader key

交互式登录用户调用：

```json
{
  "serverName": "LoginSvr",
  "method": "updateApiKey",
  "content": {
    "label": "my-robot",
    "ip_whitelist": "[\"203.0.113.10\"]",
    "expires_at": "2027-01-01T00:00:00Z",
    "cid": "key-create-001"
  }
}
```

服务端强制：

```text
type=trade
permissions=MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE
rate_limit_profile=TRADER_STANDARD
```

客户端不能通过该接口把 Trader key 升级成 Tenant key。

### 查询

```json
{
  "serverName": "LoginSvr",
  "method": "queryApiKey",
  "content": {
    "cid": "key-list-001"
  }
}
```

查询结果不返回 `secret_key`。

## 4. Tenant Service API Key

TenantAdmin Session 调用：

```json
{
  "serverName": "LoginSvr",
  "method": "tenantApiKeyAdmin",
  "content": {
    "action": "CREATE",
    "label": "tenant-backoffice",
    "cid": "tenant-key-001"
  }
}
```

服务端强制：

```text
type=tenant
permissions=MARKET_READ,TENANT_READ,TENANT_WRITE
rate_limit_profile=TENANT_STANDARD
```

支持：

```text
LIST
CREATE
DELETE
```

Tenant Service key 不允许调用 OrderSvr/TradeSvr Trader API。

## 5. 行情 API

### 5.1 Public market snapshot

```json
{
  "serverName": "MDSvr",
  "method": "queryPublicMarket",
  "content": {
    "location": "TENANT_A",
    "securityID": "BTCUSDT"
  }
}
```

返回聚合：

- orderBook；
- ticker；
- recentTrades。

当前 Crypto 基线默认 `marketIndicator=4`。现有 `queryPublicMarket` DTO 当前按 `location + securityID` 查询；未来同一 symbol 跨多个 marketIndicator 时需要升级为显式市场维度。

### 5.2 Kline

```json
{
  "serverName": "MDSvr",
  "method": "queryKLine",
  "content": {
    "location": "TENANT_A",
    "securityID": "BTCUSDT",
    "start": "",
    "end": "",
    "text": "1m",
    "num": 500
  }
}
```

### 5.3 Market WebSocket/topic

当前稳定候选：

```text
dc.md.orderbook.<SecurityID>.<Location>
dc.md.trade.<SecurityID>.<Location>
```

MDSvr 对用户 Session 校验 topic 必须以当前 Session location 结尾。

当前 topic 尚未编码 `marketIndicator`；在开放多个同名跨市场品种前必须升级 topic namespace，并保留旧 topic 兼容期。

## 6. 下单

```json
{
  "serverName": "OrderSvr",
  "method": "placeOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "Side": "Buy",
    "OCType": "OPEN",
    "OrdType": "Limit",
    "TimeInForce": "GTC",
    "OrderQty": "0.010",
    "Price": "60000.0",
    "ClOrdID": "robot-000001",
    "ReduceOnly": "false"
  }
}
```

说明：

- 金融数值使用字符串；
- `ClOrdID` 是客户端幂等/追踪主键；
- `Location/UserID/UserName` 不需要由外部客户端提供，SessionOrderAuthority 会写入 authoritative identity；
- OrderSvr cluster routing 使用 `location + MarketIndicator + SecurityID`。

现有 `NewOrderSingle` 还支持未来多资产需要的 `SecurityType/SettlType/ClearingMethod/DeliveryType/Yield/Party/CounterParty` 等字段，但 Crypto v1 不把这些列为必填。

## 7. 撤单

### 单笔

```json
{
  "serverName": "OrderSvr",
  "method": "cancelOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "OrderID": "server-order-id",
    "ClOrdID": "cancel-request-001"
  }
}
```

### 批量

```json
{
  "serverName": "OrderSvr",
  "method": "cancelBatchOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "OrderIDs": [
      "order-1",
      "order-2"
    ]
  }
}
```

当前内部批量撤单一次建议不超过 RobotSvr 已验证的 50 条分片大小。

## 8. 订单/成交查询

### 当前订单

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

### 订单

```json
{
  "serverName": "OrderSvr",
  "method": "queryOrder",
  "content": {
    "securityid": "BTCUSDT",
    "marketIndicator": "4",
    "orderId": "optional",
    "maxOrderCount": 100
  }
}
```

### 当前服务成交

```json
{
  "serverName": "OrderSvr",
  "method": "queryExecOrder",
  "content": {
    "securityid": "BTCUSDT",
    "marketIndicator": "4",
    "maxOrderCount": 100
  }
}
```

### Durable history

```json
{
  "serverName": "ProjectionSvr",
  "method": "queryProjectedOrderHistory",
  "content": {
    "location": "TENANT_A",
    "userId": "u-001",
    "securityId": "BTCUSDT",
    "limit": 100
  }
}
```

```text
queryProjectedExecutionHistory
```

使用同类查询结构。

**在对第三方正式开放 Projection 查询前，需要完成 Session authoritative identity 绑定，避免直接信任 content 中的 userId/location。**

## 9. 账户与持仓

当前 TradeSvr 主要以 snapshot topic 提供权威状态：

```text
dc.trade.accountbalance.<UserID>.<Location>
dc.trade.position.<UserID>.<Location>
```

对用户 Session：

- topic user/location 必须与 Session 一致；
- wildcard identity 被拒绝；
- TenantAPI 会话被拒绝。

### Leverage

```json
{
  "serverName": "TradeSvr",
  "method": "setLeverage",
  "content": {
    "securityID": "BTCUSDT",
    "leverage": 10
  }
}
```

### Position mode

```json
{
  "serverName": "TradeSvr",
  "method": "setPositionType",
  "content": {
    "securityID": "BTCUSDT",
    "positionType": "Cross"
  }
}
```

资金、保证金、PnL、强平价和持仓状态必须以 TradeSvr 返回值为准，API 客户端不自行作为权威计算源。

## 10. Execution private stream

当前 RobotSvr 已验证订阅格式：

```text
dc.order.trade.<SecurityID>.*.<UserID>.<Location>
```

API 客户端使用自己的 authoritative user/location，不允许订阅其他租户或其他用户的私有执行流。

## 11. Tenant API — AdminSvr

### 用户 LIST

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

### 用户 CREATE

```json
{
  "serverName": "AdminSvr",
  "method": "tenantUserAdmin",
  "content": {
    "action": "CREATE",
    "username": "trader01",
    "password": "********",
    "name": "Trader 01",
    "email": "trader01@example.invalid",
    "request_id": "create-user-001"
  }
}
```

其他 action：

```text
ENABLE
DISABLE
RESET_PASSWORD
```

### 品种

```text
serverName=AdminSvr
method=tenantSymbolAdmin
actions=LIST / ENABLE / DISABLE
```

租户只能启停平台已经批准的品种；tick/qty/risk/fee 等平台规则不是租户自由修改接口。

### Robot

```text
serverName=AdminSvr
method=tenantRobotAdmin
actions=LIST / UPSERT / ENABLE / DISABLE
```

当前可配置字段包括：

- robot_id/robot_name；
- security_id；
- api_user_id/api_key；
- quote_source；
- bid_levels/ask_levels；
- spread/step/order_qty/max_position；
- refresh/stale/deviation/circuit breaker；
- hedge 参数；
- strategy_config。

### Settings / Audit

```text
tenantSettingsAdmin:
GET
UPDATE
AUDIT
```

### Tenant trade query

```text
tenantTradeAdmin:
ORDERS
EXECUTIONS
POSITIONS
BALANCES
POSTINGS
LIQUIDATIONS
ADL_EVENTS
ADL_LEDGER
```

具体 action 以 AdminSvr 当前 handler/service 支持集为准；对外 v1 GA 前会把每个 action 的 request/response schema 再锁成机器可校验契约。

## 12. 当前必须继续补齐的 GA 门槛

已经完成/在当前基线：

- API Key location 绑定；
- Trader/Tenant key 类型分离；
- API Key expiry；
- Trader 自助 key 不能提权成 Tenant key；
- Tenant Service key 必须 TENANT_ADMIN 创建；
- TenantAPI Session 不能访问 OrderSvr/TradeSvr；
- Order/Trade/MDSvr Session tenant identity 校验；
- GW HTTP + TCP/WebSocket 真实链路已有 RobotSvr 运行验证；
- 共享 `DcOpenApi.VERSION=v1` 服务/方法/scope 常量。

在“对外 GA”前仍要完成：

1. `permissions` 的细粒度 `READ/WRITE` 下游强制执行，而不是只靠 key class；
2. `ip_whitelist` 在 API 登录/入口强制执行；
3. `rate_limit_profile` 与 GW 通用限流联动；
4. `last_used_time` 更新；
5. ProjectionSvr 历史查询 Session authoritative identity；
6. API 错误码公开白名单，禁止泄露内部异常；
7. WebSocket 全 topic reference、image/increment、sequence/gap/reconnect 规范；
8. Java/Python SDK；
9. API E2E：API Key -> HTTP login -> TCP/WebSocket -> 下单 -> 成交 -> balance/position -> reconnect；
10. 现有 `marketIndicator=4` 的 topic 兼容方案，为后续同 symbol 多市场做准备。

这些项完成后，才把 Crypto Open API v1 标记为 External GA。
