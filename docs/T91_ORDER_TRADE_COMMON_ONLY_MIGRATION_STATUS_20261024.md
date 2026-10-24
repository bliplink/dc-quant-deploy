# T91 — Order/Trade Common-only migration, actual code changes and release verification

2026-10-24, local Mac mini; do not conflate isolated Common+Demo HA evidence with real Order/Trade HA.

## User requirement

There must be exactly one cluster engine: **the ALREADY tested Common engine**. Order/Trade retain business functions, `apply`, `snapshot`, `restore`, `finishReplay` only. Do **not** port either service's old election, replication, ZK CAS, WAL, READY, snapshot transport, custody or recovery algorithms into Common. All service-side older cluster authorities must be removed; existing Common must own and validate *physical* proofs. Deploy new Order/Trade images only after integration and actual HA data proofs succeed.

## Executed code deletion and local tests

- Common branch HEAD `5ce1b3a` unchanged. No code port from business service to Common.
- Order branch `feat/t85-common-ha-integration-20261024`, HEAD `6de3daf` pushed to GitHub; deletes service-owned `OrderFailoverProofControlHandler.java` and `OrderFailoverProofProvider.java`, including JSON `FAILOVER_PROOF`/`LEARNER_PROOF` RPC responses and tests. Router now rejects these operations `UNSAFE` without forwarding; old `OrderReplicationManager.queryFailoverProof/queryLearnerProof` always fail closed, and the old fallback replication-control handler is gone. Only Common authenticated/certified recovery control operations remain eligible. No fake WAL/Custody certificates.
- The previous T89 commit `7dcccf6` removed `OrderReplicaRepairCoordinator` and its private ZK membership-CAS scheduler. No other legacy cluster algorithm was moved into Common.
- Order tests after this removal: **392 tests, zero failures/errors, 3 skipped, 91 suites**; Maven offline `clean package -DskipTests` PASS; clean compiled output has **no** `OrderReplicaRepairCoordinator`, `OrderFailoverProofProvider`, or `OrderFailoverProofControlHandler` class files.
- Trade previous `47644f4` removed its independent Genesis observer/CAS. Regression baseline: **415 tests, zero failures/errors, 0 skipped, 95 suites**. Trade source not otherwise changed in T91.

## Actual rebuilt Linux ARM64 Docker images (not deployed live)

| Service | Local Docker image | Full image id |
| --- | --- | --- |
| Order | `local/otc-t91-ordersvr:common-t87-6de3daf` | `sha256:ca1bc54ff945fd5e84d68fc32fe7e49e47babac3418f3083f4eaa28927eeeb6d` |
| Trade | `local/otc-t91-tradesvr:common-t87-47644f4` | `sha256:ade40a733360ff6170c51c9ee2ab51d08d82b8c2e5ca511c3414c54caa1114d3` |

Both image builds replace all old `classes/` and `lib/` from base layers. One matching Common Jar per image, SHA-256 `cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3`; old signed/unsigned service-owned classes absent as checked with `RUN` instructions. Images are tagged `dc.release.authorized=false` and `dc.release.gate=NO-GO` deliberately. No GitHub Actions used.

`python3 tests/verify-t90-candidate-images.py` has been updated to T91 images and all three removed Order classes. On **real Docker images** it yields `artifact_preflight=PASS` but `release_decision=NO-GO`. `--strict-release` exits **2**, refusing deployment. Latest source static audit `NO-GO: 22 passed, 12 blocking` (improved from T90 21/13).

## Exact remaining blockers

- Order still owns `OrderReplicationManager`, `OrderPartitionRecoveryManager`, `OrderSnapshotReplicationManager`, and `OrderPartitionLifecycleManager.markReady()`. It still has an old read-only `OrderFailoverPromotionSafety` validation flow which will now fail closed because the legacy JSON proof source was removed. Its functionality must be replaced by **existing** Common physical custody/WAL/epoch verification and business-only callbacks.
- Trade still owns `TradeFailoverControlPlaneClient`, `TradeReplicationManager`, `TradeCertifiedRecoveryReceiver`, and `TradePartitionLifecycleManager.markReady()`. The enormous service-specific `TradeStateCoordinator` owns legacy failover/degraded ACK decisions and still needs to call Common authority, not self-authorize.
- Four isolated `DemoV19*` harness source owners remain flagged for review. Do not confuse its historical success with live Trade/Order ready certification.
- The Common business `ReplicatedStateMachine` adapters exist (`OrderRecoveryStateMachine`, `TradeRecoveryStateMachine`) but are not the sole ACTIVE hot-path cluster controller in either business service. A business adapter linking to Common is not the same as integrated custody/READY.
- Last genuine Demo E2E had a failure at APS broker price publishing `9000 INTERNAL_ERROR`; existing Order/Trade old-image cluster exhibits numerous `PARTITION_NOT_READY` failures and Robot ERROR. Mac disk >95% full. These issues have NOT been fixed by static migration.

## Release gate and next technical steps

1. Remove four remaining Order private owners and three Trade private owners from actual hot paths **only while replacing them with working existing Common** APIs; ensure no shadow replication bypass or lose-ACK fallback. Bind the exact same Common state machine recovery runtime as Demo with real fenced physical CommitIndex+Custody attestation and per-partition write admission.
2. Remove both service-local READY writes; Common must authorize READY after physical old-owner revocation, signed WAL/custody, full `snapshot + committed replay`, business consistent restore and reliable Projection watermark.
3. Full clean compilation/tests, new ARM64 images with the one Common SHA, static audit PASS and image gate `--strict-release` PASS.
4. Deploy isolated realistic Order/Trade first with explicit configs + dedicated ZK/MySQL; new QA tenant, deposits, limit/match, cancel, positions, balances, MySQL/Projection authority. Rebuild/deploy actual live Demo with rollback only after these pass. Real continuous-trading SIGKILL A→B→A and catch-up are last decisive HA acceptance; report p50/p95/p99, RTO and 10/50/200 tenant load.

**T91 outcome: Real code removed, rebuilt both images and verified binary parity. NOT deployed into live Demo; FUNCTIONAL/HA NO-GO.** Running Compose containers, MySQL, prior Common forensic evidence/WAL and tenant data were not reset/deleted/replaced.
