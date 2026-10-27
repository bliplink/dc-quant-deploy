# T165 | Robot real Demo resumption preflight — 2026-10-26

## Intended acceptance

The success criterion is **live Robot quotes through Gateway -> Common-only Order/Trade -> MD depth**, with a proven real order ID, nonzero active maker orders, both bid/ask depth, cancel/fill, Trade balance/positions and Projection reconciliation. Unit-test quote images, signed Common E1 REPLAY_COMPLETE and Docker "Up" do **not** satisfy this end-to-end criterion.

## Real host inspection at 23:01–23:08 China time

- Official `dc-saas-ordersvr` A/B/C and `dc-saas-tradesvr` A/B are STILL exited (143) on T113 images. Robot, Gateway, Admin, MD and Projection are running.
- Official mounted Order/Trade config enables the retired `*.cluster.lifecycle.enabled=true`, `failover.enabled=true`, `replication.enabled=true`. Restarting T113 as a "quick Robot fix" contradicts the Common-only requirement and cannot provide certified Common writer admission. Leave OFF.
- New T164 isolated Order/Trade A/B run and have independent original RSA-2048 signed virgin physical E1 WAL receipts and genuine durable `REPLAY_COMPLETE` for P090. They run `CommonRecoveryOnlyProcess`, **never** invoke `ServerGwWrapper.StartCertifiedBusiness`, never expose the real Order/Trade HTTP/Gateway business ports, and are explicitly `RECOVERING`. Do not connect production Robot to them yet.
- Gateway's authoritative `robotRuntime` HEARTBEAT samples from the past 100 s include **25** distinct tenant locations: **0 RUNNING with nonzero open orders; 25 ERROR**. Actual error strings: `gateway rejected queryTradePosition: [1003] [1015] SERVER.TradeSvr is not Online` and `gateway rejected queryOpenOrder: [1003] [1015] SERVER.OrderSvr is not Online`.
- The existing Robot has previously recovered autonomously after a real, healthy OrderSvr restart, so no Robot scheduling/strategy configuration change is justified before restoring the business services (see `docs/ROBOT_WEB_E2E_QUOTE_RECOVERY_20260905.zh-CN.md`).

## Latest read-only verifier, executed

`python3 tools/t149-recovering-only/verify-t165-live-demo-robot-quote.py`.

Supports `--pilot LOCATION` for one real tenant during a safe gradual rollout; default tests all recently seen tenants. Returns exit 3 on missing Common-only real business servers / inactive Robot. Returns exit 4 if the preliminary live gateway heartbeat passes but authenticated real MD two-sided depth and trade end-to-end are not yet proved, so it **never declares a false full PASS**. No Docker changes or ZK mutations.

Expected observed output includes:

```
T165_ROBOT_RUNTIME_WINDOW_SECONDS=100 tenants=25 running_with_orders=0 errors=25
T165_ROOT_CAUSE=GATEWAY_ORDER_SERVICE_OFFLINE
T165_ROOT_CAUSE=GATEWAY_TRADE_SERVICE_OFFLINE
T165_NO_GO SERVICE_DOWN_dc-saas-ordersvr
T165_NO_GO SERVICE_DOWN_dc-saas-tradesvr
T165_NO_GO NO_REAL_ROBOT_ACTIVE_ORDER_HEARTBEAT
T165_LIVE_ROBOT_BID_ASK_NOT_CERTIFIED; no containers or ZK changed
```

## Non-negotiable next execution

1. Complete Common-only **initial zero-history E1 -> externally certified READY** transition, with all original physical RSA birth/custody, current ZK session and old recovery-writer exclusion; retain exactly one physical cluster implementation in Common. There is no current production implementation that can validly publish initial READY after T164 E1 RECOVERING. A manual ZK flag or altered config phase is prohibited.
2. Reopen/restore certified business snapshot into the **same actual Spring Order/Trade managers** that will serve, reattest volatile `CommonCertifiedBusinessReplayGate` after each JVM restart, then bind actual Netty/WAL/Business endpoints and certify write admission. T164 domain-only managers in a separate RECOVERING JVM do not prove READY JVM state.
3. Configure business deployment for a correctly routed canary partition and tenant; the current T164 proof covers **only P090**. Do not claim that all active tenants / 256 partitions are routed by it.
4. Retire T113 configuration and install new Common-only ARM64 Order/Trade images on the actual Demo network, verifying Gateway Online, Robot `RUNNING` and positive `open_order_count`. Then use `tests/run-robot-liquidity-e2e-host.sh` / authenticated real MD/Web tests to certify bid+ask, cancel, crossing fill and financial consistency.

No GitHub Actions. No invented live Robot quotes. Do not restart old legacy clusters.