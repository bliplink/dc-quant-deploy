# Tenant-defined product and signed API SDK — 2026-10-20 checkpoint

## Scope

This delivery improves the **public business APIs and Python SDK only**.
The user is validating Common/Trade HA separately; no HA changes, fault
injection or order/trade state machine changes were made here.

## SDK 0.1.2 (published on local Demo API Docs)

Source checkout: `.work/opentradingcore-api-docs`, `saas-crypto` commit `3f4441a`.
The download files are served at:

- `/sdk/opentradingcore-0.1.2-py3-none-any.whl`
- `/sdk/opentradingcore-python-sdk-0.1.2.zip`

Relative paths are rooted at `https://api.opentradingcore.com/`. Local Demo
verified HTTP 200, correct ZIP signatures and sizes (wheel 12,520 bytes,
source ZIP 14,794 bytes). The updated documentation was served for both
`/en/` and `/zh/`, including the new versioned SDK links.

Corrections:

- `publish_price(data_source_id=...)` sends the single **currently bound**
  price-source identifier to APS. The first positional `symbol` parameter
  is still accepted for legacy clients but now means **price source ID**,
  independent of the tradable `BTC003USDT` product. Stale TTL values cannot
  be used; there is no 1% switch deviation constraint or automatic standby.
- `place_limit_order` / Broker `place_customer_limit_order` normalize caller
  `BUY`/`SELL` into **OrderSvr wire enums `Buy`/`Sell`**; the signed Trader
  identity or explicitly authorized Broker customer identifies `UserID`.
  `Location` is bound to the signed tenant. `Terminal`, `AlgoName`, `Demo`
  and `ReduceOnly` are supplied for accepted business requests.
- Close-order helper arguments `oc_type='CLOSE'`, `position_side='Long'`
  or `'Short'`, `reduce_only=True` are required together and are checked
  against the opposite closing side. Trader and Broker order/cancel scopes
  remain distinct. Cancel requests now carry required user/tenant identity.
- `examples/demo_custom_price.py` is included in the source archive; it
  prompts for API credentials and will not publish without `--publish`.
  Existing read-only trader/broker examples are also packaged.
- No order/place/cancel or price-write operation is automatically retried
  after ambiguous timeouts. Reconcile using the caller's unique ClOrdID.

### Verification

- Python SDK: **21 of 21** unit tests passed, including delegated customer
  identity, HMAC login, independent source ID, exact OrderSvr request enums,
  required close parameters and Broker/Trader permission boundaries.
- Public OpenAPI v1 schema: **17** methods with request schemas, and **16**
  externally displayed method entries per language. `openapi_spec_validator`,
  catalog verification and both MkDocs strict builds passed.
- Legacy Order source checkout (`.work/ordersvr-tenant-enabled-origin-20261019`):
  25 of 25 targeted ArgsCheck, pending cancel, batch cancel identity and
  CrossStrategy TIF JUnit tests passed. These were **not** run against the
  new source checkout or the running Demo binary and do not prove new live
  cancellation/close/concurrency behavior.

## Actual transaction baseline from previous Demo validation

`GRXY6A` and `UG55XU`: each had two matching limit orders on BTC003USDT,
result `Filled` on both sides, with two corresponding execution records.
Broker-signed TenantAPI price publication, MD TTL and Web display were also
verified in previous runs. Those trader orders used ordinary **WEB sessions**;
this delivery's SDK changes are not proof that signed Trader API keys have
performed a new live trade. The attempted extension to execute new signed
trader funding and matching was blocked by the execution environment, and
was not run or committed. No fake fills or failover claims were made.

## Remaining acceptance gates

1. Use a real **signed Trader API Key** per participant on a new Demo tenant,
   verify SDK 0.1.2 `login`, `balances`, `positions`, `place_limit_order`,
   `cancel_order`, `order_history` and `execution_history` after actual writes.
2. Verify Broker signed delegate order, cancellation and **reduce-only close**
   against an explicitly authorized customer with suitable scopes. Do not
   conflate a Broker's simulated Demo customer cash operations with real
   deposits or withdraws.
3. Reproduce and diagnose two nearly simultaneous opposing same-price
   orders that previously remained `New` until cancellation. A Maker-first,
   resting-then-Taker flow passed, but concurrent matching did not.
4. Real Demo close/cancel and realized PnL/position/fee reconciliation, with
   no cross-tenant effect, remains outstanding.

## Deployment

The local Compose override `config/api-docs-sdk-012-20261020.yaml` replaces
only `api-docs`. Include it after `config/frontend-language-rollout-20261020.yaml`
in an authorized Demo roll-out. Current image:
`local/dc-saas-api-docs:sdk-012-20261020`. No GitHub Actions or backend
containers were used in this update; no Mac Documents folder access.
