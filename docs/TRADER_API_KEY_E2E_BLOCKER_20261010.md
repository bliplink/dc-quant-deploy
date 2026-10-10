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
