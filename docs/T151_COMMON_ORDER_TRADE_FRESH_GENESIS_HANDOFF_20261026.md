# T151 — Common / Order / Trade real first-Genesis intake status (2026-10-26)

Baseline: T149 isolated macOS ARM64 3×ZooKeeper + Order-A/B/C + Trade-A/B, all service candidates in `RECOVERING`; T150 signed original Genesis Order P090 A/B, Order P091 C/B, Trade P090 A/B. T84 Common Demo is separate and has never been replaced.

## Confirmed live outcomes

| Checked | Executed evidence |
| --- | --- |
| T149 independent 3-ZK candidates | 3/3 running, no host-exposed ports |
| T150 original E1 signed Genesis quorum reopen | Order P090 A/B, P091 C/B, Trade P090 A/B: **6/6 PASS** |
| T150 corruption rejection | Three original-Primary quarantine test copies: **3/3 PASS**, original Genesis unchanged |
| Current T149 real Common ZK ephemeral leases and TCP/Netty business reject | Order A/B/C + Trade A/B: **5/5 PASS** after T151 source changes |
| Demo T84 | A/B and 3-ZK still running |
| Former formal Order/Trade | 5 service containers remain stopped, intentionally NOT replaced |
| Actual authenticated Order/Trade business restart and automatic READY | **NOT DONE / NO-GO** |

T150 repeatable command (in current original Mac):
```bash
bash tools/t149-recovering-only/verify-t150-post-genesis.sh
```
This is a read-only validation, NOT initial install or READY publication.

## T151 multi-repo source delivered

| Repository / candidate | Reviewed source | Test evidence | Status |
| --- | --- | --- | --- |
| Common | [PR #33](https://github.com/bliplink/com.app.common/pull/33) (built on Common [PR #32](https://github.com/bliplink/com.app.common/pull/32)) | Offline full Maven **560/560 pass, 0 skipped**, with original Demo RSA | PR open; no image rollout |
| Order | [Draft PR #20](https://github.com/bliplink/com.app.dc.ordersvr/pull/20) based on T145 | Full Maven **178 tests, 0 fail/errors, 2 skip** | Draft: fresh E1 byte-equivalence integration missing |
| Trade | [Draft PR #37](https://github.com/bliplink/com.app.dc.tradesvr/pull/37) based on T143; captures previously unpushed T146–T148 plus T151 | Full Maven **213/213 pass, 0 skipped**, with real Common Netty/Custody Newing tests | Draft: fresh E1 byte-equivalence integration missing |

Mac Native GitHub HTTPS port 443 was unreachable. GitHub connector created the corresponding remote commits/PRs. The Trade PR aggregates all 16 altered files from original T146–T148 local commits plus the T151 business snapshot timestamp change, not an independently merged release.

### What actually changed

- **Common**: `CommonCertifiedFreshGenesisSnapshotPreflight` reopens original dual-RSA E1 signed quorum Genesis plus locally fsynced image, demands live external Common E1/zero-WAL writer-fencing census before/during/after exclusive business snapshot capture, and compares *opaque actual loaded* `ReplicatedStateMachine.snapshot()` bytes against signed Genesis. Result is strictly an immutable read-only observation, NEVER a READY grant. Real RSA tests: **3/3 new + 3/3 original Genesis**, no skip; full Common regression 560.
- **Order/Trade**: actual business snapshot capture sets canonical `createdAt=1` **only** if complete Common `RecoveryRequest` has local epoch/seq 0, snapshot E1 seq0, committed head E1 seq0, zero committed state/marker, and no same-Epoch replay; all later snapshots retain wall-clock time. This eliminates a timestamp-only mismatch against the T150 E1 signed image. The full *loaded business snapshot against original certificate* test is still missing: file editor execution was blocked when attempting to add Order's targeted test; the source candidates were not enabled or deployed.
- **Common T150**: the signed HEAD/Manifest/Data/DurablePrefix injection seam exists in PR #32, **but no actual authoritative source callbacks are installed in the T149 candidate CommonRecoveryOnlyProcess**. Its runtime default remains an empty map and rejects all recovery RPCs.

## Why REAL READY is still NO-GO

1. **Fresh vs failover are distinct:** T150 E1 signed Genesis has `seq=0`. Do not reuse `CommonCertifiedGenesisSurvivorInstall` which requires `seq>0` physical committed WAL/custody and genuine old-owner revocation. Do not fake HEAD or a zero WAL commit certificate.
2. **Actual application state:** T149 candidate processes are recovery-only, NOT Spring Order/Trade business runtimes. No authoritative live loaded OrderManager / Trade account/position/dedupe capture has yet been fed to Common's new preflight. No real `LiveFreshCensus` implementation is wired to a local business barrier and original E1 zero-prefix voter proof.
3. **Signed source and physical evidence:** Common RecoveryOnlyProcess still rejects recovery source calls; no actual persisted business Snapshot/WAL source HEAD/MANIFEST/DATA/PREFIX registered. All Docker volumes are on one Mac, so names such as `t150-isolated-volume-A/B` do **not** prove separate physical fault domains.
4. **Install and publish:** No authenticated fresh E1 Common install and cross-JVM durable `REPLAY_COMPLETE` / business-memory proof, independent old listener fencing plus Common ZK READY CAS, then authenticated writer process startup. No new executable business image has been deployed.
5. **Business/HA:** Order NEWING → Trade margin → Order NEW transaction saga/reconciliation, real cancel/match/fills/balances/positions/Projection and automated A→B→A while trading are still NO-GO.

## Strict next sequence

1. Add actual Order+Trade **fresh E1 byte-for-byte snapshot tests using populated real business managers**, canonical time, authenticated request, and negative nonempty/different-state cases; finish review of Draft PRs #20/#37. Do not use newly constructed empty DTO as evidence of true loaded state.
2. Implement **Common-only** live `LiveFreshCensus`: real ZK session/CAS E1 RECOVERING census and each real original voter durable zero-WAL proof. No new service election, WAL or local READY.
3. Execute T151 Common preflight against an actual business-loaded state under a true exclusive business barrier, in a fresh isolated candidate workflow without exposing external writer sockets; require signed original Genesis equality on **both** original voters.
4. Wire Common authentic initial install, durable business journal baseline, snapshot restore + replay, external proof and cross-JVM handoff. Only then retire recovery listeners and use Common ZK READY and the new certified writer runtime, with no forced phase edit.
5. Validate business end-to-end and inject actual automatic Order/Trade A→B→A SIGKILL; reconcile Order/Trade/Projection, then expand 256 partitions and 10/50/200 tenants.

**No completion claim for T151 initial READY or HA.** This handoff is intentionally precise and does not substitute labels, test stubs or artificial proofs for business recovery.