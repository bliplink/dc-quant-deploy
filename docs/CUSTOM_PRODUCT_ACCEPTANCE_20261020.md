# Custom tenant products — Demo acceptance (2026-10-20)

## Intended behavior

- Product identity is **`location + security_id`**, not global `dc_symbol.symbol`.
- Tenant admin creates an enabled product directly; there is **no ACTIVATE step**.
- Trading Web's tenant-scoped **`AdminSvr.querySymbol` is anonymous/read-only**.
  `tenantProductDataSource`, `tenantDataSourceAdmin`, and writes require auth.
- Only enabled products are returned by Trading Web and MD public market reads.
- Source tickers are independent of product IDs; fresh mark/index prices may
  differ by any percentage from the previously selected source.
- Expired TTL prices must not be forwarded to Trade/Liq as usable marks.

## Corrected price binding (2026-10-20)

**User-confirmed behavior:** one tenant product can have only **one current
source**, stored as `dc_tenant_symbol.data_source_id`. Tenant administration
may switch to a different enabled source in the same tenant using `BIND`.
After the AdminSvr `querySymbol` image refreshes, MD must use only the new
route; previous source ticks become unauthorized and cached quotes cannot
be reused. A fresh price can differ by any amount from the old price (no 1%
cap). The current quote's TTL alone determines price freshness; on expiry,
no old source or system/Binance price is used as automatic fallback.

The mistaken optional `fallback_data_source_id` migration and supporting
Admin/MD candidate logic were reverted locally and were never deployed.
Targeted tests verify route replacement, previous publisher refusal and
no-fallback-after-expiry. The Demo still needs a genuine authenticated BIND
followed by an actual APS tick and Trade/Liq publication acceptance.

## Verified locally on the Demo

1. Gateway `local/dc-saas-gw:public-csv-20261019`: CSV whitelist and
   authorization behavior verified after deployment.
2. MD A/B/C `local/dc-saas-mdsvr:enabled-public-products-20261019`:
   `H2FIJU/BTCUSDT` -> code 0; `H2FIJU/BTC001USDT` and `BTC002USDT` ->
   code 5004; `H00000/BTCUSDT` -> code 0. Use `MDSVR_CONFIG_NAME=MDSvrA`
   when recreating MD-A; omitting this parameter wrongly mounts the generic
   MDSvr config and breaks the P210 market route.
3. `dc_symbol.symbol_cn_name` and `.symbol_en_name` changed from 45 to 128
   chars with migration `20261020_dc_symbol_product_display_name_128.sql`.
   The handler permits 128-character display names; old columns would reject
   them. Schema asserted with `python3 tests/test-custom-product-schema.py`:
   **3 passed**. Pre-existing global templates remain.
4. `python3 tests/test-public-tenant-product-e2e.py --api-only --tenant H2FIJU
   --expect BTCUSDT --hidden BTC001USDT --hidden BTC002USDT` **passed**.
   The no-browser mode checks both Gateway and MD responses.
5. Standalone targeted Java regressions passed (all local): Admin symbol 6,
   Order scoped symbols 3, Trade membership/freshness 5, MD TTL/selector 15,
   APS broker price ingress 10. Local JUnit ad hoc CP must put SLF4J 1.7.30
   before other cached jars to avoid an unrelated `NoSuchMethodError`.

## Not yet accepted — do not declare a full pass

- A fresh tenant-scoped `dc_symbol` row via authenticated
  `tenantProductDataSource.CREATE`. The Demo had **0 scoped rows** at the last
  inspected checkpoint; the attempted test tenant creation and admin login
  execution were blocked by environment checks. Do not bypass authentication.
- New product `BTC003USDT` published to Order/Trade/MD and Trading Web.
- Broker price publication through authenticated `APSSvr.publishBrokerPrice`,
  end-to-end TTL expiry, and a live source rebind/switch.
- Matching two independently funded trader accounts, cancellation,
  balances/positions/execution consistency, and Trade A/B automatic failover.
- **One current `data_source_id` per tenant product**, not primary/standby.
  The tenant administrator changes the selected source explicitly with BIND.
  MD invalidates the former mapping on the refreshed authoritative catalog,
  accepts the current source if its quote TTL is valid, and does not enforce a
  switch-price deviation threshold. When the current quote expires, it becomes
  unavailable; no automatic fallback to the former provider is permitted.
- Playwright PC/mobile E2E was previously green, but one 2026-10-20 rerun
  timed out without producing a result. Browser pass has **not** been renewed.

## Resume steps (only within authorized runtime)

1. Confirm environment and code versions; preserve all unrelated dirty files.
2. Obtain an authorized tenant-admin session through the normal login flow,
   not through direct database/session manipulation.
3. Create `BTC003USDT` bound to an enabled source using the official admin
   endpoint; verify the inserted `dc_symbol` row and `dc_tenant_symbol` row,
   tenant `querySymbol` visibility and another tenant's isolation.
4. Publish index/mark price through the authorized Broker API using the source
   ID (not the product name), verify MD / Trade / Liq, TTL, old-source
   invalidation and binding revision/sequence fences. Do not impose a 1%
   deviation check.
5. Perform a real two-trader order match, balances/positions reconciliation,
   and only then the Trade A/B fault-injection acceptance.
6. Do not run GitHub Actions. Build locally, commit focused paths, deploy
   proven images to Demo. Never access the Mac Documents folder.

## Local commits

- Gateway: `9a33a3c` (local Gateway repository)
- MD: `62ff43c` (local MD working checkout)
- Deploy CSV: `abd1d93`
- Deploy DB schema: `3a4cd1a`
- Deploy public API-only regression: `b7cf259`

Commits are local; pushing to remote GitHub was not verified.
