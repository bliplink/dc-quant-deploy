# Trader / Broker API E2E blocker — 2026-10-10

## Reproducible P0

The `saas-crypto` isolated tenant lifecycle test reached the same failure twice:

1. Create and approve two new demo tenants; register two isolated test users.
2. Login as the tenant admin and the Trader.
3. Create a self-service Trader API Key with `MARKET_READ,ACCOUNT_READ,ORDER_READ`.
4. List keys (no secret returned) and perform HMAC-signed `LoginSvr/apiKeyLogin` successfully.
5. Send the resulting `sessionId` to `POST /httpapi/` for:

```json
{"serverName":"TradeSvr","method":"queryAccountBalance","content":{}}
```

**Observed:** GW `code=9000`, `msg=INTERNAL_ERROR`, in both runs. The gateway emitted `GW_METHOD_CALL_FAIL` with `serverName=TradeSvr`, `method=queryAccountBalance`, `async=true`, `responseCode=9000`, `replyStage=gateway_reply`, `durationMs=0`, and blank `failureCode`/`failureReason`. The gateway `OpenApiResponseSanitizer` deliberately converts unrecognized/non-public upstream errors or malformed responses to `9000 / INTERNAL_ERROR`. Thus the public response **does not reveal the original error code**, and this evidence alone cannot distinguish gateway routing, async dispatch, or downstream handler failure. Keep the sanitizer in place while investigating via trusted server-side diagnostics. Investigate before claiming API Key E2E or GA readiness.

**Expected:** successful account read for the authenticated Trader; or a specific documented rejection, not a generic internal error.

## Isolation and cleanup

- First isolated pair: `AA5156`, `BA5156` — manager API suspension succeeded; MySQL showed `SUSPENDED`.
- Second isolated pair: `A656D4`, `B656D4` — still `TRIAL` at the last read-only MySQL check. An automated suspension attempt was blocked by the execution environment's safety check; **do not treat these as cleaned up**. Verify disposition through an authorized operating path.
- The failed E2E invoked self-service key-revocation cleanup. The initial Bash JSON parsing bug was fixed in commit `028a6f0`; second run exited without a key cleanup warning. A fresh signed login rejection after revocation was not separately verified.
- No cash deposit, Broker Java runner, customer order, HA kill, or 200-tenant stress test was executed by these failed runs.

## Other checks

- Audited immutable Broker test image `ghcr.io/bliplink/robotsvr:sha-36b80cfca6c70e9c13e1b5f0114b4eb87d0d9872` passed the offline no-network preflight.
- Trader cleanup and Broker offline tests passed (7 + 18).
- Both desktop and mobile Trade Web loaded BTCUSDT and chart for an existing `TRIAL` tenant `BIHZYE`; an older route `VPLP73` was not present in the current tenant table and is not valid test evidence.
- Public main-site API link points to `https://api.opentradingcore.com/`.

## Next safe action

1. Investigate gateway `TradeSvr/queryAccountBalance` asynchronous dispatch and route requirements using a single isolated test tenant; preserve the authoritative identity guard.
2. Verify that all leftover test keys are revoked and clean up `A656D4` / `B656D4` via an authorized operator process. Do not bypass any safety gate.
3. Re-run Trader read-only balance, `ORDER_WRITE` order/cancel, Broker ownership denial, revocation, cash/execution persistence, then progress to staged Robot and HA tests only after the P0 is resolved.


## Follow-up: routing fix and live Robot audit (2026-10-10)

- Test-side fix `9041d59`: TradeSvr balance requests now include the tenant `key`. Follow-up `c142059` extends the shared offline GW route helper to `TradeSvr`, validates that supplied keys match their target, and ensures the tenant lifecycle test passes those requests through routing validation. GitHub Actions `validate-api-acceptance` completed successfully for `c142059` (run 38013500387). **This does not establish successful authenticated live balance reads:** earlier temporary API keys were cleaned up, default seeded Trader/Admin credentials return login code `9005`, and the earlier isolated tenants each have two users against a quota of two. Do not silently create more tenants just to bypass these constraints.
- Read-only public market verification for existing trial tenants `BIHZYE`, `DPGR6B`, and `DUJE16`: `MDSvr/queryPublicMarket` returned code `0`, with 20 depth entries and 200 recent-trade entries per tenant. The lists did **not** all refresh during a seven-second sample, which is not itself proof that active order flow stopped.
- Trade Web headless desktop/mobile smoke on those three real tenants: 6/6 cases passed; BTCUSDT was visible, chart loading cleared by about 4.5 seconds on all observed desktop cases, and no page JavaScript exceptions were captured. This smoke does not validate logged-in settings, orders, or account history.
- Robot MySQL read-only health snapshot: 13 enabled Robot records, of which 12 `RUNNING` and one `DEGRADED`. The affected tenant `DUJE16` had `open_order_count=0`, `last_error_code=RUNTIME_FAILURE`, and the recorded message `gateway TCP response is empty for cancelBatchOrder`. `BIHZYE` and `DPGR6B` each had a `RUNNING` Robot with 40 reported open orders; DPGR6B also retained one separately `STOPPED` disabled Robot record. RobotSvr logs also showed `ReadProtoProcess` queue critical warnings above 100.
- Resource snapshot: RobotSvr approximately 130% CPU and MySQL approximately 1.30 GiB / 1.5 GiB. Do **not** treat these brief measurements as peak utilization or a 200-tenant load-test result.
- **Safe recovery direction:** diagnose OrderSvr/GW empty `cancelBatchOrder` responses and reconcile actual open-order state before any replay; the current Robot gateway client intentionally forbids blind replay of ambiguous cancel writes. Do not restart trading nodes or escalate the load test until this and the Trader API Key P0 are understood.
