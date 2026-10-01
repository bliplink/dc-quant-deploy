# Trader API

Use a Trader key for your own account, a custom trading frontend, a strategy Robot, or risk monitoring. The key cannot operate another user's account and does not need Broker privileges.

1. Obtain a Trader API key with the minimum required permissions.
2. Perform [signed login](authentication.md) through `LoginSvr/apiKeyLogin`.
3. Use `POST /httpapi/` with the `sessionId` header and a GW envelope.
4. Consume order-state events and reconcile queries; an accepted request is not a final fill.

| Purpose | Gateway methods | Typical permission |
| --- | --- | --- |
| Market and candles | `MDSvr/queryPublicMarket`, `MDSvr/queryKLine` | `MARKET_READ` |
| Orders | `OrderSvr/placeOrder`, `cancelOrder`, `cancelBatchOrder` | `ORDER_WRITE` |
| Current and past orders | `OrderSvr/queryOrder`, `queryOpenOrder`, `queryExecOrder` | `ORDER_READ` |
| Account and position | `TradeSvr/queryAccountBalance`, `queryTradePosition`, `getAccountConfig` | `ACCOUNT_READ` |
| Settings | `TradeSvr/setLeverage`, `setPositionType` | `ORDER_WRITE` |
| Durable history | `ProjectionSvr/queryProjectedOrderHistory`, `queryProjectedExecutionHistory` | `ORDER_READ` |

Use a unique `ClOrdID` for each intended order. After a timeout, first query that identifier and reconcile the current state; a missing HTTP response does not prove the order failed. See the [quick start](quick-start.md) for a Limit order envelope and the [method catalog](openapi/CATALOG_GENERATED.md) for all current methods.

Read-only keys should omit `ORDER_WRITE`. Never expose the secret in browser JavaScript, share a Broker service key with a Trader, or log credentials. For detailed order fields and lifecycle semantics, see the [full Chinese trading reference](/zh/openapi/CORE_TRADING_REFERENCE_V1.zh-CN/).
