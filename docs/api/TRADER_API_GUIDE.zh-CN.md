# Trader API 使用指南

> 面向普通交易用户、量化用户和自动化策略。  
> Trader 不需要成为 Broker，也可以使用自己的 API Key 交易。

## 1. 适用场景

Trader API 适合：

- 量化交易；
- 自建交易前端；
- 自动下单策略；
- 风险监控；
- 账户 / 持仓同步。

Trader API 只允许操作 API Key 所属用户自己的账户。

## 2. API Key 登录

机器可读定义：

`docs/openapi/crypto-openapi-v1.yaml`

签名入口：

`POST /api`

使用：

- apikey；
- secret；
- expiry；
- HMAC-SHA256。

成功后返回：

- client_type；
- user_id；
- location；
- token；
- api_key_type；
- permissions；
- rate_limit_profile。

## 3. 下单

Session 请求入口：

`POST /httpapi/`

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
    "ClOrdID": "my-order-000001"
  }
}
```

Trader 常用能力：

- placeOrder；
- cancelOrder；
- cancelBatchOrder；
- queryOrder；
- queryOpenOrder；
- queryExecOrder。

## 4. 账户

可用能力：

- queryAccountBalance；
- queryTradePosition；
- getAccountConfig；
- setLeverage；
- setPositionType。

普通 Trader 不能查询其它用户账户。

## 5. 行情

Trader 可以查询 / 订阅：

- public market；
- Kline；
- bookTicker；
- depth；
- trade。

实时订阅应使用 GW WebSocket。

## 6. 历史

可查询：

- projected order history；
- projected execution history。

## 7. 权限

典型 Trader key：

- MARKET_READ；
- ACCOUNT_READ；
- ORDER_READ；
- ORDER_WRITE。

建议允许用户创建只读 key，例如：

- MARKET_READ；
- ACCOUNT_READ；
- ORDER_READ。

## 8. 安全

不要：

- 在浏览器明文保存 secret；
- 在日志输出 secret；
- 给普通 Trader TENANT_WRITE；
- 共用 Broker service key。

建议：

- 独立 API Key；
- 定期轮换；
- 最小权限；
- 失效后重新签名登录；
- 使用唯一 ClOrdID。

## 9. 异步订单语义

下单成功后仍应继续消费订单状态事件。

应用应区分：

- request accepted；
- Newing；
- New；
- Filled；
- Cancelled；
- Rejected。

不要仅根据一次 HTTP response 推断最终成交结果。

## 10. Trader API 验收

至少验证：

- signed login；
- market query；
- placeOrder；
- cancelOrder；
- open orders；
- order history；
- executions；
- position；
- account balance；
- reconnect；
- 权限越权被拒绝。


## 11. Rate Limits

普通 Trader API session 当前使用：

`TRADER_STANDARD`

默认：

| Parameter | Value |
|---|---:|
| Refill rate | 100 requests / second |
| Burst | 30 |
| Scope | sessionId |

算法为 Token Bucket。

当 token 不足时：

```json
{
  "code": 10003,
  "msg": "RATE_LIMIT_EXCEEDED"
}
```

当前所有受限业务请求统一消耗 1 token，尚未实现 per-method weight。

完整说明：

`docs/api/RATE_LIMITS.zh-CN.md`
