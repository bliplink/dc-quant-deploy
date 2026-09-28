# Broker API 接入指南

> 面向自建 Broker / 经纪商后台。  
> 机器可读规范：`docs/openapi/crypto-openapi-v1.yaml`

## 1. Broker API 是什么

Broker 可以不使用本平台的 Tenant Web / Trade Web，而是自己开发：

- 网站；
- App；
- CRM；
- 客户中心；
- 交易前端；
- 自动化交易系统。

Broker 后端通过 DC Open API 接入交易核心，并代表自己名下客户执行账户和交易操作。

## 2. 典型架构

```text
Broker App / Backend
  -> DC GW Open API
  -> customer/account scope validation
  -> Order / Trade / Market core
```

Broker 与其它 Broker 通过 `location` 隔离。

## 3. 认证

Open API v1 使用：

- `apikey`
- `secret_key`
- `expiry`
- HMAC-SHA256
- session token

签名：

```text
signature = HEX(
  HMAC-SHA256(
    secret_key,
    UTF8(raw_http_body + expiry)
  )
)
```

签名请求入口：

`POST /api`

典型登录 envelope：

```json
{
  "serverName": "LoginSvr",
  "method": "apiKeyLogin",
  "content": {
    "api_key": "YOUR_API_KEY",
    "location": "YOUR_LOCATION",
    "cid": "broker-backend-001"
  }
}
```

成功后获得 session token，后续通过：

`POST /httpapi/`

并在 header 带：

`sessionId: <token>`

## 4. Broker 权限模型

Broker session 必须绑定：

- Broker 自己的 location；
- API key type；
- permissions；
- rate limit profile。

Broker 可以操作自己名下 customer / trading user，但不能跨 location。

请求 body 中自带的 UserID 不能绕过后端授权。

## 5. 客户生命周期

当前 v1 catalog 中管理入口包括：

- `AdminSvr / tenantUserAdmin`
- `AdminSvr / tenantUserRegistration`

Broker / Tenant 管理能力应覆盖：

- 创建客户；
- 创建 trading user；
- 查询客户；
- 管理账户状态；
- 管理 API Key。

具体字段以 OpenAPI 与对应方法 schema 为准。

## 6. 客户资金

Broker 需要能够为自己名下客户执行：

- cashIn；
- cashOut；
- queryAccountBalance；
- 查询资金流水。

所有资金操作必须验证：

- location；
- customer ownership；
- permission；
- idempotency / request identity。

## 7. 代客户下单

Broker 可以代理客户下单。

交易入口仍使用统一 OrderSvr 指令，不为 Broker 复制一套撮合协议。

当前 v1 trading catalog：

- `OrderSvr/placeOrder`
- `OrderSvr/cancelOrder`
- `OrderSvr/cancelBatchOrder`
- `OrderSvr/queryOrder`
- `OrderSvr/queryOpenOrder`
- `OrderSvr/queryExecOrder`

示例：

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
    "ClOrdID": "broker-customer-000001"
  }
}
```

Broker 模式下，后端必须根据 session 和 customer scope 绑定真实交易用户，不能相信客户端随意指定的用户身份。

## 8. 客户持仓与账户

当前 account catalog：

- `TradeSvr/queryAccountBalance`
- `TradeSvr/queryTradePosition`
- `TradeSvr/getAccountConfig`
- `TradeSvr/setLeverage`
- `TradeSvr/setPositionType`

Broker 只能查询自己管理的客户。

## 9. 历史

当前 history catalog：

- `ProjectionSvr/queryProjectedOrderHistory`
- `ProjectionSvr/queryProjectedExecutionHistory`

历史查询不应该直接读取核心服务物理节点。

## 10. 行情

Market catalog：

- `MDSvr/queryPublicMarket`
- `MDSvr/queryKLine`

实时行情最终需要配套 WebSocket 文档：

- bookTicker；
- depth；
- trade；
- Kline。

## 11. 权限建议

典型 Broker key 可能需要：

- MARKET_READ
- ACCOUNT_READ
- ORDER_READ
- ORDER_WRITE
- TENANT_READ
- TENANT_WRITE

最终权限集合以正式权限模型和 OpenAPI spec 为准。

## 12. 错误处理

所有响应使用统一：

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {}
}
```

`code=0` 表示当前 API 请求成功。

交易 API 还必须结合后续订单状态事件验证最终状态，尤其在异步订单链中不能把“已受理”误解成“已成交”。

## 13. Broker 集成验收

上线前至少验证：

- API key login；
- 创建 customer；
- customer cashIn；
- 代客户 placeOrder；
- maker / taker 成交；
- cancel；
- queryOpenOrder；
- queryTradePosition；
- queryAccountBalance；
- cashOut；
- 跨 location 请求被拒绝；
- reconnect / token refresh；
- rate limit；
- idempotency。


## 14. Rate Limits

当前 GW 已实现 Token Bucket OpenAPI 限流。

Broker API 目前仍使用现有 API / TenantAPI profile，**尚未实现独立 `BROKER_STANDARD`**。

因此：

- 不应在客户文档中提前承诺 Broker 500 QPS、1000 QPS 等未验证数值；
- Broker 正式 profile 应在 OrderSvr / TradeSvr 性能优化和 Broker 并发压测后确定；
- 当前 rate limit 语义、错误码和默认 profile 见：

`docs/api/RATE_LIMITS.zh-CN.md`

当前超限：

`10003 RATE_LIMIT_EXCEEDED`

当前没有 per-method weight。
