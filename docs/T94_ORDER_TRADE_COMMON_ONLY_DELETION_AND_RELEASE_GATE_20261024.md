# T94 | Order & Trade private-HA removal and Common-only candidate images

**Date:** October 24, 2026. **Decision: NO-GO for Demo rollout and real A↔B auto-failover.**

## Immutable intent

Only the existing, independently verified **Common HA engine** may elect primaries, manage membership, replicate physical WAL, certify CommitIndex + signed dual physical custody, revoke epochs, install authenticated snapshots/committed deltas, and authorize READY/strict client ACK. Neither Order nor Trade may copy its former algorithms into Common; each business service retains only matching/balances/positions, state serialization, `ReplicatedStateMachine` apply/snapshot/restore business adapter and admission to Common. No GitHub Actions until explicitly authorized.

## Committed and pushed source change

| Service | Branch | Commit | Removed private HA Java sources | Kept business/state sources |
| --- | --- | --- | ---: | ---: |
| Order | `feat/t93-order-common-only-delete-20261024` | `6a98fd9` | **31** | 15 |
| Trade | `feat/t92-trade-common-only-delete-20261024` | `7a319da` | **43** | 21 |

Both business repos have **zero source files under `src/main/java/com/app/dc/service/cluster`**. Retained business logic and Common callbacks moved to `com.app.dc.service.state`. All former service-local epoch/CAS controllers, replication managers/transports, WAL journals/stores, recovery/rejoin coordinators, snapshot WAL network/installation, and service-local READY transitions are deleted, not hidden behind new class names. `com.app.common` branch `feat/common-t82-certified-custody-20261024` remains commit `5ce1b3a`: **unchanged** and no old Order/Trade code moved into it.

Other business behaviors retained: tenant-aware matching, client-order ID idempotency, admission/drain mutex, Trade balance/position/execution state mutation callbacks, post-recovery business restore, and Common state-machine input validation. Old service-local projection committed-journal readers and writers also removed; they MUST be rebound to Common committed events before business E2E can pass.

## Honest test accounting

`mvn -q -o clean test` **actual clean build and run** on the local Mac mini:

| Candidate | Clean JUnit suites | Tests | Failed / errors | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Order | 45 | **141** | 0 | 2 |
| Trade | 45 | **167** | 0 | 0 |

The old HA implementation's tests were deleted with that implementation (45 Order / 51 Trade obsolete test source files). **The lower test counts are not equivalent to a passing HA regression.** New source invariants reject the reintroduction of service-private cluster classes and verify that missing Common WAL/custody causes a fail-closed startup/command denial. Full business UI/API, real matching/projection/funding, multi-JVM and physical failover tests against the candidate images are **NOT done**.

## Actual T94 ARM64 Docker builds

| Service | Candidate local image | Verified image ID |
| --- | --- | --- |
| Order | `local/otc-t94-ordersvr:common-only-6a98fd9` | `sha256:3172d4358d4672e429bacbc5b5c4dca0c5824f372cc7d6d48638b3118018cbc9` |
| Trade | `local/otc-t94-tradesvr:common-only-7a319da` | `sha256:8bba8f522abe43108570983b1a0fa5c798028483275e9cd74c98033122f5a108` |

Local Docker builds succeeded using 100% replaced service `classes/` and dependency `lib/` layers, without any stale service `cluster` classes. Each has exactly one `com.app.common` JAR, SHA-256 `cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3`, identical to the tested Common+Demo and other business candidate. Both images are **marked `dc.release.authorized=false`**.

Reproducible read-only Docker binary preflight:

```sh
python3 tests/verify-t94-common-only-images.py
python3 tests/verify-t94-common-only-images.py --strict-release  # expected exit=2 (NO-GO)
python3 tests/audit-single-common-core.py --common ... --demo ... \
  --demo-common-jar ... --order ... --trade ... --dc ...
```

`verify-t94-common-only-images.py`: actual image metadata + `docker run --network none --read-only` check on each built image. **Both binary absence/identity checks PASS**, but strict release **returns exit 2**. The tightened source auditor gives **30 PASS / 8 BLOCK / NO-GO**. Four blockers concern historical Demo test harness owners, **four are real production integration blockers**:

1. Order Common business WAL + CommitIndex/strict ACK/custody not connected.
2. Order Common certified snapshot producer not connected.
3. Trade Common business WAL + CommitIndex/strict ACK/custody not connected.
4. Trade Common certified snapshot producer not connected.

The internal service adapters deliberately throw `ORDER_COMMON_WAL_ACK_CUSTODY_NOT_CONNECTED` and `TRADE_COMMON_WAL_AND_CUSTODY_ADAPTER_NOT_INSTALLED` when cluster mode is selected; Order's snapshot writer and Trade's snapshot writer also reject capture until the Common authenticated snapshot stream is wired. **This is the correct temporary fail-closed state, not a runnable production service.** Direct READY publication was removed, and Common physical owner grants are checked instead of consulting only a cached local routing entry; however the actual grant controller is not yet installed as a production Spring bean and Common certificate-backed ACK is not hotpath-connected.

## Actual Demo and release decision

Running Demo Order/Trade services are **still the previous October 19/20 images** (three Order nodes, two Trade nodes). No T94 image was swapped into Compose, no database reset, and no SIGKILL performed. The existing Demo is already unhealthy (uncertified WAL tails cause PARTITION_NOT_READY/Robot ERROR; prior fresh-QA custom-price publish returned `9000 INTERNAL_ERROR`). Deploying a candidate that deterministically refuses clustered startup would cause an outage and would not test A↔B at all.

**Remaining actual engineering before deploying and injecting SIGKILL:**

1. Install genuine Common `ZkNodeScopedControlPlane`, `NodeClusterControlManager` with physical signed custody verifier, and Common `DurableWalGroupCommit`/CommitIndex/Netty WAL custody under both services' business adapters. No direct ZK reads in WAL hotpath, no service-local fallbacks. Preserve standalone business behavior only when genuinely unclustered.
2. Implement service-specific business snapshot data source and committed-diff consumer under Common `StateMachineRecoveryCoordinator`, with external Projection watermarks and financial reconciliation. Do not publish READY before old owner fenced, authorized epoch, WAL head, and independent custody proofs.
3. Clean-build and run new, non-obsolete Order/Trade tests; prove signed real client ACK with two physical JVMs; run actual QA tenant register/deposit/limit-match/cancel/positions/balance/history/Projection reconciliation.
4. Rebuild immutable images; strict source and image **release checks must pass**. Then update Demo Compose with preserved rollback reference and monitor user-facing business flows.
5. During active robot trading perform genuine **automatic** A→B→A role reversal, kill/restart/catch-up, absence of split brain/duplicate fills/lost certified ACKs; quantify RTO, WAL p50/p95/p99, TPS and 10/50/200-tenant load.

**Do not use the T94 candidates in the live demo yet; these are code-deletion and binary-integrity artifacts, not completed Common HA integrations.**
