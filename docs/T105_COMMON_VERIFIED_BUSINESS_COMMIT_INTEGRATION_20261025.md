# T105 — Common-only physically certified business-command boundary, Order/Trade replay codecs

**2026-10-25**, local Mac mini. Source pushed; local ARM64 candidates built. **No GitHub Actions; no official Demo Compose replacement, trading, SIGKILL, or false READY/ACK.**

## What actually changed

Prior T104 had the original Common pieces for Netty WAL, `DurableWalGroupCommit`, signed RF2 WAL-quorum, `DurableWalCommitIndex`, disk-installed certificate custody and signed dual custody receipt ledger, strict ACK gates and old-Epoch fencing. They were present but **not composed into one business-facing durable-commit admission**. T105 adds **only shared Common coordination and routing**, NOT another replication/election algorithm:

- `CertifiedBusinessCommandBoundary` takes actual existing Common `DurableWalGroupCommit.Writer`, physically fsynced WAL, independently signed remote WAL-fsync receipts, persisted certified CommitIndex, independently fsynced Custody and persisted dual-signature receipt quorum, and a cached Common old-Epoch/Primary grant. It cannot return `QUORUM_DURABLE` before each check succeeds. Any uncertain/failed commit poisons the writer until externally certified recovery. Physical replication/receipt collection is a required injected adapter, **not** a fake local fallback.
- It accepts a **pure immutable business-record encoder that receives the exact Common-assigned partition/Epoch/sequence**. Services can reuse their original replay binary/text format rather than creating unrecognized WAL records. One coordinator instance binds exactly one pre-authorized partition/Epoch.
- `CertifiedBusinessCommandRegistry` looks up only explicitly installed partition writers. It cannot create a local writer, infer an owner, or grant READY.
- Order `OrderStateJournal` and Trade `TradeStateCoordinator.record()` now encode original `STATE_UPSERT`/`STATE_REMOVE` or `STATE_BATCH` journal envelopes and submit them through Common's certified registry when a genuine registry exists. They have no service-owned WAL writer or replica. The actual Spring `CertifiedBusinessCommandRegistry` is **NOT YET instantiated with production Netty physical writers**: business entrypoints remain fail-closed.

**CRITICAL remaining business-atomicity issue:** Order's initial-order `AbstractStrategy` stages domain records before making an order live, but its `OrderStateJournal.beginSynchronousBatch()` is still disabled; Order has other mutate-then-record paths. Trade has mutate-then-record execution/position/balance paths. T105 is an actual Common write admission and record-format foundation, **not** a claim that every business operation is now safe or usable. Do not remove Order/Trade startup fail-closed guards until all affected business state transitions have a certified atomic commit before visibility, correct snapshot/READY, and physical real-network backend.

## Verified with previously existing Demo RSA (no new key generation)

One real file-backed test uses the previously created `CommonHaDemoA` and `CommonHaDemoB` RSA private/public key pairs **read-only**, two separate local WAL files, real Java `FileChannel.force(true)`, Common's real signed `DurableWalCommitQuorum` receipts, `DurableWalCommitIndex` on disk, two separate `DurableWalCertificateCustody` dirs and the persisted `DurableWalCustodyReceiptLedger`:

| Case | Result |
| --- | --- |
| A and B fsync, sign, persist certificate, separately install Custody, verify durable ACK | PASS |
| B fsync signature absent | No quorum / no ACK; writer poisoned, CommitIndex stays at 0 |
| B custody receipt absent | No ACK; writer poisoned, even if earlier WAL certificate is durable |
| Service-specific Order/Trade encoded business records preserve Common-provided Epoch+sequence in original restore format | PASS |
| Service without real Common registry | Fail closed |

**Same-host caveat:** both test RSA nodes and WAL disks are simulated independent JVM identities on the *same Mac*. These tests demonstrate signature/certificate enforcement and real fsync primitives but are NOT an actual multi-host durability/HA validation.

## Pushed Git branches / immutable local versions

| Repo | Branch | Latest Git SHA | Clean regression |
| --- | --- | --- | --- |
| `com.app.common` | `feat/common-t82-certified-custody-20261024` | `a53af11` | 479 tests, 0 errors, 0 skipped |
| `com.app.dc` | `feat/t85-common-ha-integration-20261024` | `01b3746` | 41 tests, 0 errors/skipped |
| Order | `feat/t93-order-common-only-delete-20261024` | `1b42f31` | 165 tests, 0 errors, 2 skipped |
| Trade | `feat/t92-trade-common-only-delete-20261024` | `2555159` | 190 tests, 0 errors/skipped |

New version was **installed locally** (not published to Maven Central) as:

- `io.github.bliplink:com.app.common:3.0.22-t105-singlecore-20261025-SNAPSHOT` SHA-256 **`730c743cb01394df6e6c194441fd4d81ecc077dee281ab2620150b2d64aa355c`**.
- `io.github.bliplink:com.app.dc:0.0.5-t105-singlecore-20261025-SNAPSHOT` SHA-256 **`309a75952393886b0732d364c2ca80d4dda6338bc1b52b68c206b791d06295ed`**.

Both Order/Trade Maven dependency trees and Docker builds have **exactly those same two JAR digests**, no old `com.app.dc.service.cluster` package, no private PKCS#8 files in images, and use existing mounted Demo RSA A/B identities.

## Real Docker evidence (not service readiness)

| Candidate | Actual Linux ARM64 image ID |
| --- | --- |
| `local/otc-t105-ordersvr:common-physical-1b42f31` | `sha256:ed9d52818c486e6c419d0c66736470215826665cb30af8eaf74bedd078dbfabe` |
| `local/otc-t105-tradesvr:common-physical-2555159` | `sha256:7649ae28be2c899dda1ac6d7689485d7d2adf2461f170e16607767a6fe172374` |

Both actual Docker JVMs were probed with `--network none --read-only` and `:ro` mounts of already-existing Demo A/B private identity and common public trust directory. Classloading confirms the Common business certified writer/registry resolves from the **new pinned Common JAR**, Order/Trade business state recorder has the exact Common registry field, legacy private HA classes are absent, existing node RSA sign/verify succeeds, and no container startup or physical real trading ACK/READY was claimed.

`tests/verify-t105-common-certified-business-images.py`: binary gate PASS, release `NO-GO` (12 blockers), `--strict-release` returns **2**. It checks both real images, source SHA labels, actual jar bytes, absence of old service HA, existing-key loader, Common proof wiring and no private keys. Publication labels remain `dc.release.authorized=false`.

## Next actual implementation / release criteria

1. **Install production `CertifiedBusinessCommandBoundary.PhysicalTransport` per partition** wired to the *already existing* Common Netty and physical receipt protocols. Resolve local WAL path/lock, stable certified membership, Primary permit, actual peer addresses, independent signed receipt and replica post-fsync custody. **No per-record ZK hot-path calls** and no generated RSA keys.
2. Extend Common's existing 64-record group fsync/cumulative signed-cert facilities to each Order matching batch, and use original Order replay codec for *every* state effect before publication; never let matching/cancel partially mutate business while custody fails.
3. Stage Trade balance/position/dedupe/fills as a single immutable full state batch **before** visible account mutations, then apply only after valid Common durable ACK; preserve exactly-once identities and signed CommitIndex continuity.
4. Bind `CertifiedPersistedCustodySource`, authenticated snapshots/replay, old-owner fencing, Common READY, and independent MySQL/Projection reconciliation. Then run 3 isolated ZK voters with real Order/Trade A/B JVMs, real API and maker/taker/funding/position activity. SIGKILL A→B→A without scripts forcing a role, verify catch-up, no double-primary, no lost/duplicate fills and measure ACK latency/TPS/RTO.
5. Only after true PASS change active Demo Docker images. Existing live Demo Order/Trade remain on 2026-10-19/20 versions; no live data/volumes removed and no service failover was attempted during this task.

**T105 gate:** Common durable business command coordination + original domain WAL record format + image packaging **PASS**; real Order/Trade physical business backend, transaction safety, auto-failover, certified READY and Demo release **NO-GO**.
