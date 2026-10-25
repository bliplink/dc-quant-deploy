# T106 — Common real signed Netty WAN/LAN WAL + dual disk custody; two Docker JVMs, precise release boundary

**2026-10-25 (Mac mini, local builds; no GitHub Actions). Status: verified Common physical TCP building block PASS; actual Order/Trade live trading, snapshot READY and automatic HA remain `NO-GO`.** Do not swap production-like Demo images based on these transport probes.

## 1. Production Common code changes (existing primitives composed, no extra Order/Trade HA)

- Add `DirectNettyCertifiedBusinessTransport` in `com.app.common.replication`: one authenticated Common per-partition/epoch writer may use **existing** `DirectNettyReplicationTransport`, `ReplicationBatch`, RSA `DurableWalBatchAckProof`, `DurableWalReceiptControlHandler`, `DurableWalCertificateCustodyControlHandler`, `DurableWalCommitQuorum` and `DurableWalCustodyQuorum` to obtain independent physical WAL fsync receipts followed by independently fsynced certificate custody receipts. It injects the real physical disk writer as a required `PhysicalLocalWal` dependency; does NOT invent a WAL storage codec, election or control-plane algorithm.
- Strict client ACK remains owned by Common's `CertifiedBusinessCommandBoundary`, including authenticated local grant, disk and quorum index fsync, majority Custody receipt ledger, and final grant check. The new adapter makes TCP/actual physical evidence available to this existing boundary. A replica `ReplicationAck.OK` with no independently verified RSA evidence is rejected. No unrestricted local-only fallback exists in strict mode.
- **Crash-safety fix**: if restart sees a persisted CommitIndex sequence greater than zero, it must revalidate the **same physically fsynced WAL and recovered majority-signed custody receipt ledger** before creating a writable business command boundary. A crash between CommitIndex fsync and majority Custody publication is rejected, regardless of the WAL prefix being present.
- **Order safety fix**: existing OrderManager paths that mutate the live book before recording a state journal now fail **before mutation** when Common HA is enabled. `OrderStateJournal.requireStagedBeforeMutation()` is not a workaround for those transactions; the real durable prepared-command and staged-before-apply business paths still need to be installed for trading to resume. The already-existing `AbstractStrategy.processWalFirstBatch` staging path cannot be enabled yet because its cluster batch binder remains unconnected.
- Trade's mutable business paths are still fail-closed by `TradeStateCoordinator.requireWritable()` pending staged account/position/fill transaction integration. Do NOT bypass either business guard.

## 2. GitHub revisions and tests

| Component | Git branch | Commit | Last fully clean regression |
| --- | --- | --- | --- |
| Common | `feat/common-t82-certified-custody-20261024` | `dc01cec` | **482 tests, 0 failures, 0 skipped** |
| shared `com.app.dc` | `feat/t85-common-ha-integration-20261024` | `4020a42` | T105 baseline 41 passing; T106 version updated and installed locally |
| Order | `feat/t93-order-common-only-delete-20261024` | `ea14593` | **166 tests, 0 failures, 2 skipped** |
| Trade | `feat/t92-trade-common-only-delete-20261024` | `dff73f8` | **190 tests, 0 failures, 0 skipped** |

Common T106 existing Maven artifact: `io.github.bliplink:com.app.common:3.0.22-t106-netty-business-20261025-SNAPSHOT`, SHA-256 `6554624b8c932bae783389df31fae39cdedfeb685b3cd172726dbc24998273e8`.

Shared DC artifact: `io.github.bliplink:com.app.dc:0.0.5-t106-netty-business-20261025-SNAPSHOT`, SHA-256 `bdaa22452cbea569cec9d2eebc4faec968e23ed6b1148f36d6abfca943f51740`. Both actual Docker images contain the exact same two jars, no service-private HA source/class directory, no private key files. All source pushed; local Maven was used (no Maven Central or GitHub Actions release).

## 3. Positive and negative real network tests

### Common real Netty loopback (different WAL/custody files, same JVM)

Common `CertifiedBusinessCommandBoundaryTest`: 6 cases, all PASS and no skips using **previously created** Demo RSA A/B. Cases include real `FileChannel.force(true)` local+replica WAL, Netty signed ACK, authenticated `DurableWalCommitIndex`, independent `DurableWalCertificateCustody`, and fsynced dual-custody receipt ledger. Cases refuse an absent signed WAL receipt, refuse missing B certificate custody despite a valid signed WAL certificate, and reject old on-disk CommitIndex recovery when quorum Custody proof is missing. Any uncertain state poisons the writer.

### Two genuinely separate Docker JVMs / actual TCP, independent container data dirs

Two actual ARM64 candidate images executed separate Java processes on an **internal-only Docker network**. This is an integration PROBE deployed *inside* the business images, not real Order/Trade Spring business service startup, and not an automatic election:

| Node | Image | Actual image ID |
| --- | --- | --- |
| A client JVM in Order candidate | `local/otc-t106-ordersvr:common-netty-ea14593` | `sha256:65efcc4dbab2db5dba7b787e30889f7f30974064621f5966812de7932c38bf50` |
| B durable replica JVM in Trade candidate | `local/otc-t106-tradesvr:common-netty-dff73f8` | `sha256:3fc148d6777140b88f0c2967319af0ba72dc3f179d938a90022e9c922261dc93` |

The tester mounted pre-existing Demo `CommonHaDemoA` and `CommonHaDemoB` RSA private directories **read-only**, with shared existing public trust **read-only**, and used separate persistent A/B test WAL+custody volumes. No keys generated or copied to images, no public GitHub paths to private key material. A uses Common Netty TCP replication to B; B fsyncs actual WAL bytes before a signed receipt; A persists certificate; B installs the signed certificate on its disk; A stores verified dual-custody ledger and only then returns authenticated strict ACK.

- First two-container smoke: **2/2 certified ACK** PASS, B certificate persisted, A/B physical WAL bytes match.
- Extended sequential test: **30/30 certified ACK** PASS, Common CommitIndex/Custody reached sequence 30; independent A/B WAL file SHA-256 EXACT match: `13f0d6a09500793695ebb4080b839f81409a3994e6d66b04b302a423ed9b9b02`.
- The reproducible `tests/t106/run-two-jvm.sh` was corrected for Docker Desktop host-mounted class compilation and then itself **executed successfully**, including explicit A/B WAL SHA check and no key creation. It takes RSA and local artifact paths from environment variables, never hardcodes or logs the private host-key path. New isolated test containers and networks were destroyed, but A/B test evidence data volumes were retained.
- The previous T106 image-byte gate was updated to `tests/verify-t106-real-netty-business-images.py`; **binary PASS**, explicit **`NO-GO` / `--strict-release` exit 2**, 12 blockers. Production images remain `dc.release.authorized=false`.

**Critical limitation:** RSA node A and B run in two different Docker JVMs, but both Docker processes and WAL files ultimately reside on the **same Mac mini**. Artificial membership host labels in this isolated test are only logical namespaces, not independent physical hardware. This test does **not** prove survival of machine failure or real cross-host quorum, and it grants NO production READY.

## 4. Measured sequential strict ACK latency — NOT acceptable against target

30 isolated same-Mac sequential single-record physical commits, timed *inside A's Java process* (these include disk commit-index fsync, remote TCP WAL fsync, local+remote certificate custody and fsynced receipt ledger). **Not 200-tenant workload, not per-partition throughput benchmark, not steady-state multi-host production metrics.**

| Metric | Measured |
| --- | ---: |
| p50 | **98.182 ms** |
| p95 | **235.344 ms** |
| p99 | **1,581.086 ms** |
| Sample size | 30 sequential successful strict commits |

All succeeded but latency significantly misses the user's **5–10 ms / WAL** target. A first-request connection/initialization cost likely affects the p99 in such a small sample; do not infer exact cause or a production figure from this isolated run. Source is the retained `t106-30commit-latency.log` on Mac. Proposed subsequent optimization must preserve signed Common evidence: use `DurableWalGroupCommit` groups (up to 64) and existing cumulative `DurableWalCommitIndex.certifyAndPersistBatch`/batch verified ACK to amortize Netty and multiple fsyncs. Do **not** eliminate certificates, hide timeouts, or restore ZK RPCs to WAL hot path.

## 5. What prevents real Order/Trade Demo release and automatic A↔B

1. Install a real **per-partition `DirectNettyCertifiedBusinessTransport.PhysicalLocalWal`** from the already-validated Demo WAL storage semantics under Common, and real Netty handlers on all Order/Trade A/B members. The T106 harness contains only disposable test disk storage and is NOT an approved production WAL implementation. No service-private WAL or cluster authority allowed.
2. Install **certified membership, physical RSA signer, old-epoch fencing, recovery and authenticated READY** from existing Common/ZK onto each actual Order/Trade business partition. No synthetic physical-host labels or unverified original certificates.
3. Finish **Order prepare-before-apply and Trade balance/position/fill atomicity**: no live business state before strict physical commit, committed original journal replay format, no loss/duplicate trade or ledger post; preserve Projection watermark consistency. Existing startup fail-close remains mandatory.
4. Start real Order/Trade JVMs with isolated ZK quorum, MySQL, MD, Projection, APS/API, Robot maker/taker, and run actual tenant registration, cash-in/out, order/match/cancel, funds/positions/executions reconciliation. Inject **real SIGKILL primary**; Common elects/revokes/rejoins automatically, A→B→A, no script-triggered READY; then 10/50/200 tenant steady load and 2–3x burst with ACK p50/p95/p99, TPS, RTO, no split-brain.
5. Only after a full true PASS replace current live Demo Compose Order/Trade images. In this task existing `dc-saas-ordersvr{,-b,-c}` and `dc-saas-tradesvr{,-b}` remained on their October 19/20 prior images; no main Demo WAL/tenant data mutated, no live SIGKILL performed.

**T106 decision:** Common **real signed Netty WAL+CommitIndex+dual custody correctness PASS**, real two-container delivery and equal WAL bytes PASS. Strict single-record ACK **performance FAIL against target**. Actual Order/Trade business HA + automatic A↔B + funds/positions reconciliation + Demo replacement **NO-GO**.
