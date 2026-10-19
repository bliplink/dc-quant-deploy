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
- The present model has **one primary `data_source_id` per product**. A
  separately configured, ordered secondary source with automatic TTL failover
  has not been verified/implemented. The existing selector rejects stale
  custom prices rather than silently falling back to a different provider.
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
