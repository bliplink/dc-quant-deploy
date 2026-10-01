# Release status

OpenTradingCore's public Trader and Broker API documentation is available as a **Developer Preview**. This is a demo-funds environment, not an External GA service or a production SLA. A [Chinese edition](/zh/status/) is available.

The current method catalog and request schemas are generated from the checked OpenAPI YAML. They describe the gateway's existing API envelope; a conventional REST `/v1/*` API is not currently available.

Before External GA, the project still needs documented and verified stability and failover targets, higher-load and long-duration trading tests, finalized external WebSocket wire contracts, installable Trader/Broker SDKs with end-to-end tests, cash-operation idempotency and ambiguous-outcome recovery, and a dedicated sandbox credential/reset flow. English reference coverage also needs to be completed.

Do not use real funds. For early integrations, test with disposable demo accounts and design clients to reconcile ambiguous order or cash outcomes before retrying.
