# Trade Web load sequence and Gateway baseline — 2026-10-10

## Browser smoke (read-only)

Ran `TRADE_WEB_LOAD_TENANTS=BIHZYE,DPGR6B,DUJE16 bash tests/run-trade-web-loading-smoke-host.sh` against the current local Trade Web Docker image, without signing in or changing tenant state.

- 3 valid trial locations × desktop/mobile = **6/6 passed** (HTTP 200; BTCUSDT present; no `No markets found` and no chart-loading placeholder by 8.5 s; zero captured JavaScript errors).
- Checked at about 1.5, 4.5 and 8.5 seconds. At 1.5 seconds, the chart was still loading in some cases. All six finished before the 4.5-second snapshot in the repeated observation.
- These are local-web, unauthenticated UI checks, **not** authenticated personal settings/API Key, mobile order history, full order-book data quality or end-to-end execution proofs.
- The host smoke accepts 1–5 explicit existing tenant locations and needs no application credentials. Do not use non-existent location `VPLP73` for current demo validation.

## Gateway method statistics (one-minute windows)

These are observed Gateway **method request** statistics, not peak system TPS, matching throughput, durable persistence or end-to-end latency:

| Window ending (container clock) | `OrderSvr/placeOrder` total / success / fail | Approx. requests/s | Mean / P95 gateway method duration |
| --- | --- | ---: | --- |
| 09:18:16 | 398 / 398 / 0 | 6.63 | 21 ms / 200 ms |
| 09:19:16 | 145 / 145 / 0 | 2.42 | 2 ms / 6 ms |
| 09:20:16 | 121 / 121 / 0 | 2.02 | 2 ms / 6 ms |
| 09:21:16 | 991 / 991 / 0 | 16.52 | 9 ms / 12 ms |

For `OrderSvr/queryOpenOrder`, the 09:20 window logged 4,884 calls (4,777 successful, 107 failed) and the 09:21 window logged 4,420 calls (4,311 successful, 109 failed). These are method-level failure counts and must not be silently equated to data loss or trading outages; classify the underlying errors before scaling up.

## Live resources at 09:21

- Tenants: **17** (15 `TRIAL`, 2 `SUSPENDED`). Test tenants `A656D4` and `B656D4` remained `TRIAL` in the last check. Prior sandbox suspension attempt was blocked by the environment safety check; do not bypass it.
- MySQL: 1.297 GiB / 1.5 GiB container memory; RobotSvr: approximately 130% CPU; OrderSvr 1.358 GiB / 3 GiB; TradeSvr 915.7 MiB / 2 GiB.
- These are instantaneous Docker samples, not resource limits inferred for 200 tenants.

## Outstanding gates

- Trader API Key signed login had worked, but unkeyed `TradeSvr/queryAccountBalance` failed with GW `9000`. The test and API docs now include the TradeSvr tenant routing `key`, but a credentialed **live rerun has not been completed**. No-session balance queries are still rejected with `10004` whether or not a tenant routing key is supplied.
- Additional credentialed E2E attempts were blocked by the execution environment safety checks. Do not bypass these checks or create additional orphan test tenants.
- Broker delegated-order permissions, revoke/re-login, account/order consistency, authenticated mobile settings, 200-tenant stress and HA injection remain unverified.
