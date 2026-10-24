# Common single-engine convergence — T87 (2026-10-24)

## Non-negotiable architecture

**Demo, OrderSvr and TradeSvr MUST invoke the same Common cluster implementation.** Common exclusively owns node leases, assignment/epoch CAS, failure detection, replica placement, TCP WAL, commit certificates, independently signed physical custody, recovery, archiving, old-primary fencing, ACK modes and READY publication. A business service only supplies the `ReplicatedStateMachine` contract (`apply`, `snapshot`, `restore`, `finishReplay`) and domain-specific state validation. No alternative Order-, Trade-, or Demo-owned HA controller is an acceptable fallback. The Gateway remains transparent.

## Source changes completed

| Repo | Feature branch | Candidate source commit | Change |
| --- | --- | --- | --- |
| `bliplink/com.app.common` | `feat/common-t82-certified-custody-20261024` | `5ce1b3a` | Common RF2 `RECOVERING` transition; authenticated physical recovery receipts; imports missing Demo-only planned transition, membership stability, epoch fence, buddy placement, epoch commit barrier and crash-safe archive resume interfaces |
| `bliplink/com.app.dc` | `feat/t85-common-ha-integration-20261024` | `ec07c26` | Private candidate Common `3.0.22-t87-singlecore-20261024-SNAPSHOT` dependency and `com.app.dc 0.0.5-t87-singlecore-20261024-SNAPSHOT` |
| `bliplink/com.app.dc.ordersvr` | `feat/t85-common-ha-integration-20261024` | `ee3746b` | Add `OrderRecoveryStateMachine` business adapter; Common RF2 nonroutable transition in automatic failover; pin candidate `com.app.dc` |
| `bliplink/com.app.dc.tradesvr` | `feat/t85-common-ha-integration-20261024` | `e1ae1ac` | Delete service-owned `TradeFailoverController` automatic election loop and `TradeFailoverAssignmentTransition` READY constructor; bind `TradeStart` to Common `ZkPartitionFailoverRuntime`; business snapshot/commit proof as callback; pin candidate `com.app.dc` |

The isolated Demo source candidate is compiled **from source** using the same Common Maven artifact. The original T84 precompiled `/tmp/v19` harness is NOT sufficient evidence of this parity. The T87 Demo source candidate is not yet a merged/released product.

## One exact Common JAR

Common GAV (private candidate): `io.github.bliplink:com.app.common:3.0.22-t87-singlecore-20261024-SNAPSHOT`.

Exact Common JAR SHA-256 in **all three candidates** (Demo Maven dependency, Order image dependency directory, Trade image dependency directory):

`cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3`

Order/Trade were clean-packaged after regression; their image dependency directories contain exactly ONE Common JAR, exactly ONE `com.app.dc` candidate and MySQL Connector/J 8.0.33 (not 5.x). This is binary parity only, **not** proof of runtime/behavior parity.

## Local test results

| Candidate | Total tests | Failures | Skipped | Result |
| --- | ---: | ---: | ---: | --- |
| Common | 476 | 0 | 0 | PASS |
| Demo from complete source | 251 | 0 | 1 | PASS with one skip |
| Order | 398 | 0 | 3 | PASS with three skips |
| Trade | 436 | 0 | 0 | PASS |

Tests were run locally on Java 8 with Maven; **no GitHub Actions** or central Maven release were used. Isolated candidate version coordinates require the locally built Common JAR to be installed before building `com.app.dc` and then Order/Trade. They are NOT public Maven Central coordinates.

## Strict deployment gate: NO-GO (16 unresolved findings)

Run the read-only `tests/audit-single-common-core.py` against the five source roots and the exact Demo Common JAR. It verifies required Common APIs, three business adapters, identical binary hashes, and rejects known service-owned authority. Current output: **18 PASS, 16 BLOCKING => NO-GO**.

Remaining **Demo** cluster authority classes that belong in Common: `DemoV19SafeTakeover`, `DemoV19Rf2StrictAckRuntime`, `DemoV19DurableRuntime`, `DemoV19NodeGrantBridge`.

Remaining **Order** cluster implementations: `OrderReplicationManager`, `OrderReplicaRepairCoordinator`, `OrderPartitionRecoveryManager`, `OrderSnapshotReplicationManager`, `OrderFailoverProofControlHandler`. `OrderReplicaRepairCoordinator` still performs service-owned assignment CAS, and `OrderPartitionLifecycleManager` still invokes `PartitionReadinessGuard.markReady` outside the unified certified Common authority. `OrderRecoveryStateMachine` is implemented and tested but not yet the exclusive live recovery path.

Remaining **Trade** cluster implementations: `TradeFailoverControlPlaneClient` (still used for evidence and source-side CAS), `TradeReplicationManager`, `TradeCertifiedRecoveryReceiver`; `TradeCertifiedGenesisReplicaObserver` still performs direct assignment CAS on planned handoff, and `TradePartitionLifecycleManager` still invokes service-owned `PartitionReadinessGuard.markReady`. Business code must call Common operations, not replace them with renamed local copies.

No static audit replaces live failover proof: **all 16 blockers and any additional reachability found in source must be removed**, and Common certified READY must be exercised in the actual product, not a test fake. Removal must preserve business `apply/snapshot/restore` behavior and physical committed WAL lineage.

## Acceptance required before disposable Demo reset and deployment

1. Migrate the remaining Demo/Order/Trade cluster authority into Common and remove the reachable legacy implementations; satisfy the strict static gate with one immutable Common JAR.
2. Build real ARM64 Order/Trade runtime containers from clean dependency directories; prove every image carries the *same* Common SHA, with no stale duplicate JAR. Leave Gateway as passthrough.
3. Run physically separate-JVM Common control and Netty data tests; true double custody, cross-JVM old-epoch revocation, no READY prior to signed physical watermark/fencing proof; A→B→A and rejoin under ongoing writes.
4. Only after the above is successful: explicitly reset the disposable Demo business data (with scoped backup of retained evidence) and redeploy all services locally, register a fresh tenant, automatic approval/robot, create users/API keys, deposit, place/cancel/match, positions, trades and projection consistency.
5. Reconcile Order/Trade state, MySQL balances/positions/orders/executions and Projection watermark; measure P50/P95/P99, TPS, RTO and repeat at 10/50/200 tenants with 2–3x burst.

## Production/Demo status at T87

**No existing `dc-saas` Demo containers have been replaced.** No MySQL or user/trading data was cleared; no T82–T84 evidence volume deleted; no fresh tenant was created in this T87 migration. T84 isolated pass is NOT full product HA pass. The original Mac disk is about 96% used (roughly 21 GiB available); a 150 GiB business reset must be scoped to the disposable Demo only and timed after the candidate passes readiness gates. Full business HA is **NO-GO**.

## 2026-10-24 follow-up: confirmed immutable Common+Demo source baseline

**Explicit architecture decision:** Existing Common+Demo implementation validated in the prior isolation tests is the sole source of cluster logic. **Do not port any Order/Trade clustering algorithm or authority code into Common.** This supersedes attempts to adapt the service-owned replica repair/promotion code into Common. Where a service has bespoke election/replication/recovery/READY, DELETE the bespoke implementation and connect the service's business `apply/snapshot/restore` callbacks to an **already existing** Common engine interface. Reuse verified Common classes; do not create a new `OrderCommonXXX` or `TradeCommonXXX` copy of a control algorithm.

The uncommitted experimental `PartitionReplicaRepairController` addition and modified planned handoff code have been **reverted** from Common; Order changes dependent on this new API have also been reverted. Common `feat/common-t82-certified-custody-20261024` at `5ce1b3a` remains clean and unchanged; a clean Maven package has confirmed no experimental repair-controller class. All T88 local candidate POM changes were rolled back to T87. The later isolated Trade commit `47644f4` **removed** its 274-line `TradeCertifiedGenesisReplicaObserver` source-owned ZooKeeper CAS loop and startup reference; full Trade test suite passed (415 tests, 0 failed). No Common changes accompanied that Trade removal.

The release gate after this correction is **19 PASS / 15 BLOCK => NO-GO**. The remaining blocker list must be treated as service/harness code still needing removal/rebinding to existing Common APIs. A missing Common API is a reportable integration blocker, **not permission to transplant the old service cluster logic**. Do not promote Order/Trade, enable old failover sidecars as fallback, or reset/redeploy Demo until real existing-Common wiring and physical business failover pass. The current Demo remains untouched; the T82–T84 evidence and user data remain intact.
