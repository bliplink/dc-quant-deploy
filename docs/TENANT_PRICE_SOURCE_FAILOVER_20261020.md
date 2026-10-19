# Tenant product primary/standby price sources (2026-10-20)

## Contract

- Product key remains `location + security_id`.
- Tenant product management is authenticated. Anonymous Trading Web receives
  **only** the tenant-scoped read-only `AdminSvr.querySymbol` product list.
- `TenantProductDataSource.CREATE` supports `data_source_id` (required) and
  `fallback_data_source_id` (optional). `BIND` uses the same two fields;
  omitting the fallback removes any previous standby. `UNBIND` removes both.
- Primary and standby IDs must differ. Both sources must already be enabled
  for the same tenant. Source metadata cannot be edited/deleted while bound.
- Admin `querySymbol` authoritative image contains source routes with
  `route_priority=0` (existing primary) and `route_priority=1` (standby).
  MD loads the complete image and resolves both without querying SQL on its
  price hot path. Revoked routes disappear on refreshed images.
- MD selects a fresh primary, otherwise a fresh standby; stale quotes are
  rejected. No 1% or any other prior-price deviation cap is applied.
- Standby Binance price must have a usable epoch-millisecond `sendingTime`
  no older than `broker.price.binance.fallback.ttlMs` (default 10000 ms,
  supported range 1000–60000 ms). Otherwise it is *not* a valid fallback.
- Custom APS prices retain their source-time TTL, lease/sequence and tenant
  isolation requirements. On expiry without a live backup the effective mark
  becomes unavailable rather than reusing a stale Binance/system quote.
- There is no additional ACTIVATE API: CREATE inserts an enabled product.

## Source and database changes

- Migration: `mysql/migrations/20261020_dc_tenant_symbol_fallback_source.sql`
  adds a nullable `dc_tenant_symbol.fallback_data_source_id`.
- AdminSvr local source commit: `db138cc`.
- MD local source commits: `e2ef7a6`, `df1711a`.
- These are local code commits, not confirmed pushed to GitHub.

## Local regression evidence

- AdminSvr targeted JUnit: **10 passed**, including source-binding validation,
  tenant catalog serialization and backup source priority.
- MD targeted JUnit: **33 passed**, including primary-to-backup TTL switching,
  arbitrary price deviation, both sources stale, tenant isolation and stale
  Binance standby. A further JSON image parsing test also passed (14 catalog
  tests). These are **not** proof of deployed transaction/failover behavior.

## Deployment state and sequencing

**NOT DEPLOYED as of this document.** Runtime rejected the attempted Demo
migration, so the fallback column was not installed and neither AdminSvr nor
MD has been replaced with this candidate. Do not recreate them using the new
build until schema installation is independently confirmed.

1. Confirm `fallback_data_source_id` does not already exist in `dc_tenant_symbol`;
   execute the one-time migration through the normal authorized deployment
   process, then verify type and nullability.
2. Build candidate AdminSvr and MD images **locally** from the commits above.
   Preserve the existing application configuration, including the previous
   broker-price feature flags and three MD node identities. When recreating
   MD-A, explicitly use `MDSVR_CONFIG_NAME=MDSvrA`.
3. Deploy MD candidate rolling (learner first); deploy AdminSvr when MD can
   parse `route_priority`. Perform `querySymbol` full-image refresh.
4. Through a genuine authorized tenant-admin session bind `BTC003USDT` to an
   enabled primary/backup source. Verify the public product list and a second
   tenant's inability to see the product.
5. Publish independent authenticated APS price events for both sources with
   valid timestamps. Verify primary preference, TTL expiry switch to standby,
   return to primary after fresh tick, and fail-closed when neither is valid.
6. Fund two independent test traders through the supported account API, match
   orders, cancel orders and reconcile balances/positions/executions. Run
   Trade A/B automatic failover only after this checkpoint is green.
7. Reject deployment if tests fail; do not invent live acceptance results or
   bypass login/session enforcement.

## Remaining product work

- The tenant administration UI still needs a fallback-source selector and
  a visible source status (READY/STALE/UNAVAILABLE).
- Live end-to-end Broker price, real order matching, Trade/Liq stale-price
  enforcement under failover, and 200-tenant load remain unverified.
