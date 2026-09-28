# DC Trading Operations Reference v1

> Core Trading Reference 的第二批操作接口。

---

# 1. Cancel Batch Orders

## Permission

`ORDER_WRITE`

## Server / Method

```text
serverName = OrderSvr
method     = cancelBatchOrder
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

当前内部批量撤单一次建议不超过已经验证的 50 条分片规模。

---

# 2. Query Order

## Permission

`ORDER_READ`

## Server / Method

```text
serverName = OrderSvr
method     = queryOrder
```

## Request

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

Trader 只能查询自己的订单。

Broker 只能查询当前 Broker location 内授权 customer 的订单。

---

# 3. Query Executions

## Permission

`ORDER_READ`

## Server / Method

```text
serverName = OrderSvr
method     = queryExecOrder
```

## Request

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

当前服务成交用于实时/近期查询。

长期 durable history 应使用 ProjectionSvr：

- queryProjectedOrderHistory
- queryProjectedExecutionHistory

---

# 4. Set Leverage

## Permission

`ORDER_WRITE`

## Server / Method

```text
serverName = TradeSvr
method     = setLeverage
```

## Request

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

杠杆设置成功后，最终账户风险状态以 TradeSvr 为准。

---

# 5. Set Position Mode

## Permission

`ORDER_WRITE`

## Server / Method

```text
serverName = TradeSvr
method     = setPositionType
```

## Request

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

允许值以当前 TradeSvr contract 为准。

---

# 6. Durable Order History

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
    "userId": "u-001",
    "securityId": "BTCUSDT",
    "limit": 100
  }
}
```

Trader API 查询时，Session identity 为权威身份。

content 中的 `userId/location` 不能覆盖 Session scope。

---

# 7. Durable Execution History

## Permission

`ORDER_READ`

## Server / Method

```text
serverName = ProjectionSvr
method     = queryProjectedExecutionHistory
```

使用与订单历史类似的查询模型。

---

# 8. Common Errors

| Code | Msg |
|---:|---|
| 8000 | ORDER_NOT_FOUND |
| 9002 | USER_SESSION_NOTEXIST |
| 9004 | PARAMETER_ERROR |
| 9016 | TRADE_PERMISSION_DENIED |
| 10003 | RATE_LIMIT_EXCEEDED |
| 10000 | NO_POSITION |
| 9000 | INTERNAL_ERROR |
