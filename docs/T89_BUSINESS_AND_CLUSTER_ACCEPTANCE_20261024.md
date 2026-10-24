# T89 Business + HA acceptance — 2026-10-24

## Single Common contract (unchanged)

The validated **Common + isolated Demo** source is the only cluster implementation. **No Order/Trade election, WAL, replication, repair, READY or ZK assignment algorithm is copied into Common.** Services own only `ReplicatedStateMachine` business callbacks and business validation. Unverified WAL tails always block READY. Do not turn off safety checks. No GitHub Actions.

## Candidate source convergence

- `com.app.common` remains `5ce1b3a` on `feat/common-t82-certified-custody-20261024` without new business-derived cluster code.
- `com.app.dc.ordersvr` contains the new Common `OrderRecoveryStateMachine` adapter and Common `ZkPartitionFailoverRuntime` integration. T89 further **deletes** its separate `OrderReplicaRepairCoordinator` (241-line private member promotion/CAS) and its scheduled repair loop, pending legitimate Common custody-driven rejoin integration. This removes an unauthorized alternate cluster authority; it does NOT mean rejoin is implemented end-to-end.
- `com.app.dc.tradesvr` `47644f4` deleted the private Genesis observer/CAS loop; it starts the Common `ZkPartitionFailoverRuntime`. Trade still has other private replication/recovery/READY paths and is NOT completed.
- The exact T87 Common JAR SHA-256 is shared by Demo, Order and Trade candidate dependency roots: `cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3`.
- Strict static release audit after T89 Order deletion: **21 passing, 13 blocking; NO-GO**. In particular Order's `OrderReplicationManager`, `OrderPartitionRecoveryManager`, `OrderSnapshotReplicationManager`, `OrderFailoverProofControlHandler`, `OrderPartitionLifecycleManager.markReady` and Trade's private replication/recovery/readiness remain. The four Demo harness drivers are acceptance-fixture remnants; classify separately from actual Common runtime before product release, do not mistake their continued presence for an alternate deployed business service.

## Verified candidate regression and GitHub delivery

- Order candidate `7dcccf6` (pushed to `feat/t85-common-ha-integration-20261024`): clean Maven `test` **390 tests, 0 failures/errors, 3 skipped**, 90 suites; later `package -DskipTests` PASS; compiled `OrderReplicaRepairCoordinator.class` does not exist; `OrderNoForkCommonFailoverTest` verifies Common runtime and absence of the old controller. The deleted suite tested old private member CAS and is not an HA pass; fail-closed rejoin must be implemented with **existing Common** certified recovery machinery.
- Trade `47644f4`: full Maven regression **415 tests, 0 failures/errors, 0 skipped**, 95 suites (following deletion of the private Genesis owner-CAS observer).
- Existing isolated Common/complete Demo T87 baseline: Common **476 tests / 0 failed**, Demo **251 tests / 0 failed / 1 skipped**. No Common source code was altered by T89.
- Three candidate dependency JARs SHA-256 equal: `cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3`.

## Real running Demo — old images, not the candidate

Verified that the running services still use older `local/dc-saas-ordersvr:product-matching-mode-20261020` and `local/dc-saas-tradesvr:tenant-scoped-20261019` images. Thus **NO running Demo result validates the new T89 Common adapter**. Do not enable SIGKILL during an already unhealthy market.

1. Read-only API checks: public `AdminSvr.querySymbol` plus `MDSvr.queryPublicMarket` PASS for three real tenants (`Z9BX88`, `B36KVV`, `H2FIJU`) including tenant-bound symbol list and anonymous administrative API rejection. All three returned **0 order-book entries**, so no evidence of quoting.
2. Fresh independent QA tenant `ZEUGFB` was automatically approved. Tenant admin login, custom source/product CREATE and LIST, public product discovery, tenant isolation, price-source reassignment, signed Broker API key CREATE and login all PASS.
3. The next real operation, `APSSvr.publishBrokerPrice`, returned `9000 INTERNAL_ERROR`; the test **stopped before orders/match**. Temporary QA Broker API key was deleted successfully; no broker secret stored in evidence. This is an **actual business E2E failure**, not a pass.
4. Existing Order logs show `PARTITION_NOT_READY` and `replication request failed` for OrderSvrB; several Order primary partitions report `synchronous replica forbids unverified local WAL tail rebase; use Common certified recovery before restoring READY`. Keep these safety denials in place until certified recovery installs a trusted WAL prefix. Trade partition query also intermittently rejects with `PARTITION_NOT_READY`.
5. Read-only MySQL audit found **48 tenants**, with 47 Robot state rows: **44 ERROR / 2 STOPPED / 1 STARTING**. These values are point-in-time and are not proof of an automatic Common failover.
6. Mac/Docker data disk approx. **96% used / 19–20 GiB free**; the Java memory-mapped file library logs high-disk-pressure warnings. Data cleanup must be carefully scoped to disposable Demo after a candidate is ready; do not delete forensic T82–T84 volumes.

## Remaining blockers to pass user acceptance

1. Delete/replace remaining Order and Trade private replication/writer-lease/epoch/CAS/READY implementations with existing Common APIs; retain only domain state snapshot, apply, restore and business data validation. Physical Common committed receipts must actually be wired, not substituted with Order JSON `OrderFailoverProof`.
2. Clean-build actual Order/Trade images containing exactly one correct Common JAR. Perform tests against those containers, not old Demo services; preserve business custom-product and Broker API features.
3. Stabilize Demo cold start and physical recovery: old-primary fencing, signed CommitIndex + independent custody, 256-partition READY; then robot quoting and simple maker/taker match, cancel, balance, position and MySQL Projection reconciliation.
4. Perform real A → B → A AUTO FAILOVER with SIGKILL (no script-promoted ZK state), recovery catch-up, dual readiness, no loss/double fill/split brain; measure p50/p95/p99 WAL ACK latency, TPS and RTO.
5. Extend to 10/50/200 tenant steady loads and burst only after functional/HA correctness PASS.

**Acceptance state: NO-GO.** Existing production-like Demo containers, MySQL, broker/trader data and Common forensic evidence volumes have NOT been reset, deleted, or replaced in this T89 work.
