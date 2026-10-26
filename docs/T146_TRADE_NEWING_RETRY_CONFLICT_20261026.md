# T146 — Trade Newing request conflict guard for future certified risk reservation

Date: 2026-10-26. Branch `saas-crypto` isolation; local Mac arm64. No cluster implementation in Trade; Common T143 reused with byte-identical JAR. No Robot or GitHub Actions.

## Actual defect and code changes

- Original Trade `ExecutionDeduplicator` used location+orderID+execType+ordStatus as key for successful `Newing`. A message with SAME order ID/status but DIFFERENT price/quantity/user/side/tenant/product could receive the old success, masking a request/financial conflict. For a fully integrated risk-reservation workflow, same-command retries must be equivalent and conflicts must fail closed.
- Introduced immutable SHA-256 original request fingerprint for `Newing` with length-delimited Location, OrderID, UserID, SecurityID, MarketIndicator, Demo, Side, OCType, Price, OrderQty, TimeInForce, OrdStatus. `ExecutionDeduplicator.requireMatchingApplied(report)` returns original result for genuine exact duplicates; throws `TRADE_NEWING_CONFLICTING_OR_UNVERIFIED_RETRY` on conflicting price/quantity/user/etc or original success without authenticated fingerprint (older WAL/snapshot unknown -> FAIL CLOSED).
- Trade's **real** `OrderFacade.updateOrderInside()` uses this comparison BEFORE it invokes `CheckManager.updateOrder` (which invokes actual `ProcessOrder` risk calculations). Successful `Newing` now passes its original report when marking the request as applied. Dedup's Trade / Trade_Cancel existing keys and behavior remain unchanged.
- Fingerprint is saved and restored as a `Snapshot.AppliedEntry.fingerprint` field, following the Trade business snapshot; `TradeRecoveryApplier` additionally restores it from the committed `TradeExecutionDedupeMutation.report` in a WAL state batch. Old snapshot marker missing fingerprint is intentionally non-replay-safe. Pruning and tenant-location clearing remove the companion fingerprint.

## Tested

- `ExecutionDeduplicatorTest`: identical Newing -> return same result; altered quantity or price -> reject; serialized snapshot -> NEW JVM restores original economics and rejects conflicts; old snapshot marker lacking fingerprint -> reject; conflicting committed dedupe replay -> reject.
- `OrderFacadeLifecycleOrderingTest`: real Trade OrderFacade with an instrumented `CheckManager` verifies risk check runs exactly ONCE for identical retries and is NOT invoked again after a conflicting retry. Existing order lifecycle and cancellation behavior unchanged.
- Full Trade `mvn -q -o test -Dotc.demo.existing.keys=<existing original RSA>`: **199 tests, 0 fail, 0 errors, 0 skipped**. `mvn -q -o -DskipTests clean package` PASS.
- Official `local/otc-t146-tradesvr:newing-retry-signed-state` Docker image built `linux/arm64`. Inside image one unchanged Common `3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT` JAR SHA256 `9197029483a8d18032de0a8ca2f8888a9e62d8933b8cf8d4604206e246ca60ea`. NO local Trade WAL copy/election. No live deployment.

## Remaining NO-GO — not a durable funds transaction yet

- This guard does NOT make the existing `ProcessOrder.checkOpen()` freezes commit-first. That code still mutates `Position` and `AccountBalance` directly, then `TradeExecutionStateRecorder.record()` snapshots after side effects; `TradeStateCoordinator.requireWritable()` properly rejects production Common-cluster mutation before these effects. The Test's `CheckManager` is a deterministic call counter, NOT an end-to-end balance or margin authorization. Neither Trade financial HA nor order-to-Trade distributed atomicity is established by T146.
- Next refactor `ProcessOrder` on OPEN Newing into a **pure after-state planner** operating on copies of authoritative account/position plus idempotency state; prepare one `TradeStateBatch` with account, position, order request and dedupe result; call existing Common `TradeStateCoordinator.commitPreparedState()` and apply exact WAL bytes only after signed physical ACK (NO legacy mutation callback). Validate same original request retry and mismatched request; fail-closed if apply/crash before business ACK. Only then connect Order T145 pending-Newing and risk-approved New/cancel matching.
- Service original ZK Genesis/RECOVERING signed source recovery and persisted READY, actual gateway down/up, A→B→A physical fault and authoritative Order/Trade/Projection reconciliation remain NO-GO. The five old Order/Trade services remain stopped; T84 Demo continues. Do not bypass Trade requireWritable or open trading.
