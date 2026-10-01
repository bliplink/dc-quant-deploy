# OpenTradingCore Developer Preview

Build a trading client with the Trader API, or connect your own customer application with the Broker API. Both use the OpenTradingCore gateway and the same order schema; their identity and customer scopes differ.

!!! warning "Developer Preview — not External GA"
    This environment uses demo funds only. Public API documentation is available for evaluation, but the trading stability, SDK, external WebSocket and cash-idempotency release gates are not complete. Do not connect real funds or treat this site as a production SLA.

## Choose your path

| I want to… | Start here |
| --- | --- |
| Trade my own account or write a strategy Robot | [Trader guide](trader.md) and [Quick start](quick-start.md) |
| Build a Broker website or backend for my customers | [Broker guide](broker.md) and [Authentication](authentication.md) |
| Inspect current method names, permissions and request schemas | [YAML-derived method catalog](openapi/CATALOG_GENERATED.md) or [download OpenAPI YAML](openapi/crypto-openapi-v1.yaml) |
| Handle streaming and reconnects | [Realtime and recovery guide](realtime.md) |

The current gateway transport is `POST /api` for signed API-key login and `POST /httpapi/` for authenticated requests. The [Quick start](quick-start.md) shows the actual envelope; REST-style `/v1/order` paths are **not** part of this version.

This English edition covers the integration path and all 28 method names. The full field-level reference is currently available in [简体中文](/zh/); English field-by-field translations and installable SDKs remain release work. See the [release status](status.md) for the outstanding gates.
