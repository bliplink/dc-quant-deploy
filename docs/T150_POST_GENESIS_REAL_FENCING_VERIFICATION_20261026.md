# T150 independent post-Genesis live-container regression

Date: 2026-10-26 (macOS ARM64), started from exact T149 commit `9e775454aed436e662f635919f1d818fad685cdc`. This report covers **observed** state, not a production-ready deployment.

## Read-only verification actually executed

Script: `tools/t149-recovering-only/verify-t150-post-genesis.sh`.

The Mac candidate stack `otc-t149-ha-intake` contained real running ZooKeeper zk1/zk2/zk3 and Order-A/B/C + Trade-A/B; the original T84 Demo stack remained running separately. The runtime T150 prototype `T150RealEmptyBusinessGenesis` had already emitted original node-local Genesis images, two RSA voter receipts and sealed image/quorum files per shard on each of its voters. The verifier invokes that helper's **read-only** `--verify` entrypoint separately in the corresponding business container. It reopens the Common-certified Genesis files with the exact pinned original RSA membership, recomputes the actual service's fresh empty serialized snapshot bytes, and requires `businessReady=false`.

| Scope | Physical-container checks | Outcome |
| --- | ---: | --- |
| Order P090 | Order-A and Order-B | 2/2 PASS |
| Order P091 | Order-C and Order-B | 2/2 PASS |
| Trade P090 | Trade-A and Trade-B | 2/2 PASS |
| **Common Genesis reopen** | **6 total** | **6/6 PASS** |
| Post-Genesis Common ZK ephemeral lease, Netty business ReplicationBatch deny, unsigned WAL_COMMIT deny | Order-A/B/C, Trade-A/B | **5/5 PASS** |
| 3 separate ZooKeeper containers running | zk1/zk2/zk3 | **3/3 PASS** |

Observed terminal markers:

```
T150_REAL_ZK_THREE_RUNNING_PASS
T150_POST_GENESIS_6_RSA_REOPEN_5_FENCED_PASS
T150_NO_GO: one-Mac volumes are NOT independent physical hosts. No certified business replay, READY or HA promotion.
```

Reproduce on the exact isolated T149 Mac stack **after** the T150 helper class has been compiled and staged in the candidate containers. The previously Mac-only prototype source is now also checked in as `tools/t149-recovering-only/bootstrap/T150RealEmptyBusinessGenesis.java` (lab utility, not an authoritative snapshot writer):

```bash
bash -n tools/t149-recovering-only/verify-t150-post-genesis.sh
bash tools/t149-recovering-only/verify-t150-post-genesis.sh
```

Build the lab helper for each service with the exact Common T143 jar (SHA256 `9197029483a8d18032de0a8ca2f8888a9e62d8933b8cf8d4604206e246ca60ea`): `bash tools/t149-recovering-only/compile-t150-genesis.sh order <T145-target/dependency> <output-dir>` and the same command using `trade` + T148 dependencies. Both compiled as Java 8 bytecode (major version 52) on the local Mac, PASS. This does **not** stage/execute a new signing operation. Existing T149 containers already have the prior isolated compiled helper in `/tmp`.

The read-only verification script inspects real node config paths for node identity and Common manifest/lease/port only; it does not output config secrets or read the RSA private bytes itself. It performs read-only signed Genesis reopens and negative Netty RPC probes. **It does not bootstrap, sign, install, grant READY, switch primary, alter any ZK node, or change T84 Demo.** The lab helper is not an authoritative snapshot source and MUST NOT be used to sign a nonempty or production domain image.

## Signed Genesis corruption rejections (additional live lab check)

The source helper's `--negative` mode was executed in the three **original primary** candidate containers: Order-A/P090, Order-C/P091 and Trade-A/P090. Each tampered a *temporary quarantine copy* of an RSA voter signature and a sealed `.quorum`, required `CommonCertifiedGenesisQuorum` rejection, removed the quarantine copy, and successfully reopened the unchanged original durable certificate: **3/3 PASS**. This is not a test of real business recovery, READY or cross-host quorum.

## Remaining release blockers — explicit NO-GO

1. **Physical fault domains are not independent.** All service and ZK containers are on one Mac. The development membership's node/volume names are labels, not evidence of independent hardware. Local RSA proofs must not be marketed as cross-host quorum.
2. **Empty business snapshot versus authoritative live state:** The T150 local helper builds fresh `OrderPartitionSnapshot`/`TradePartitionSnapshot` objects and checks their empty schema. This is **not** yet proof that all authoritative Order/Trade state stores, concurrent writers, WALs and service business managers are consistently empty. Validate the canonical application snapshot-producing/rehydrating paths before promoting any business workload.
3. The currently deployed T149 `CommonRecoveryOnlyProcess` still supplies `Collections.emptyMap()` as signed source handlers. A separate Common T150 source branch adds an opt-in typed factory, but **that candidate binary is not deployed**, and there is no certified Common HEAD/MANIFEST/DATA/DURABLE_PREFIX service or authenticated Snapshot/WAL source for these real containers.
4. A signed Genesis alone cannot satisfy `CommonDurableBusinessReplayHandoff`, restored business-in-memory state proof, fresh ZK assignment/epoch checks and new business writer process. No READY has been published, and the existing recovery Netty listeners correctly refuse writes.
5. The full Order pending NEWING → Trade reserved margin → Order active NEW saga, cancel/match/fill/Projection replay, actual SIGKILL A→B→A, 256 shards and 10/50/200 tenant load remain unverified.

**Overall:** T150 post-Genesis cryptographic reopens and fail-closed runtime were verified; the actual business-state recovery/READY integration remains **NO-GO**. Continue by providing a genuine authoritative business snapshot adapter and signed, fenced Common recovery source instead of toggling the runtime phase or writing an unsigned marker. Do not replace the old formal Order/Trade containers or touch T84 Demo.