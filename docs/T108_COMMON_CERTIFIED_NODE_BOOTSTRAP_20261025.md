# T108 — Common-only authenticated node / partition runtime, one Netty listener for 256 shards

**2026-10-25; local Mac mini ARM64, no GitHub Actions.** The user authorized discarding old Demo partitions, WAL and test business data and restarting from zero. That removes legacy partition migration requirements, but does **NOT** permit bypassing certified ZK membership, old-primary fencing, physical Custody/READY and business-state consistency. **T108 result: Common physical-data-plane integration PASS, real Order/Trade business/automatic HA acceptance NO-GO; active Demo unchanged.**

## Committed, implemented new Common classes

Common `feat/common-t82-certified-custody-20261024` @ `1ab715b` adds four reusable physical runtime components; there is **no parallel cluster engine in Order/Trade**:

- `CommonCertifiedPartitionRuntime`: per-shard constructor requiring exact immutable Common signed WAL membership, previously created local RSA signer, previously installed Common `NodeClusterControlManager`, current old-Epoch authorization, disk `CommonFileBusinessWal`, physical `DurableWalCommitIndex`, signed `DurableWalCertificateCustody` and `DurableWalCustodyReceiptLedger`, and existing `DirectNettyCertifiedBusinessTransport`. The real authenticated ZK grant must prove exact service partition, Epoch, strict ACK mode, Primary *and* Replica physical voter identity; a substituted physical signer or RF3 topology unsupported by the current ZK node manifest is **rejected**. No ZK traffic in WAL/receipt hot path.
- `CommonCertifiedNodeNettyDispatcher`: an immutable map of 1–256 admitted partition runtimes, dispatching both binary WAL replication and signed custody controls over **one shared Netty server**. Unknown partition/operation errors fail closed; no one-listener-per-shard design.
- `CommonCertifiedNodeRuntime`: checks that **all** local assigned partitions have authenticated Common grants and matching service/node/Epoch identity, exposing only certified Primary business writers. It starts a single existing `DirectNettyReplicationServer` after verifying every installed local partition; a missing partition or revoked grant prevents startup/ACK.
- `CommonCertifiedNodeBootstrap`: complete Common-owned fresh-data-plane factory that reads existing `PartitionAssignment`/`PartitionReplicaGroup` and `DurableWalShardMembership` APIs, validates distinct voter node RSA keys and mapped Netty endpoints, checks the live Common signed ZK node grant for every installed partition, proves original node RSA private/public-key possession, creates partition runtimes and starts the one-node Netty listener only when all required assignments are certified. **It does not fabricate a ZK READY, grant a new lease, roll an Epoch, generate RSA keys or perform an automatic promotion.** A genuine certified Genesis or prior snapshot/recovery remains a prerequisite.

## Source and regression evidence

| Source | Branch | Pushed commit | Latest clean tests |
| --- | --- | --- | --- |
| `com.app.common` | `feat/common-t82-certified-custody-20261024` | `1ab715b` | **496 tests, 0 failures, 0 skips** |
| shared `com.app.dc` | `feat/t85-common-ha-integration-20261024` | `902984e` | **41 tests, 0 failures/skips** |
| `ordersvr` | `feat/t93-order-common-only-delete-20261024` | `765d4b7` | **166 tests, 0 failures, 2 skips** |
| `tradesvr` | `feat/t92-trade-common-only-delete-20261024` | `5b110c8` | **190 tests, 0 failures/skips** |

Shared dependency hashes, verified inside both candidate Docker images:

- `com.app.common:3.0.22-t108-certified-node-20261025-SNAPSHOT` = `90c4b8ab3b378a61c67607221400fa1da55e0aa8fe3bb19408c46e7064290ff8` (SHA-256).
- `com.app.dc:0.0.5-t108-certified-node-20261025-SNAPSHOT` = `33bb58ffd3dc380074741f6c83814ca030c540514074dd7426f37aec72013c3f` (SHA-256).

## New ARM64 immutable candidate Docker images

| Image | Actual image ID |
| --- | --- |
| `local/otc-t108-ordersvr:common-zk-765d4b7` | `sha256:41f8291ba40f427e1a555507d86f6af54b5d5885654fef6180299ade0895ae8c` |
| `local/otc-t108-tradesvr:common-zk-5b110c8` | `sha256:ee0069f0eeb40249c662d113fe0b69d5e3a1830a24a069c2ad1f5262a10acbf0` |

Both have one newly pinned Common jar, no old `com.app.dc.service.cluster` bytecode directory, no baked `*.pk8` private keys, and explicit `dc.release.authorized=false`. `tests/verify-t108-certified-node-business-images.py` passes real binary/class/jar checks but outputs release `NO-GO`, with 12 blockers; `--strict-release` exits **2** as intended.

## Real physical tests and limitations

- `CommonCertifiedPartitionRuntimeTest` **5 PASS**: existing RSA A/B, real Netty and separate original disk WAL/Custody, strict client `QUORUM_DURABLE` ACK, local A Primary lease revocation, B Replica lease revocation, untrusted node identity failure, one Netty listener routing P090 and P128 into separate WAL/receipt directories without cross-partition acceptance.
- `CommonCertifiedNodeRuntimeTest` **5 PASS**: full node bootstrap, missing local-partition census rejected, test-only ZK grant revoked → no more writes, existing RSA substitution rejected, RECOVERING ZK manifest rejected, signed physical voter B silently replaced by C rejected. **The ZK grants in these deterministic tests were test-only and do NOT constitute actual live ZooKeeper CAS quorum certificates.** Real Common `ZkNodeScopedControlPlane` must be configured with `CertifiedNodeRecoveryGate` and its authentic physical evidence source before production readiness.
- The latest real Docker A/B integration smoke via `tests/t108/run-certified-two-jvm.sh` uses two separate JVMs **inside the newly built Order/Trade images**, real internal Docker TCP, **real fresh `CommonFileBusinessWal`**, separate local evidence volumes, real RSA A/B **read-only original Demo mounts**, independently installed signed CommitIndex/Custody and strict ACK: **8/8 certified transactions PASS**, byte-for-byte A/B WAL SHA-256 equal. This transport test runs a dedicated probe main class, **not the actual Order/Trade Spring business services**.
- Eight sequential strict ACK sample timings: **p50 67.730 ms**, p95/p99 1,224.183 ms (small cold-start-heavy sample, not a stable percentile estimate). **Still above target** p50 5–10 ms: group commit and certificate fsync amortization are not yet implemented across the real business paths.
- All A/B Docker JVMs were on ONE Mac mini, not two independent physical host failures. Proving 2/2 signed node identity is not proving cross-host high availability.

## Remaining blockers to fresh-cutover acceptance

1. The new **Common-only** `CommonCertifiedNodeBootstrap` is not yet instantiated from the **real** Order/Trade Spring runtime: the services must provide their ZK node-level authentic CAS `NodeClusterControlManager`, actual persisted signed recovery/custody authority and server startup lifecycle, node RSA alias mapping to existing Demo A/B keys, actual certified `PartitionAssignment` census, peer endpoint mappings and physical Netty bind. Existing production `OrderClusterAdapter.init()` / `TradeClusterAdapter.init()` still fail closed without a fully installed business runtime. **Do not merely remove these throw guards.**
2. On fresh empty WAL storage, signed ZK Genesis must explicitly be authenticated; **an empty file is not proof of committed Genesis or authority**. No old READY or old-ZK membership may silently be recycled. `CommonCertifiedNodeBootstrap` does not elect/mark READY; Common control-plane Genesis/recovery must do so with proofs.
3. Order/Trade mutation-to-WAL **atomic ordering is still incomplete**. Order new/cancel/modify/matching/exec and Trade account/balance/position/fill/dedup must construct full domain command **before** externally visible mutation, commit through Common strict ACK, apply atomically only after successful certificate custody; authentic Snapshot/replay must agree with mysql/projection authority. Service safety blocks correctly remain active until this is fully done.
4. Only then boot the new isolated three-ZK fresh demo stack and exercise real account funding/maker/taker/cancel/fill/position and 256 shards, automatic SIGKILL A→B→A, survive/rejoin and certified identical authoritative watermarks, then 10/50/200 tenants, 2–3× burst, latency/TPS/RTO and double-Primary checks.
5. The user has authorized deleting all obsolete partitions and test business data at cutover, but T108 **did not delete active Demo WAL, MySQL or tenant data, did not swap active Order/Trade images, and did not attempt false SIGKILL/failover**. Existing public Demo remains on previous October 19/20 images to avoid a destructive outage while the certified new service boot is unavailable.

**T108 verdict: Common node physical runtime, multi-shard Netty and certified-control integration scaffolding PASS; real services and automatic HA still NO-GO.**
