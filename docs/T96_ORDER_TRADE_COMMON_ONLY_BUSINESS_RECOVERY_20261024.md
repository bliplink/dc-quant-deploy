# T96 — Order/Trade Common-only business state integration and verified release block

**Date:** 2026-10-24, local Mac mini. **Common** remains commit `5ce1b3a` (`feat/common-t82-certified-custody-20261024`). No Order/Trade election, WAL, ACK, repair or recovery algorithm was moved into Common. No GitHub Actions.

## Source changes already pushed

| Service | Git branch | Latest commit | Business code |
|---|---|---|---|
| Order | `feat/t93-order-common-only-delete-20261024` | `422de4e` | Removed 31 private HA classes; 15 domain classes moved to `com.app.dc.service.state`; added `OrderCommonRecoveryBinding` and Common-authoritative business-image capture |
| Trade | `feat/t92-trade-common-only-delete-20261024` | `9bff3b4` | Removed 43 private HA classes; 21 domain classes moved to `com.app.dc.service.state`; added `TradeCommonRecoveryBinding` and balances/positions/config/orders/dedupe business-image capture |

Both now have **zero** Java sources and **zero** compiled classes under `com.app.dc.service.cluster`. Other business handlers/strategies retain their matching/financial code and call the service `state` package. Business states implement **the exact Common** `ReplicatedStateMachine` byte interface; `PartitionStateMachineRegistry` and `StateMachineRecoveryCoordinator.recover()` are the *existing* Common implementation called by the new thin business bindings. Tests reject wrong-partition registration and missing authenticated Common `Control`, and verify Common image capture is domain-only.

**This is not yet the complete runtime integration.** No binding has been wired to a live Common physical transport/certificate writer and cluster startup; the business `ClusterAdapter` *explicitly throws* if cluster mode is enabled without those dependencies. The `OrderSnapshotManager.capturePartition(String)` unauthenticated entry point still refuses; Common-exclusive business-image capture has been added separately. Trade snapshot production only runs when injected with `TradeBusinessSnapshotCapture`; the default unauthenticated constructor refuses. These protections are intentionally fail-closed; do not bypass them or mark READY from Order/Trade.

## Clean local regression (not HA fault-injection)

| Result | Order | Trade |
|---|---:|---:|
| Fresh Maven `clean test` suites | 47 | 47 |
| Tests | 146 | 172 |
| Errors/failures | 0 | 0 |
| Skipped | 2 | 0 |

The old tests for deleted service-local HA engines were deleted, so reduced counts are **not evidence of coverage of the Common engine in live business services**. The Common+isolated-Demo acceptance is a separate historical baseline, not a proxy for this live integration.

## Actual Docker images built on Mac mini

| Image | Full Docker ID |
|---|---|
| `local/otc-t96-ordersvr:common-only-422de4e` | `sha256:02a6fd539b812fe74327df97800cdeae3dccad556c8a681005319a2b01692dc9` |
| `local/otc-t96-tradesvr:common-only-9bff3b4` | `sha256:6729eead8435c056f701db6c9f62bd66aadd58cd4c68980d78da1184c2d61433` |

Both images replace the inherited `/classes` and `/lib` directories, have exactly one Common JAR, and verify its SHA-256 is **`cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3`**. Both are Linux ARM64 and remain **`dc.release.authorized=false`**. Each was exercised in a fresh Docker JVM with `--network none --read-only`: actual `NodeClusterControlManager`, Common state registry, coordinator and `ReplicatedStateMachine` resolve from the exact Common JAR, the domain recovery binding resolves, and legacy service cluster owner classes cannot be loaded. This checks binary linkage, NOT startup, trading or HA.

## Explicit real release gate

`python3 tests/audit-single-common-core.py [args used in T94]`: **30 PASS / 8 BLOCK / NO-GO**. Four blocks are unfinished Common production durability/snapshot bindings (Order and Trade), four blocks are duplicate historical Demo harness classes pending cleanup/classification. These are source heuristics, not an executable end-to-end HA test.

`python3 tests/verify-t94-common-only-images.py`: `artifact_binary_validation=PASS`, `release_decision=NO-GO` on the two **actual T96 images**. `python3 tests/verify-t94-common-only-images.py --strict-release` **exits 2** and blocks live release. It checks absent old cluster classes, SHA, source revision, recovered business adapter classes, explicit missing-WAL/snapshot path and unverified HA release labels.

**No Demo Docker services were replaced.** Running services still use old Order 2026-10-20 and Trade 2026-10-19 images. There was no SIGKILL, data reset, role CAS, manual READY, live trading or Projection acceptance in this T96 turn. Disk approx. 81 GiB free (82% used); no WAL or forensic evidence deleted. Prior Demo has `PARTITION_NOT_READY`, Robot ERROR, and a failed APS Broker price end-to-end step; these remain unverified/unfixed.

## Concrete next execution requirements

1. **Use existing Common as the ONLY production WAL writer and physical certificate custodian.** Install one authenticated node control plane and a `NodeClusterControlManager` per node; bind `DurableWalGroupCommit`/Netty, `DurableWalCommitIndex`, independent custody quorum and Common's strict ACK evidence to actual Order/Trade business mutation boundaries, including partial failures and zero-double-write admission. No old-service implementation or per-record ZK calls.
2. **Use Common exclusively for image authority and recovery READY.** Bind Common-exclusive capture barrier, committed WAL source, signed snapshot/CommitIndex/custody, fenced owner transition, business restore `finishReplay`, and independent Projection reconciliation before READY. The domain capture methods implemented here do not themselves certify snapshots.
3. **Run real isolated multi-JVM integration** with proper server config, dedicated ZooKeeper and MySQL, real broker/trader API keys; verify fresh tenant, funding, maker/taker fills, cancel, balance/position/Projection, full recovery; `SIGKILL A→B→A` automatic promotion under active trading with signed custody, replica rejoin, no loss/double fill/split-brain, WAL ACK p50/p95/p99 and RTO.
4. Only then promote and replace Demo Compose images with rollback plan; proceed to 10/50/200 tenant load, burst and archive retention tests. Continue local compilation, **no GitHub Actions**.

**T96 verdict:** Source deletion and Common business recovery/snapshot interface progress **PASS**; live Order/Trade Common-only HA and deployment **NO-GO**. This report is not a release authorization.
