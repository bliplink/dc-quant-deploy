# T145 — real OrderFacade certified staged NEWING state (Common-only cluster)

Date: October 26, 2026. Target `saas-crypto` and original `bliplink/com.app.dc.ordersvr`. No Order-owned election/replication/WAL implementation, Robot changes, or GitHub Actions build.

## What changed

- Added `OrderFacade.commitPreparedInitialOrderState(Order)` to the actual Order service's business facade. A full candidate order is validated with **non-maker**, strictly positive quantity and price, no previous visible order of that identity, and **only `OrderStatus.Newing` plus `ExecType.Newing`**. `New`/`Filled`/maker/market-without-price are strictly rejected because independent TradeSvr margin approval has not occurred. The preexisting OrderPartitionBarrier is used where installed; the candidate's timestamps are staged before commit and there is no live OrderManager mutation before Common returns its signed physical commit.
- Calls the unchanged T144 `OrderStateJournal.commitPreparedState(OrderStateMutation.from(...))` while the candidate is not visible; Common `CertifiedBusinessCommandRegistry.commitThenApply` serializes by partition, fsyncs A/B WAL through actual loopback TCP Netty, checks original RSA-signed CommitIndex, dual physical Custody and independent receipts, and then `OrderStateRecovery.apply` changes the actual `OrderManager`. No service-specific log replication, election or READY code was introduced.
- The **real business facade** is exercised by the existing `OrderCommonSinglePartitionRealStateTest` on P090 with existing A/B Demo RSA, two separately fsynced WAL/Custody/receipt directories and actual Netty server/transport. Duplicate initial order, unapproved `New`, maker, missing price and unassigned tenant are rejected without consuming the signed Common commit position. Common-only standalone physical interface (not live ZooKeeper election) is used in these tests.

## Exact verification

- `mvn -q -o test -Dotc.demo.existing.keys=<existing original Demo keys>`: **178 Order tests, 0 failures, 0 errors, 2 skipped**. Both targeted real Common TCP/Netty and original RSA unit/integration tests PASS. No fake signing or replacing existing RSA.
- `mvn -q -o -DskipTests clean package`: PASS.
- Official candidate `local/otc-t145-ordersvr:certified-pending-newing` is `linux/arm64`, carries exactly the same immutable Common T143 binary `com.app.common-3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT.jar`, SHA256 `9197029483a8d18032de0a8ca2f8888a9e62d8933b8cf8d4604206e246ca60ea`. No Common change or rebuild is needed for this Order-only business adaptation.

## Formal deployment **NO-GO** and concrete next work

**Do not turn on external Gateway / broker API trading yet.** This entry is an internal state-only business facade, *not* an authorized order workflow. It does not validate user session or obtain a TradeSvr margin/funds reservation, does not enqueue to `AbstractStrategy`, does not generate execution/match, and does not publish external `New` ACK. It must NOT be treated as a risk-approved order or a successful live trade. The current `StrategyFacade.routeNewOrder` still blocks at `OrderClusterAdapter.recordCommand` and `AbstractStrategy` / `OrderFacade` ordinary asynchronous NEW, cancel, trade/fill/crossing/batch paths still use the legacy fail-closed mutation ordering.

Next implement a deterministic, replay-safe signed business admission transaction for a **single actual authenticated limit NEW** (authorization, idempotent risk reservation in Trade, Order staged Newing under Common, risk result replay, then Common committed New/maker transition). Do not claim a distributed atomic transaction between Order and Trade unless a genuine durable reconciliation/outbox/saga handles death between the two commits. Then move cancellation, fills, positions/balances and Projection to exactly-once replay and restart comparison; only after working Gateway and matching, inject genuine A→B→A SIGKILL under load.

Current old `dc-saas-ordersvr*` / `dc-saas-tradesvr*` five containers remain `Exited(143)`; T84 Demo A/B remain UP. No live deployment, no Robot, no GH Actions, no new application cluster. Test A/B RSA processes share one Mac (not separate-host fault domains).
