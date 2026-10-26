# T155 — Demo Order/Trade replacement and Robot flow: live NO-GO gate (2026-10-26)

## Requested outcome

Replace the **currently stopped** Demo `dc-saas-ordersvr` A/B/C and `dc-saas-tradesvr` A/B with the newer unified Common implementation, then run the existing Robot through order placement, quote, cancel, match, fill, balance, positions and Projection without any service-owned cluster logic.

**T155 actual conclusion: do not swap the still-RECOVERING T153 candidates into the existing Demo right now.** Order/Trade Java binary compiles and 97/97 production-class isolated business smoke tests PASS, but the T153 Docker image is explicitly **not a business-serving image** under the current config. The source's OrderSvr/TradeSvr `main` selects `CommonRecoveryOnlyProcess.serve(...)` then returns BEFORE `ServerGwWrapper.StartCertifiedBusiness`; there is no Spring trading runtime or Gateway/FIX/API listener. The app is intended to refuse customer requests until authorized Common READY.

## Actual Mac findings

From actual Docker inspection at 2026-10-26 16:52 (+08:00):

- Official Order `dc-saas-ordersvr`, `dc-saas-ordersvr-b`, `dc-saas-ordersvr-c`: **EXITED (143)**, stopped at **2026-10-25T05:43:21Z**. Their original image is `local/otc-t113-ordersvr:survivor-custody-2f4b98e`.
- Official Trade `dc-saas-tradesvr`, `dc-saas-tradesvr-b`: **EXITED (143)** at the same time; original image `local/otc-t113-tradesvr:survivor-custody-2f87223`.
- The `dc-saas-robotsvr`, `dc-saas-gateway`, `dc-saas-adminsvr`, `dc-saas-projectionsvr`, `dc-saas-mdsvr*`, `dc-saas-mysql` and UI containers are RUNNING. Running Robot is **not evidence of an accepted live order**.
- Gateway logs show repeated `GW_METHOD_CALL_FAIL` targeting `OrderSvr.queryOpenOrder` and `TradeSvr.queryTradePosition`. A 25-second query counted **334 failed queryOpenOrder and 242 failed queryTradePosition**. Counts are a moving sample, not overall totals.
- The live isolated T149/T153 five nodes are UP 24+ minutes, original 3ZK are UP; `OrderSvrA` and `TradeSvrA` config explicitly shows `nodeRuntime.phase=RECOVERING`.
- Last T153 baseline: 6/6 original dual-RSA Genesis reopen, 5/5 real RECOVERING Netty business reject, 6/6 real ZK dual-voter lease/RSA, and repeatable ARM64 local image builds with ONE Common sha256 `58c71dd41b70cbb4ac97d6ab3887978c5204e2d4a464017257a23908b961f659`.
- T154 real production-domain isolated function smoke in `docs/T154_ORDER_TRADE_FUNCTIONAL_SMOKE_20261026.md`: **Order 45/45, Trade 52/52, no failures/skips**, including signed original dual-voter WAL, loopback Netty, cancel, matching rules, real Trade margin/positions. **Not an inter-container Robot transaction**.

## T155 repeatable live safeguard — executed

```bash
bash tools/t149-recovering-only/gate-t155-demo-order-trade-robot-swap.sh
```

This read-only script inspects exact official + candidate containers, current candidate phase, ZK three processes and Robot/Gateway status. Counts current Gateway method failures with no sensitive request content, and requires actual signed Common business replay / zero-WAL/custody / authenticated READY and Robot/Projection reconciliation. **It does not have a bypass flag or mutate Docker/ZK/Robot.**

Actual output ends:
```text
T155_NO_GO candidate_not_business_ready=ordersvr-a phase=RECOVERING
T155_NO_GO candidate_not_business_ready=ordersvr-b phase=RECOVERING
T155_NO_GO candidate_not_business_ready=ordersvr-c phase=RECOVERING
T155_NO_GO candidate_not_business_ready=tradesvr-a phase=RECOVERING
T155_NO_GO candidate_not_business_ready=tradesvr-b phase=RECOVERING
T155_NO_GO missing_verified_recovery_install_ledger_and_original_zero_WAL_Custody
T155_NO_GO missing_same_session_Common_ZK_certified_READY_and_new_business_JVM_probe
T155_NO_GO missing_real_Order_Trade_robot_order_fill_balance_position_Projection_reconciliation
T155_DEMO_ORDER_TRADE_ROBOT_SWAP_BLOCKED failing_gates=8
T155_NO_CHANGES: no Docker recreate, ZK CAS, Robot restart or Gateway routing mutation
```

The script exits **3** to intentionally fail any automated replace stage. The old stopped official services are reported as CURRENT DEMO OUTAGE, not themselves an excuse to refuse replacement: the refusal is solely because the candidates cannot accept business safely.

## Smallest real path to Robot trading

1. In Common only, supply a certified **initial** original per-voter zero-ACK WAL / CommitIndex / Custody audit attached to real new E1 namespace creation. A subsequent directory listing, a synthesized success callback or manual ZK `READY` flag is NOT admissible proof. On this development Mac user allows fresh data, so a new authentic E1 bootstrap is preferable to inventing old state.
2. Launch real Order/Trade business state managers **while fenced and without Gateway/customer TCP** and run `CommonCertifiedFreshGenesisInstall` using genuine dual-RSA Genesis, `CommonZkOriginalE1Census`, actual exclusive business lock, durable journal baseline, snapshot/zero-WAL restore and fsynced `REPLAY_COMPLETE` on BOTH original voters. Ensure a new JVM can verify persisted evidence.
3. Common grants external READY only after original lease fencing and installed business memory/journal proof, and the previous RECOVERING-only listener has been retired; real certified business server must pass `CommonBusinessRecoveryReadiness` and begin serving. No Order-/Trade-owned election, WAL or READY.
4. **Only THEN replace actual `dc-saas` Order/Trade Compose images** and run Robot in a low-impact canary (existing approved tenant, one symbol), validate actual order ID, quote+cancel, two-way crossing fill, Trade margin/balances/positions, admin/Projection watermark and a lack of duplicate order/fill, then release Robot to all tenants and test A→B→A. On mismatch stop new Robot trading, keep old data/evidence for reconciliation, and restore previously known safe version only after certified state compatibility is proven.

Current state: **T153 candidate deployment PASS, T154 unit/component business functional smoke PASS, T155 actual Demo+Robot business swap NO-GO.** Do not claim Robot quote/fill until genuine end-to-end evidence exists.