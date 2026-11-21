# DC Trading API v1

当前基线：2026-09-19。

本文定义 Trader API 与 Broker Trading API **共同使用的交易能力**。两者下单、撤单、行情、订单、成交、余额、持仓、账户配置和历史查询的业务字段保持一致；区别只在“目标交易账户是谁”。

## 1. 账户作用域

| 调用者 | 目标账户 |
| --- | --- |
| Trader API Key (`type=trade`) | 只能是当前 API Key 所属交易账号 |
| Broker API Key (`type=broker`) | 必须显式指定本租户的客户 `customerId/userId` |

Trader 不能通过请求字段切换到其他客户。Broker 也不能跨 `location` 操作其他租户客户。

Broker 目标客户必须满足：

```text
customer.location == broker.location
customer.user_type == TRADER
customer.enable == 1
```

交易写操作还要求客户 `enable_trade == 1`。

## 2. 共同交易能力

| Operation | 权限 | Trader | Broker |
| --- | --- | --- | --- |
| Market data | `MARKET_READ` | ✅ | ✅ |
| Place order | `ORDER_WRITE` | 自己 | 指定本租户 customer |
| Cancel order | `ORDER_WRITE` | 自己 | 指定本租户 customer |
| Cancel all/batch | `ORDER_WRITE` | 自己 | 指定本租户 customer |
| Query orders | `ORDER_READ` | 自己 | 指定本租户 customer |
| Query executions | `ORDER_READ` | 自己 | 指定本租户 customer |
| Query durable history | `ORDER_READ` | 自己 | 指定本租户 customer |
| Query balances | `ACCOUNT_READ` | 自己 | 指定本租户 customer |
| Query positions | `ACCOUNT_READ` | 自己 | 指定本租户 customer |
| Read account config | `ACCOUNT_READ` | 自己 | 指定本租户 customer |
| Set leverage / position mode | `ORDER_WRITE` | 自己 | 指定本租户 customer |

## 3. 标准下单业务模型

对外业务字段：

```json
{
  "symbol": "BTCUSDT",
  "market": "CRYPTO",
  "side": "BUY",
  "positionSide": "LONG",
  "orderType": "LIMIT",
  "timeInForce": "GTC",
  "quantity": "0.010",
  "price": "60000.0",
  "clientOrderId": "client-000001",
  "reduceOnly": false
}
```

Trader 调用时账户由认证 Session 决定，不接受切换账户。

Broker 调用同一订单模型，但额外指定：

```json
{
  "customerId": "customer-user-id",
  "order": {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "orderType": "LIMIT",
    "quantity": "0.010",
    "price": "60000.0"
  }
}
```

### 新单过载时的处理（T554 候选版本）

通过 TCP 调用 `OrderSvr/placeOrder` 时，检查回包里的业务字段 `code` 和 `msg`。

| 回包 | 订单状态与客户端动作 |
| --- | --- |
| `429 / ORDER_BUSY_RETRYABLE` | 本次新单在受理前被拒绝，没有取得订单号，也没有触发预占。稍后使用同一个 `ClOrdID` 和原参数退避重试，并给重试增加随机间隔。 |
| `409 / ORDER_ADMISSION_IN_PROGRESS` | 同一个 `ClOrdID` 的上一次请求正在确认。保留原 ID 和参数，查询订单或稍后重试。 |
| `0` | 订单已受理。成交结果以该账户的最终成交回执为准。 |

撤单使用原有的 `cancelOrder` 通道。客户端继续依次处理 `Pending_Cancel` 和 `Cancelled`。连接中断或超时后，先按原 `ClOrdID` 核实结果。

## 4. 当前 v1 GW 传输映射

当前运行时仍复用 GW envelope。标准外部资源模型与内部服务映射如下：

| External operation | GW mapping |
| --- | --- |
| Login | `LoginSvr/apiKeyLogin` |
| Market | `MDSvr/queryPublicMarket`, `queryKLine` |
| Place order | `OrderSvr/placeOrder` |
| Cancel order | `OrderSvr/cancelOrder` |
| Batch cancel | `OrderSvr/cancelBatchOrder` |
| Orders | `OrderSvr/queryOrder`, `queryOpenOrder` |
| Executions | `OrderSvr/queryExecOrder` |
| Balance | `TradeSvr/queryAccountBalance` |
| Position | `TradeSvr/queryTradePosition` |
| Account config | `TradeSvr/getAccountConfig` |
| Leverage | `TradeSvr/setLeverage` |
| Position mode | `TradeSvr/setPositionType` |
| Historical orders | `ProjectionSvr/queryProjectedOrderHistory` |
| Historical executions | `ProjectionSvr/queryProjectedExecutionHistory` |

HTTP transport details are in [字段级调用参考](../DC_OPEN_API_V1_REFERENCE.zh-CN.md)。未来如果 GW 增加 REST-friendly `/v1/*` façade，该 façade 只做协议映射，不改变以上交易语义或核心服务。

## 5. WebSocket

Trader 私有流只能订阅自己；Broker 私有流可以订阅本租户指定 customer 的订单、成交、余额和持仓。

Topic、snapshot/delta、Gap 和 reconnect 规则见 [WebSocket / Topic Reference](WEBSOCKET_TOPICS_V1.zh-CN.md)。
