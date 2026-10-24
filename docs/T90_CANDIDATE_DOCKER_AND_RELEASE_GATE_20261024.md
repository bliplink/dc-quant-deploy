# T90 — Order / Trade Docker candidates built, release still NO-GO

**Date:** 2026-10-24 (Asia/Shanghai). **Rule:** Existing Common + Demo verified code is the only cluster implementation. Do NOT migrate service-specific Order/Trade election, WAL, recovery, ACK, CAS, member repair, READY, or certificate code into Common; replace old service implementations with direct integration of existing Common runtime. No GitHub Actions, no destructive data reset, no unproven READY.

## Locally built ARM64 Docker images (REAL image builds)

| Image | Docker image ID | Service Git SHA | Common JAR SHA-256 |
| --- | --- | --- | --- |
| `local/otc-t90-ordersvr:common-t87-7dcccf6` | `sha256:6797ab7d6a28101c9f810ba8c25a81e080b7d4158b7fe585f602c44fffe3149f` | `7dcccf6` | `cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3` |
| `local/otc-t90-tradesvr:common-t87-47644f4` | `sha256:d7367f180fa057d72a9d53a70f5a588c13f2759aaa00c28e2919eab90acca09e` | `47644f4` | same |

The local isolated Demo candidate uses the identical Common JAR. The images are **actual Docker builds** on the user's Mac mini. The staging contexts are under `/Users/kong/.opentradingcore/t90-release-stage-20261024/`, and each build replaces **all** old service `/classes` and `/lib` directories, rather than leaving shadowed legacy classes from the prior Docker layer. The Dockerfiles verify exactly one `com.app.common` JAR, one `com.app.dc` JAR, its SHA-256, and absence of deleted old owner classes. Images carry explicit `dc.release.authorized=false` and `dc.release.gate=NO-GO` labels.

## Executed Docker container checks

- `--network none` / `--read-only` fresh `docker run` JVM classloader audits both **PASS**: `ReplicatedStateMachine`, `ZkPartitionFailoverRuntime`, and `CertifiedNodeRecoveryGate` resolve from the exact Common T87 JAR; `OrderRecoveryStateMachine` and `TradeRecoveryStateMachine` link to Common's business interface; `OrderReplicaRepairCoordinator` and `TradeCertifiedGenesisReplicaObserver` are truly absent at runtime.
- Separate disconnected application startup attempts entered Java but **did NOT establish a running service**: ephemeral smoke containers had no mounted `ATSConfig.ini` and no ZooKeeper/MySQL/network, returned start error; timeout (18s) stopped them, with no Demo access. Do NOT mark boot, business or HA PASS based on these probes.
- Reproducible binary gate: `python3 tests/verify-t90-candidate-images.py` returns candidate binary `PASS` but `release_decision=NO-GO`. `python3 tests/verify-t90-candidate-images.py --strict-release` returns **exit 2**, refusing production release.

## Blocking cluster logic still packaged in these exact images

- **Order**: `OrderReplicationManager`, `OrderPartitionRecoveryManager`, `OrderSnapshotReplicationManager`, `OrderFailoverProofControlHandler`.
- **Trade**: `TradeFailoverControlPlaneClient`, `TradeReplicationManager`, `TradeCertifiedRecoveryReceiver`.
- Additionally service `OrderPartitionLifecycleManager` / `TradePartitionLifecycleManager` call `PartitionReadinessGuard.markReady()` directly, without complete Common custody/physical-fencing certificate integration. Source release audit currently reads **21 PASS / 13 BLOCK**: 7 actual old business service code owners, 2 direct READY transitions, and 4 Demo harness-vs-Common duplication entries. Classify Demo harness independently but never lower requirements on business services.
- Existing production-like Demo itself remains **NOT HEALTHY**, with `PARTITION_NOT_READY`/uncertified WAL tails, 44 error robot rows, and independent fresh tenant Broker price publishing failure 9000 documented in T89. An unhealthy baseline is not suitable for genuine failover injection. The existing Compose services still reference previous October 19/20 images; no T90 candidate deployed live.

## Required promotion order

1. Complete Order/Trade thin business state machine adapters for **all** existing Common cluster operations, eliminate the 7 private cluster classes and both direct READY paths; re-run clean Maven regressions.
2. Build fresh binaries/images; require exactly one Common JAR SHA per image. Run both `tests/audit-single-common-core.py` (source) and `tests/verify-t90-candidate-images.py --strict-release` (Docker byte-level) to PASS. Update T90 expected image names and Common digest when a NEW candidate is built.
3. Run an **isolated realistic environment** with dedicated ZK, WAL volumes, MySQL/business dependencies, complete configuration and real two-way physical Common certificates, then register fresh QA tenant and achieve deposit/limit/match/cancel/account/position/Projection consistency.
4. Inject real SIGKILL A→B→A during active trading. Reject double primary, unverified READY, WAL mismatch, lost ACKs, duplicate executions; quantify RTO, ACK p50/p95/p99 and TPS.
5. Only after the above gates, update actual Demo Compose image references with a preserved rollback configuration and monitored business cutover. Then test 10/50/200 tenants and burst.

**T90 verdict: candidate Docker images installed locally; production/demo service rollout NOT EXECUTED, release NO-GO**. No MySQL drop, live deployment change, Docker data/volume prune, or GitHub Actions used. Existing Common T82/T84 forensic volumes and the running Demo remain untouched by this candidate preparation.
