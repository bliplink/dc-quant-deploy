# Broker API

A Broker can build its own website, app, backend, customer management, and trading frontend while using OpenTradingCore's core services. The Broker acts for customers it owns **within the same `location`**; other tenants and Brokers remain isolated.

Broker keys sign in through the same `LoginSvr/apiKeyLogin` flow as Trader keys. A successful Broker session has `client_type=TenantAPI` and `api_key_type=broker`. The session's actor remains the Broker; it does not become a customer login. Subsequent calls use `POST /httpapi/` and `sessionId`.

| Workflow | Current gateway methods |
| --- | --- |
| Customer/trading user management | `AdminSvr/tenantUserAdmin`, `AdminSvr/tenantUserRegistration` |
| Customer cash ledger | `TradeSvr/cashIn`, `TradeSvr/cashOut` |
| Orders and cancellations | `OrderSvr/placeOrder`, `cancelOrder`, `cancelBatchOrder` |
| Customer balance and positions | `TradeSvr/queryAccountBalance`, `queryTradePosition` |
| Orders, fills and durable history | `OrderSvr/queryOrder`, `queryExecOrder`; `ProjectionSvr/queryProjectedOrderHistory`, `queryProjectedExecutionHistory` |
| Public market data | `MDSvr/queryPublicMarket`, `queryKLine` |

Every customer operation must pass the server's `location`, ownership, and permission checks. Supplying a customer `UserID` in the body does not bypass them. An HTTP `code=0` for order placement only confirms request acceptance; reconcile the eventual state before reporting a fill.

Cash-operation idempotency and ambiguous-outcome recovery are **not yet External GA ready**. In this demo environment, record a stable request identity and reconcile the ledger before any retry; do not treat transport timeout as failure. See [release status](status.md).

The current Broker session uses `TRADER_STANDARD` (100 requests/s refill, burst 30), not a dedicated high-QPS Broker profile. That is an implementation limit, not a throughput SLA. Consult the [method catalog](openapi/CATALOG_GENERATED.md), [authentication guide](authentication.md), and [full Chinese Broker reference](/zh/openapi/BROKER_REFERENCE_V1.zh-CN/) for exact fields and constraints.
