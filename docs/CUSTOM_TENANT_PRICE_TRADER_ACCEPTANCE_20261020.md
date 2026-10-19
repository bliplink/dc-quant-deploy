# Tenant custom source → custom product → two trader match (2026-10-20)

## Scope (user confirmed)

**Only tenant API custom pricing and ordinary trader transaction flows.**
Do not change or fault-inject Trade/Common HA. Product identity is
`location + security_id`. Each tenant product has **one current** data source;
BIND switches that source explicitly. Old source price is invalidated; a
current source quote is usable only during TTL. No price deviation threshold.

## Live Demo acceptance — PASS

Test tenant: `GRXY6A` (fresh via ordinary tenantApplication auto-approval).
New product: `BTC003USDT`, created/enabled directly via authenticated
`AdminSvr.tenantProductDataSource.CREATE` without ACTIVATE.

Steps observed from normal authenticated endpoints:

1. TenantAdmin login; create two CUSTOM price sources and BIND product to
   current source `QA_ALT_7E24239810`. `tenantProductDataSource.LIST` returned
   the one current binding. Public `AdminSvr.querySymbol` listed the product;
   a different tenant could not see it.
2. Generate a tenant Broker API Key, sign in to TenantAPI, submit
   `APSSvr.publishBrokerPrice` for current source with `index=90000`,
   `mark=90001` and TTL 60000 ms; APS response `code=0 ACCEPTED`. Public MD
   received the mark, and the Broker API Key was revoked in script cleanup.
3. Register/login **two distinct ordinary WEB trader accounts** using the
   formal tenant registration/login APIs. Set 10x leverage on BTC003USDT and
   simulate cash-in 1000 each via authenticated TradeSvr APIs. Both traders'
   private `TradeSvr.queryAccountBalance` returned balance 1000 before trading.
4. Submit Sell 0.001 @ 90000 (Maker), wait for durable `New` resting state,
   then Buy 0.001 @ 90000 (Taker). Both OrderSvr.placeOrder calls succeeded.
   Both `dc_orders` records became `Filled` with `cum_qty=0.001` and each
   account had one `dc_orders_execorders` record at 90000.
5. Trader `TradeSvr.queryTradePosition` and `queryAccountBalance` returned:

| Role | Direction | Filled qty | Execution fee | Balance after | Used margin | Position |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Maker | Sell | 0.001 | 0.018 | 999.982 | 9.0594 | Short 0.001 |
| Taker | Buy | 0.001 | 0.054 | 999.946 | 9.0486 | Long 0.001 |

Verified independently with read-only queries on the MySQL order, execution,
balance and position projections. This is a **real Demo transaction**, not
unit-test-only proof. No actual external cryptocurrency transfer took place.

## Important acceptance observations

- Private Trade read APIs require the **tenant routing `key`** even when
  `content={}`. The first E2E version omitted it and returned gateway 1003.
  Supplying the correct routing key resolved balance and position queries,
  without modifying Trade code.
- Immediately after Admin CREATE, OrderSvr can report `5004 SYMBOL_NOTEXIST`
  while its bounded authoritative Admin catalog refresh is pending. The E2E
  script re-attempts only **explicit 5004 rejections**; it never retries an
  ambiguous accepted or timed-out order. It refreshes the currently bound APS
  quote before TTL expiry during this wait. No extra registration/ACTIVATE API.
- An earlier near-simultaneous pair of same-price orders in `ZXRUZ7` both
  remained `New` until their test-only cancellation. This **concurrent order
  sequencing case is not accepted**. The successful documented transaction
  waits for the Maker to become a resting order before submitting the Taker.
  Do not extrapolate this test to concurrent matching stress acceptance.
- The previously observed stale cached public mark was fixed in MD
  (`ttl-public-mark-refresh-20261020`), confirmed live with `MarkPrice=null`
  after TTL on `N9NZV5/BTC003USDT`.
- This run did not include account withdrawals, separate cancellation success
  proof, or post-close realized PnL. Those are additional business regressions,
  not prerequisites for showing that trader custom-product matching works.

## Reproduce (local Demo, no HA)

```bash
python3 tests/test-custom-product-live-e2e.py --execute --with-traders
```

The opt-in script generates a new throwaway tenant, source IDs, two random
trader accounts, one temporary Broker API Key and fresh ClientOrderIDs.
Sensitive login credentials remain in process memory, are not printed, and
Broker API Key cleanup occurs even on test failure. Mutations are restricted
to official authenticated APIs. `readonly_sql()` performs only SELECT.

Script commit: `6604f14` (`saas-crypto`, local only). Do not run GitHub Actions.
Do not access the Mac Documents folder; preserve unrelated dirty files/data.
