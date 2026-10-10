# API documentation changes

## 2026-10-10 — Trader account read routing clarification

- `TradeSvr/queryAccountBalance` and `TradeSvr/queryTradePosition` examples now include `key: "YOUR_TENANT_LOCATION"`. This is the gateway **partition routing key**, not an account selector.
- The authenticated `sessionId` remains authoritative for the trader's tenant, user identity, and permissions. Neither `key` nor `content` may be used to access another account. This corrects the reference examples; it does **not** announce a new API method or a verified live API Key acceptance result.

## 2026-10-01 — bilingual developer preview

- The existing Open API v1 contract remains the source of truth; no new gateway method is claimed by this documentation release.
- English and Simplified Chinese overview, onboarding, authentication, Trader, Broker, realtime, rate-limit, release-status, and method-catalog pages are now built together.
- The 28-method catalog in both editions is generated from the same validated OpenAPI YAML. Detailed field-level prose remains primarily in Chinese, and English pages link to it explicitly.

For future API changes, update the OpenAPI YAML and both changelog pages. The bilingual checker requires paired guide changes and paired release notes when contract/reference source files change.
