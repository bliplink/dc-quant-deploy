# T107 — from-zero Order/Trade partition reset plan and real Common-owned WAL implementation

**2026-10-25 / Mac mini. User authorized discarding old Demo partitions and trading data and restarting.** That permission removes the requirement to recover legacy Order/Trade WAL tails; it does not authorize fabricated READY certificates or unsafe writing before a correct Common ACK. **Result: Common fresh-storage integration PASS; actual new Order/Trade business deployment still NO-GO. No original Demo volumes deleted yet.**

## Implemented (code pushed)

`com.app.common` SHA `836ba39` adds **`CommonFileBusinessWal`** in Common itself, not in Order, Trade or a separate competing cluster implementation. This is the reusable byte[] physical-storage adapter passed into Common's already existing `DirectNettyCertifiedBusinessTransport`, `DurableWalGroupCommit`, signed `DurableWalCommitQuorum`, `DurableWalCommitIndex`, dual signed `DurableWalCertificateCustody` and strict ACK. It owns only file framing, epoch+sequence contiguity, physical `FileChannel.force(true)`, bounded records, CRC checks, deterministic SHA-256 physical prefix, writer file lock and raw bytes recovery. It has **no local election, no READY operation, no unsigned client-ACK and no business-state apply**. It refuses damaged/truncated WAL tails, old-Epoch data, concurrent writers and WAL heads that disagree with certified CommitIndex. Exact-head TCP retransmission after lost reply is idempotent and re-signs without appending a duplicate. Mismatched bytes reject. Incremental cached prefix hash and most recent fsynced command avoid repeated full-history file hashing/scanning in the hot path.

Fresh service Maven version coordinates:

| Component | Branch | SHA | Fresh regressions |
| --- | --- | --- | --- |
| Common | `feat/common-t82-certified-custody-20261024` | `836ba39` | **486 tests, 0 failures, 0 skips** |
| shared `com.app.dc` | `feat/t85-common-ha-integration-20261024` | `812520b` | Pin Common T107; locally installed |
| Order | `feat/t93-order-common-only-delete-20261024` | `f47be93` | **166 tests, 0 failures, 2 skipped** |
| Trade | `feat/t92-trade-common-only-delete-20261024` | `03d7f6b` | **190 tests, 0 failures, 0 skips** |

Single Common artifact `3.0.22-t107-fresh-wal-20261025-SNAPSHOT` SHA-256 `d70b08f34438c4399c39ea7eb6f29af990b570e3fd13e11681305f7c40336ae0`. Single shared DC artifact `0.0.5-t107-fresh-wal-20261025-SNAPSHOT` SHA-256 `a704ff0c563c0716e37ec15d1acbb36dd7bdc408431a19d496b28766cbb2acbe`. Both service Maven packages and Docker images contain exactly these artifacts. No GitHub Actions, no Maven Central publication, no RSA generation.

## Local ARM64 candidate images

| Candidate | Actual Docker image ID |
| --- | --- |
| `local/otc-t107-ordersvr:fresh-common-f47be93` | `sha256:4bd08c07907e34e8173ab908a396223e2906da081233c0030f25b9ce48d27d50` |
| `local/otc-t107-tradesvr:fresh-common-03d7f6b` | `sha256:76af668015908f1941fb735764db407d528773ec24783bdf1c530ca540d595ea` |

No old `com.app.dc.service.cluster` classes, no baked RSA private keys. Existing Demo RSA A/B keys mounted `:ro` inside isolated Docker test; private host path is deliberately **not included in this public report**. `tests/verify-t107-fresh-common-business-images.py` returns binary `PASS`, strict release `NO-GO` / exit **2** with 12 explicit blockers. Image release labels remain `dc.release.authorized=false`.

## Tests of actual new Common WAL vs old disposable probe storage

- `CommonFileBusinessWalTest` 4/4 PASS: new/empty WAL, physically forced original bytes, re-open exact recorded sequence, refuse uncertified dirty append tail, refuse partial frames or old Epoch, signed B replica ACK using existing Demo RSA, exact duplicate accepted without another write, mismatched same-sequence TCP message rejected.
- New `tests/t107/T107FreshWalTwoJvmProbe.java` replaces the old T106 disposable `FileWal` class in the two-Docker-JVM probe with the **actual Common `CommonFileBusinessWal` implementation**. `tests/t107/run-fresh-wal-two-jvm.sh` starts two separate Docker JVMs in an internal Docker network, independently mounts original Demo RSA A and B read-only, creates **empty test volumes** and verifies real Netty TCP physical record replication, dual on-disk custody, signed CommitIndex and independently verifiable client ACK.
- **12/12 actual physical Common WAL commits PASS**, two JVMs, single Mac; final exact A/B WAL SHA matches. Measured sequential strict ACK samples (small pilot only): p50 `108.872 ms`, p95/p99 `1793.642 ms`. **Performance target 5–10 ms NOT met.** Multi-node batching and certificate fsync amortization remain mandatory. Test containers/private network cleaned; data evidence kept.
- Preliminary fresh *actual business image startup preflight* mounted **empty data directories** and existing control/config in `--network none`. Neither Order nor Trade could reach dependencies (connection refused) within the bounded boot period. This is an intentionally **isolated connectivity negative test**, **NOT successful Order/Trade startup and NOT proof about restored business readiness**. Only test-specific data directories were touched.

## Explicit reset/redeployment policy authorized by the user

Existing Demo host data root contains roughly **155 GiB**:

- `OrderSvrA` ~48 GiB, `OrderSvrB` ~48 GiB, `OrderSvrC` near-empty.
- `TradeSvrA` ~3 GiB, `TradeSvrB` ~3 GiB.
- `mysql` ~49 GiB, `clickhouse` ~3.3 GiB; others MD/APS/ZK. Existing logs ~9.1 GiB.

The old Order/Trade partition WAL/snapshot/business data and obsolete ZK partition states **may be discarded** at actual verified cutover; there is no need to preserve/repair them for backward compatibility. However on the present T107 candidate the main `OrderClusterAdapter.init()` and `TradeClusterAdapter.init()` still **deliberately fail closed** because the per-partition physical Common writer/epoch authorization/recovery/READY dependencies are not yet genuinely installed in Spring. Wiping active data and replacing the live containers now would only break the public Demo with no capable service to accept orders. Therefore **do not delete active host data or DB** before the new fresh topology boots and certifies. Preserve shared Demo RSA keys, source/repos, connection credentials, and all third-party volumes not covered by the reset. No host private key contents/paths should enter version control.

## Concrete missing production integration

1. Install Common's new `CommonFileBusinessWal` with **per-partition file/lock** through the real Common `DirectNettyCertifiedBusinessTransport.PhysicalLocalWal` interface and shared service-scoped `DirectNettyReplicationServer`. Each signed replica callback must use Common's physical durable `receiveReplicated()` and current Common node grant, not a service-specific replication implementation.
2. Resolve service node assignments and physical voter identity from the actual trusted Common ZK member manifest, explicitly bind old Epoch/certified Genesis/fenced Primary with Common ZK node-scoped CAS and *existing* Demo RSA keys; no automatic fabricated membership/READY.
3. Inject real `CertifiedBusinessCommandRegistry` in Order and Trade **only for installed and authenticated partitions**. Before enabling live traffic, fix every mutate-then-record order/cancel/matching/fill/balance/position path to stage full state effects before Common strict physical commit and publish only after ACK. Existing safety guard remains ON for now.
4. After certified snapshot install/READY, use **a fresh isolated real service stack** (3 ZK voters, Order A/B, Trade A/B, MySQL/Projection, MD/API/Robot) to perform actual account cash-in, limit/maker/taker match, fill/cancel, balance and position consistency, repeated **automatic A→B→A SIGKILL**, stable watermark reconciliation, then 10/50/200 tenants and 2–3x burst. Measure RTO, TPS, p50/p95/p99 latency, reject duplicates and split brain. Only after this test can fresh Demo Compose be cut over and old partition directories reset.

**Verdict:** New Common shared physical WAL correctness and two-JVM transport certificate custody **PASS**. Fresh Order/Trade actual service deployment, real financial data consistency, automatic failover, strict ACK latency SLO **NOT PASS / release NO-GO**. No GitHub Actions used.
